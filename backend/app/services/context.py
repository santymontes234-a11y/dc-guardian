"""Who is acting and under which correlation id — passed from routers into services."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.db.types import utcnow
from app.models.enums import ActorType
from app.services import audit


@dataclass
class ActorCtx:
    actor_type: ActorType
    actor_id: int | None = None
    correlation_id: str | None = None
    now: datetime = field(default_factory=utcnow)  # injectable for tests

    @classmethod
    def system(cls, now: datetime | None = None) -> "ActorCtx":
        return cls(ActorType.SYSTEM, now=now or utcnow())

    def audit(
        self,
        db: Session,
        action: str,
        entity: str | None = None,
        entity_id: Any = None,
        details: dict | None = None,
    ):
        return audit.record(
            db,
            action=action,
            actor_type=self.actor_type,
            actor_id=self.actor_id,
            entity=entity,
            entity_id=entity_id,
            details=details,
            correlation_id=self.correlation_id,
        )


def diff_fields(obj: Any, changes: dict[str, Any]) -> dict[str, list]:
    """Apply ``changes`` to ``obj`` and return ``{field: [old, new]}`` for real changes."""
    out: dict[str, list] = {}
    for name, new in changes.items():
        old = getattr(obj, name)
        if old != new:
            setattr(obj, name, new)
            out[name] = [old, new]
    return out
