"""영수증 자동 인식 API: 올린 사진 이름으로 초안을 받는다 (stub 엔진이라 OCR 설치 없이 돈다)."""

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


def upload(client) -> str:
    return client.post("/api/v1/receipt-photos", files={"file": ("r.png", PNG, "image/png")}).json()["photo_url"]


def test_recognize_uploaded_photo(client):
    res = client.post(upload(client) + "/ocr", params={"engine": "stub"})
    assert res.status_code == 200
    body = res.json()
    assert body["draft"]["store_name"] == "같이고기 경기대점"
    assert body["draft"]["total_amount"] == 93000
    assert body["draft"]["items"][-1] == {"name": "제휴할인", "amount": -5000, "kind": "DISCOUNT"}
    assert body["check"] == {"items_sum": 93000, "difference": 0, "is_matched": True}
    assert body["engine"] == "stub"
    assert {ln["role"] for ln in body["lines"]} >= {"store", "item", "discount", "total", "ignored"}


def test_missing_photo(client):
    res = client.post("/api/v1/receipt-photos/" + "0" * 32 + ".png/ocr")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "NOT_FOUND"


def test_engine_unavailable(client, monkeypatch):
    def broken(name):
        raise EngineUnavailable("tesseract 프로그램을 찾을 수 없습니다")

    monkeypatch.setattr(ocr_api, "get_engine", broken)
    res = client.post(upload(client) + "/ocr", params={"engine": "tesseract"})
    assert res.status_code == 503
    assert res.json()["error"]["code"] == "OCR_UNAVAILABLE"
