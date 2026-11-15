"""Engines and session factories.

SQLite concurrency model (single backend process, WAL):
- **Write sessions** (``SessionLocal`` / ``get_db``) start with ``BEGIN IMMEDIATE`` and take the
  write lock up front, so read-modify-write sequences (lockout counters, the audit hash chain)
  are serialized. Keep them short: never run slow work (bcrypt, face models) inside one.
- **Read sessions** (``ReadSessionLocal`` / ``get_read_db``) use a deferred ``BEGIN``: they see a
  consistent snapshot and never block writers. Use them for GET endpoints and auth lookups.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


def make_engine(url: str, *, write: bool = True) -> Engine:
    connect_args = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        db_path = url.removeprefix("sqlite:///")
        if db_path and db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, connect_args=connect_args)

    if url.startswith("sqlite"):
        begin_sql = "BEGIN IMMEDIATE" if write else "BEGIN"

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):
            # Take over transaction control from pysqlite (it never BEGINs before a SELECT).
            dbapi_conn.isolation_level = None
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=10000")
            cur.close()

        @event.listens_for(engine, "begin")
        def _begin(conn):
            conn.exec_driver_sql(begin_sql)

    return engine


_url = get_settings().database_url
engine = make_engine(_url, write=True)
read_engine = make_engine(_url, write=False)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
ReadSessionLocal = sessionmaker(bind=read_engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_read_db() -> Iterator[Session]:
    db = ReadSessionLocal()
    try:
        yield db
    finally:
        db.close()
