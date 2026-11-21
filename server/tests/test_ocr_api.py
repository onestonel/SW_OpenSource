"""영수증 자동 인식 API: 영수증에 올린 사진으로 초안을 받는다 (stub 엔진이라 OCR 설치 없이 돈다)."""

from __future__ import annotations

import pytest

from app import storage
from app.api.v1 import ocr as ocr_api
from app.ocr.engines import EngineUnavailable

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
