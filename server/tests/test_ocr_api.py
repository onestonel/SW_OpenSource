"""영수증 자동 인식 API: 영수증에 올린 사진으로 초안을 받는다 (stub 엔진이라 OCR 설치 없이 돈다)."""

from __future__ import annotations

import io
import json
import urllib.error

import pytest

from app import storage
from app.api.v1 import ocr as ocr_api
from app.ocr import run_ocr
from app.ocr.engines import EngineUnavailable, get_engine

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


@pytest.fixture(autouse=True)
def tmp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "storage_dir", lambda: tmp_path)
    return tmp_path


def make_receipt(api) -> str:
    """정산방 · 영수증을 만들고 그 영수증의 사진 주소를 돌려준다."""
    room = api.post("/rooms", {"name": "제주 여행", "members": ["A", "B"]}).json()
    body = {"store_name": "1차 식당", "payer_member_id": room["members"][0]["id"], "total_amount": 10000,
            "items": [{"name": "김치찌개", "amount": 10000}]}
    receipt = api.post(f"/rooms/{room['room_token']}/receipts", body).json()
    return f"/api/v1/rooms/{room['room_token']}/receipts/{receipt['id']}/photo"


def upload(client, api) -> str:
    url = make_receipt(api)
    assert client.post(url, files={"file": ("r.png", PNG, "image/png")}).status_code == 200
    return url


def test_recognize_uploaded_photo(client, api):
    res = client.post(upload(client, api) + "/ocr", params={"engine": "stub"})
    assert res.status_code == 200
    body = res.json()
    assert body["draft"]["store_name"] == "같이고기 경기대점"
    assert body["draft"]["total_amount"] == 93000
    assert [i["name"] for i in body["draft"]["items"]] == ["삼겹살", "목살", "된장찌개", "맥주", "제휴할인"]
    assert body["draft"]["items"][-1] == {"name": "제휴할인", "amount": -5000, "kind": "DISCOUNT"}
    assert body["check"] == {"items_sum": 93000, "difference": 0, "is_matched": True}
    assert body["engine"] == "stub"
    assert {ln["role"] for ln in body["lines"]} >= {"store", "item", "discount", "total", "ignored"}


def test_missing_photo(client, api):
    res = client.post(make_receipt(api) + "/ocr")  # 사진을 아직 안 올림
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "NOT_FOUND"


def test_engine_unavailable(client, api, monkeypatch):
    def broken(name):
        raise EngineUnavailable("tesseract 프로그램을 찾을 수 없습니다")

    monkeypatch.setattr(ocr_api, "get_engine", broken)
    res = client.post(upload(client, api) + "/ocr", params={"engine": "tesseract"})
    assert res.status_code == 503
    assert res.json()["error"]["code"] == "OCR_UNAVAILABLE"


def test_remote_engine(client, api, monkeypatch):
    """remote(OCR_ENGINE=remote): 사진을 ocr 컨테이너로 보내고, 받은 결과를 그대로 돌려준다."""
    sent = []

    def fake_urlopen(req, timeout):
        sent.append(req)
        return io.BytesIO(json.dumps(run_ocr(b"", get_engine("stub")).to_dict()).encode())

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    res = client.post(upload(client, api) + "/ocr", params={"engine": "remote"})
    assert res.status_code == 200
    assert res.json()["draft"]["total_amount"] == 93000
    assert sent[0].full_url.endswith("/ocr") and sent[0].data == PNG


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (urllib.error.URLError(ConnectionRefusedError()), 503, "OCR_UNAVAILABLE"),  # 컨테이너가 꺼져 있음
        (urllib.error.HTTPError("http://ocr:8000/ocr", 422, "", {}, io.BytesIO(b"{}")), 422, "IMAGE_UNREADABLE"),
    ],
)
def test_remote_engine_errors(client, api, monkeypatch, error, status, code):
    def fail(req, timeout):
        raise error

    monkeypatch.setattr("urllib.request.urlopen", fail)
    res = client.post(upload(client, api) + "/ocr", params={"engine": "remote"})
    assert res.status_code == status
    assert res.json()["error"]["code"] == code
