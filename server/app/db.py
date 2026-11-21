"""DB 엔진·세션. 엔진은 처음 쓸 때 연결하므로 DB가 꺼져 있어도 서버는 뜬다 (그때 /health가 503)."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .core.config import settings

CONNECT_TIMEOUT_S = 3  # DB가 꺼져 있을 때 /health가 오래 기다리지 않게


class Base(DeclarativeBase):
    """테이블 모델의 부모 클래스 (app/models.py)."""


def make_engine(url: str, **kwargs) -> Engine:
    if url.startswith("postgresql"):
        kwargs.setdefault("connect_args", {"connect_timeout": CONNECT_TIMEOUT_S})
    engine = create_engine(url, pool_pre_ping=True, **kwargs)
    if engine.dialect.name == "sqlite":
        # 테스트용 SQLite는 기본으로 외래 키를 검사하지 않는다 (ON DELETE CASCADE도 안 됨)
        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    return engine


engine = make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """요청마다 세션 하나. API 함수에서는 `db: DB`로 받는다 (app/api/deps.py)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
