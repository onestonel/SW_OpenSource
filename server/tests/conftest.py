"""테스트 공통 준비. DB는 SQLite 메모리 DB로 바꿔 끼워서, PostgreSQL 없이도 돈다."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_db, make_engine
from app.main import app


@pytest.fixture
def client() -> TestClient:
    engine = make_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False},
                         poolclass=StaticPool)
    session_factory = sessionmaker(bind=engine)

    def override():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    engine.dispose()
