"""테스트 공통 준비. DB는 SQLite 메모리 DB로 바꿔 끼워서, PostgreSQL 없이도 돈다."""

from __future__ import annotations

import os

os.environ["AUTO_MIGRATE"] = "false"  # 테스트는 서버가 켜질 때 마이그레이션하지 않는다 (아래에서 테이블을 직접 만든다)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app import models  # noqa: E402,F401  (테이블을 메타데이터에 등록)
from app.db import Base, get_db, make_engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    engine = make_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False},
                         poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

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


class Api:
    """테스트용 얇은 클라이언트. 주소 앞의 /api/v1을 붙이고 상태 코드를 확인한다."""

    def __init__(self, client: TestClient):
        self.client = client

    def call(self, method: str, url: str, expect: int, **kw):
        res = self.client.request(method, "/api/v1" + url, **kw)
        assert res.status_code == expect, res.text
        return res

    def get(self, url, expect=200):
        return self.call("GET", url, expect)

    def post(self, url, json=None, expect=201):
        return self.call("POST", url, expect, json=json)

    def patch(self, url, json=None, expect=200):
        return self.call("PATCH", url, expect, json=json)

    def delete(self, url, expect=204):
        return self.call("DELETE", url, expect)


@pytest.fixture
def api(client) -> Api:
    return Api(client)


def error(res) -> dict:
    return res.json()["error"]
