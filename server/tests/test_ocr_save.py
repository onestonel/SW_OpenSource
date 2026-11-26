"""OCR 초안을 영수증 '확인 중'으로 저장하기 (POST …/photo/ocr?save=true).

읽은 초안을 영수증 입력 규칙에 맞게 정리해(app/ocr_draft.py) 영수증의 가게 이름 · 총액 · 품목을 덮어쓴다.
stub 엔진이나 가짜 OCR 결과로 돌아서 OCR 설치가 필요 없다.
"""

from __future__ import annotations

import pytest

from app import storage
from app.api.v1 import ocr as ocr_api

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
STUB_ITEMS = [("삼겹살", 48000, "ITEM"), ("목살", 32000, "ITEM"), ("된장찌개", 3000, "ITEM"),
              ("맥주", 15000, "ITEM"), ("제휴할인", -5000, "DISCOUNT")]


@pytest.fixture(autouse=True)
def tmp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "storage_dir", lambda: tmp_path)
    return tmp_path


@pytest.fixture
def receipt(client, api) -> dict:
    """정산방(A · B)과 영수증(결제자 B)을 만들고 사진을 올린다."""
    room = api.post("/rooms", {"name": "제주 여행", "members": ["A", "B"]}).json()
    body = {"store_name": "1차 식당", "payer_member_id": room["members"][1]["id"], "total_amount": 10000,
            "items": [{"name": "김치찌개", "amount": 10000}]}
    r = api.post(f"/rooms/{room['room_token']}/receipts", body).json()
    url = f"/rooms/{room['room_token']}/receipts/{r['id']}"
    upload(client, url)
    return {"room": room, "url": url, "token": room["room_token"]}


def upload(client, url: str) -> None:
    assert client.post(f"/api/v1{url}/photo", files={"file": ("r.png", PNG, "image/png")}).status_code == 200


def read(client, url: str, **params):
    return client.post(f"/api/v1{url}/photo/ocr", params={"engine": "stub", **params})


def rows(receipt_json) -> list[tuple[str, int, str]]:
    return [(i["name"], i["amount"], i["kind"]) for i in receipt_json["items"]]


class FakeResult:
    """run_ocr 대신 돌려줄 결과. draft는 OCR API 답장의 draft 모양."""

    def __init__(self, draft: dict, warnings: list[str] | None = None):
        self.draft, self.warnings = draft, warnings or []

    def to_dict(self) -> dict:
        items_sum = sum(i["amount"] for i in self.draft["items"])
        total = self.draft["total_amount"]
        diff = None if total is None else total - items_sum
        return {"draft": self.draft, "check": {"items_sum": items_sum, "difference": diff, "is_matched": diff == 0},
                "warnings": list(self.warnings), "lines": [], "engine": "fake", "elapsed_ms": 0}


def fake_ocr(monkeypatch, draft: dict, warnings: list[str] | None = None) -> None:
    monkeypatch.setattr(ocr_api, "run_ocr", lambda data, engine: FakeResult(draft, warnings))


def test_save_overwrites_receipt_and_keeps_checking(client, api, receipt):
    res = read(client, receipt["url"], save="true")
    assert res.status_code == 200, res.text
    body = res.json()
    saved = body["receipt"]
    assert saved["status"] == "CHECKING"
    assert saved["store_name"] == "같이고기 경기대점" and saved["total_amount"] == 93000
    assert rows(saved) == STUB_ITEMS
    assert saved["payer"]["name"] == "B"  # 결제자는 OCR이 알 수 없어서 그대로
    assert saved["check"] == {"items_sum": 93000, "difference": 0, "is_matched": True}
    assert saved["photo_url"] == f"/api/v1{receipt['url']}/photo"
    assert api.get(receipt["url"]).json() == saved
    assert body["draft"]["store_name"] == "같이고기 경기대점"  # 초안 · 경고 · 줄은 저장하지 않을 때와 같다
    assert body["warnings"] == []


def test_without_save_receipt_is_unchanged(client, api, receipt):
    body = read(client, receipt["url"]).json()
    assert body["receipt"] is None
    r = api.get(receipt["url"]).json()
    assert r["store_name"] == "1차 식당" and rows(r) == [("김치찌개", 10000, "ITEM")]


def test_reading_again_replaces_items(client, api, receipt):
    """사진을 다시 올려 다시 읽어도 품목이 겹쳐 쌓이지 않는다."""
    first = read(client, receipt["url"], save="true").json()["receipt"]
    upload(client, receipt["url"])
    second = read(client, receipt["url"], save="true").json()["receipt"]
    assert rows(second) == STUB_ITEMS
    assert len(api.get(f"/rooms/{receipt['token']}/receipts").json()) == 1
    assert {i["id"] for i in first["items"]}.isdisjoint(i["id"] for i in second["items"])


def test_new_items_start_with_everyone_checked(client, api, receipt):
    read(client, receipt["url"], save="true")
    api.post(receipt["url"] + "/confirm", expect=200)
    table = api.get(f"/rooms/{receipt['token']}/checks").json()
    everyone = sorted(m["id"] for m in receipt["room"]["members"])
    assert [i["name"] for i in table["items"]] == ["삼겹살", "목살", "된장찌개", "맥주"]  # 할인 줄은 체크 표에 없다
    assert all(sorted(i["member_ids"]) == everyone for i in table["items"])


def test_confirmed_receipt_is_not_read_for_save(client, api, receipt, monkeypatch):
    api.post(receipt["url"] + "/confirm", expect=200)
    res = read(client, receipt["url"], save="true")
    assert res.status_code == 409 and res.json()["error"]["code"] == "RECEIPT_CONFIRMED"
    assert read(client, receipt["url"]).status_code == 200  # 저장하지 않고 읽기만 하는 것은 된다


def test_confirmed_while_reading_is_not_overwritten(client, api, receipt, monkeypatch):
    """OCR은 수십 초 걸린다. 그 사이에 다른 사람이 확정했으면 덮어쓰지 않는다."""
    stub = FakeResult({"store_name": "같이고기", "total_amount": 5000,
                       "items": [{"name": "고기", "amount": 5000, "kind": "ITEM"}]})

    def slow_ocr(data, engine):
        api.post(receipt["url"] + "/confirm", expect=200)
        return stub

    monkeypatch.setattr(ocr_api, "run_ocr", slow_ocr)
    res = read(client, receipt["url"], save="true")
    assert res.status_code == 409 and res.json()["error"]["code"] == "RECEIPT_CONFIRMED"
    r = api.get(receipt["url"]).json()
    assert r["status"] == "CONFIRMED" and rows(r) == [("김치찌개", 10000, "ITEM")]


def test_messy_draft_is_cleaned_before_saving(client, api, receipt, monkeypatch):
    """OCR 초안이 영수증 입력 규칙에 안 맞으면 정리해서 저장하고, 고친 이유를 warnings 뒤에 붙인다."""
    long_name = "모둠 " * 20
    fake_ocr(monkeypatch, {"store_name": None, "total_amount": None, "items": [
        {"name": long_name, "amount": 12000, "kind": "ITEM"},
        {"name": "25,000 1개", "amount": 0, "kind": "ITEM"},
        {"name": "제휴할인", "amount": -2000, "kind": "DISCOUNT"},
    ]}, warnings=["가게 이름을 찾지 못했습니다.", "합계 금액을 찾지 못했습니다."])
    body = read(client, receipt["url"], save="true").json()
    saved = body["receipt"]
    assert saved["store_name"] == "1차 식당"  # 못 읽은 가게 이름은 원래 이름 그대로
    assert saved["total_amount"] == 10000  # 합계를 못 읽어 품목 합으로
    assert rows(saved) == [(" ".join(long_name.split())[:50], 12000, "ITEM"), ("제휴할인", -2000, "DISCOUNT")]
    assert body["warnings"][:2] == ["가게 이름을 찾지 못했습니다.", "합계 금액을 찾지 못했습니다."]
    assert body["warnings"][2:] == [
        f"'{saved['items'][0]['name']}': 이름이 길어 앞 50자만 넣었습니다.",
        "'25,000 1개': 0원이라 뺐습니다.",
        "가게 이름을 읽지 못해 원래 이름('1차 식당')을 그대로 두었습니다.",
        "합계를 읽지 못해 품목 합(10,000원)으로 넣었습니다.",
    ]


def test_draft_without_items_keeps_receipt(client, api, receipt, monkeypatch):
    fake_ocr(monkeypatch, {"store_name": "같이고기", "total_amount": 30000, "items": []},
             warnings=["품목을 하나도 찾지 못했습니다."])
    body = read(client, receipt["url"], save="true").json()
    assert body["receipt"] is None
    assert body["warnings"] == ["품목을 하나도 찾지 못했습니다.",
                                "품목을 하나도 읽지 못해 영수증은 그대로 두었습니다. 직접 입력해 주세요."]
    r = api.get(receipt["url"]).json()
    assert r["store_name"] == "1차 식당" and rows(r) == [("김치찌개", 10000, "ITEM")]
