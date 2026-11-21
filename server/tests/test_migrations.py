"""Alembic 마이그레이션이 모델(app/models.py)과 같은지, 되돌리기까지 되는지."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext

from app import models  # noqa: F401
from app.db import Base, make_engine

SERVER = Path(__file__).resolve().parents[1]


def test_upgrade_head_matches_models_and_downgrades(tmp_path):
    engine = make_engine(f"sqlite+pysqlite:///{tmp_path / 'm.db'}")
    cfg = Config(str(SERVER / "alembic.ini"))
    cfg.set_main_option("script_location", str(SERVER / "migrations"))
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")
        assert compare_metadata(MigrationContext.configure(conn), Base.metadata) == []
        command.downgrade(cfg, "base")
        command.upgrade(cfg, "head")
    engine.dispose()
