"""Alembic 환경. DB 주소는 DATABASE_URL. 테스트에서는 config.attributes["connection"]으로 연결을 넘겨받는다."""

from logging.config import fileConfig

from alembic import context

from app import models  # noqa: F401  (모델을 메타데이터에 등록)
from app.core.config import settings
from app.db import Base, make_engine

config = context.config
# 서버 안에서 돌릴 때(app.main.migrate)는 서버의 로그 설정을 건드리지 않는다
if (config.config_file_name is not None and not config.attributes.get("connection")
        and config.attributes.get("configure_logger", True)):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def run_offline() -> None:
    context.configure(url=settings.database_url, target_metadata=target_metadata, literal_binds=True,
                      render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _run(connection)
        return
    engine = make_engine(settings.database_url)
    with engine.connect() as conn:
        if conn.dialect.name == "sqlite":
            # SQLite의 batch 모드는 테이블을 새로 만들고 옛 테이블을 DROP한다. 외래 키 검사가 켜져 있으면
            # 그 DROP이 ON DELETE CASCADE로 자식 행을 지우거나 실패한다. 끄고 돌린 뒤 무결성을 따로 확인한다.
            conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
            conn.commit()
        _run(conn)
        if conn.dialect.name == "sqlite":
            broken = conn.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
            if broken:
                raise RuntimeError(f"foreign key check failed after migration: {broken[:5]}")
    engine.dispose()


def _run(connection) -> None:
    # render_as_batch: SQLite에서도 ALTER TABLE 마이그레이션이 돌게 한다
    context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_offline()
else:
    run_online()
