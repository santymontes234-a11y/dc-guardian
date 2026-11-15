"""The Alembic migrations must produce exactly the schema declared by the models."""

from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext

from app.db.base import Base
from app.db.session import make_engine
from app.core.config import BACKEND_DIR


def _cfg(url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "app/db/migrations"))
    cfg.attributes["url"] = url
    cfg.attributes["configure_logger"] = False
    return cfg


def test_upgrade_head_matches_models(tmp_path: Path):
    url = f"sqlite:///{tmp_path / 'mig.db'}"
    command.upgrade(_cfg(url), "head")
    engine = make_engine(url)
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn, opts={"compare_type": True, "render_as_batch": True})
        diff = compare_metadata(ctx, Base.metadata)
    assert diff == [], f"Models and migrations differ: {diff}"


def test_downgrade_to_base(tmp_path: Path):
    url = f"sqlite:///{tmp_path / 'mig.db'}"
    cfg = _cfg(url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
