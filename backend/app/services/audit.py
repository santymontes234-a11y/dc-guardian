"""Append-only, keyed hash-chained audit log.

``hash = HMAC-SHA256(audit_key, prev_hash || canonical_json(row incl. id))``.

Protections:
- Editing or deleting a middle row breaks the chain (``verify_chain``).
- The HMAC key (derived from ``DCG_MASTER_KEY``) prevents recomputing a forged chain from the
  DB file alone.
- SQLite triggers reject UPDATE/DELETE on ``audit_log`` (see ``models.monitoring``).
- ``verify_chain`` returns the head (last id + hash) so an auditor can compare it with a
  previously noted value and detect tail truncation.

Writers rely on the engine's ``BEGIN IMMEDIATE`` (``db.session``): the read of the last row and
the insert happen under the database write lock, so the chain cannot fork.
Note: rotating the master key makes older entries unverifiable.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.types import utcnow
from app.models import AuditLog
from app.models.enums import ActorType

GENESIS_HASH = "0" * 64


def _audit_key() -> bytes:
    return hashlib.sha256(b"dc-guardian/audit/v1|" + get_settings().master_key.encode()).digest()


def _canonical(entry: AuditLog) -> str:
    return json.dumps(
        {
            "id": entry.id,
            "ts": entry.ts.isoformat(),
            "actor_type": str(entry.actor_type),
            "actor_id": entry.actor_id,
            "action": entry.action,
            "entity": entry.entity,
            "entity_id": entry.entity_id,
            "details": entry.details_json,
            "correlation_id": entry.correlation_id,
        },
        sort_keys=True,
        ensure_ascii=False,
    )


def _compute_hash(prev_hash: str, entry: AuditLog) -> str:
    return hmac.new(_audit_key(), (prev_hash + _canonical(entry)).encode(), hashlib.sha256).hexdigest()


def record(
    db: Session,
    *,
    action: str,
    actor_type: ActorType,
    actor_id: str | int | None = None,
    entity: str | None = None,
    entity_id: str | int | None = None,
    details: dict[str, Any] | None = None,
    correlation_id: str | None = None,
) -> AuditLog:
    """Add an audit entry to the current transaction (caller commits)."""
    db.flush()  # earlier entries of this transaction become visible to the query below
    last = db.execute(select(AuditLog.id, AuditLog.hash).order_by(AuditLog.id.desc()).limit(1)).first()
    prev_hash = last.hash if last else GENESIS_HASH

    entry = AuditLog(
        id=(last.id + 1) if last else 1,
        ts=utcnow(),
        actor_type=actor_type,
        actor_id=None if actor_id is None else str(actor_id),
        action=action,
        entity=entity,
        entity_id=None if entity_id is None else str(entity_id),
        details_json=json.dumps(details or {}, sort_keys=True, ensure_ascii=False, default=str),
        correlation_id=correlation_id,
        prev_hash=prev_hash,
    )
    entry.hash = _compute_hash(prev_hash, entry)
    db.add(entry)
    db.flush()
    return entry


@dataclass
class ChainReport:
    ok: bool
    checked: int
    broken_at_id: int | None = None
    head_id: int | None = None
    head_hash: str | None = None


def verify_chain(db: Session) -> ChainReport:
    prev = GENESIS_HASH
    expected_id = 1
    count = 0
    for entry in db.execute(select(AuditLog).order_by(AuditLog.id)).scalars():
        if (
            entry.id != expected_id
            or entry.prev_hash != prev
            or not hmac.compare_digest(_compute_hash(prev, entry), entry.hash)
        ):
            return ChainReport(ok=False, checked=count, broken_at_id=entry.id)
        prev = entry.hash
        expected_id += 1
        count += 1
    return ChainReport(ok=True, checked=count, head_id=count or None, head_hash=prev if count else None)
