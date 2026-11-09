"""완료 기준: localhost:8000/api/v1/health 가 ok."""

from __future__ import annotations


def test_health_is_ok(client):
    res = client.get("/api/v1/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_request_id_header(client):
    assert client.get("/api/v1/health").headers["X-Request-Id"]
    assert client.get("/api/v1/health", headers={"X-Request-Id": "abc"}).headers["X-Request-Id"] == "abc"


def test_unknown_route_uses_error_format(client):
    res = client.get("/api/v1/nope")
    assert res.status_code == 404
    assert res.json() == {"error": {"code": "NOT_FOUND", "message": "요청한 주소를 찾을 수 없습니다."}}


def test_cors_allows_web(client):
    res = client.options("/api/v1/health", headers={
        "Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"})
    assert res.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_api_docs(client):
    assert client.get("/docs").status_code == 200
    assert "/api/v1/health" in client.get("/openapi.json").json()["paths"]
