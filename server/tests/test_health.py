"""상태 확인 API (#3, #15)와 공통 응답 (오류 형식 · X-Request-Id · CORS)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.db import get_db, make_engine
from app.main import app, create_app

WEB = "http://localhost:3000"


def test_health_is_ok(client):
    res = client.get("/api/v1/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "db": "ok"}


def test_health_when_db_is_down():
    """DB에 연결할 수 없으면 503. (아무도 듣지 않는 1번 포트로 접속하게 해서 실제 연결 실패를 만든다)"""
    down = make_engine("postgresql+psycopg://app:app@127.0.0.1:1/settle")

    def override():
        db = sessionmaker(bind=down)()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    try:
        res = TestClient(app).get("/api/v1/health")
    finally:
        app.dependency_overrides.clear()
        down.dispose()
    assert res.status_code == 503
    assert res.json() == {"status": "error", "db": "error"}


def test_request_id_header(client):
    assert client.get("/api/v1/health").headers["X-Request-Id"]
    assert client.get("/api/v1/health", headers={"X-Request-Id": "abc"}).headers["X-Request-Id"] == "abc"


def test_unknown_route_uses_error_format(client):
    res = client.get("/api/v1/nope")
    assert res.status_code == 404
    assert res.json() == {"error": {"code": "NOT_FOUND", "message": "요청한 주소를 찾을 수 없습니다."}}


def test_cors_allows_web(client):
    res = client.options("/api/v1/health", headers={"Origin": WEB, "Access-Control-Request-Method": "GET"})
    assert res.headers["access-control-allow-origin"] == WEB


def test_unhandled_error_keeps_request_id_and_cors():
    """처리하지 못한 예외로 500이 나도 X-Request-Id와 CORS 헤더가 붙는다 (#4 리뷰)."""
    boom_app = create_app()

    @boom_app.get("/api/v1/boom")
    def boom():
        raise RuntimeError("boom")

    res = TestClient(boom_app, raise_server_exceptions=False).get(
        "/api/v1/boom", headers={"Origin": WEB, "X-Request-Id": "req-500"})
    assert res.status_code == 500
    assert res.json() == {"error": {"code": "INTERNAL_ERROR", "message": "서버 오류가 발생했습니다."}}
    assert res.headers["X-Request-Id"] == "req-500"
    assert res.headers["access-control-allow-origin"] == WEB


def test_api_docs(client):
    assert client.get("/docs").status_code == 200
    assert "/api/v1/health" in client.get("/openapi.json").json()["paths"]


def test_migrate_failure_logs_full_error(monkeypatch, caplog):
    """migrate()가 실패하면 오류 종류만이 아니라 메시지와 traceback 전체가 로그에 남는다."""
    from alembic import command

    from app import main

    def boom(*_args, **_kw):
        raise RuntimeError("relation \"members\" does not exist")

    monkeypatch.setattr(command, "upgrade", boom)
    with caplog.at_level("ERROR", logger="settle"):
        main.migrate()  # 서버를 멈추지 않는다
    record = next(r for r in caplog.records if r.name == "settle")
    assert record.levelname == "ERROR" and "DB migration failed" in record.getMessage()
    assert record.exc_info is not None
    assert 'relation "members" does not exist' in caplog.text and "Traceback" in caplog.text
