"""가게 이름 · 결제자만으로 '확인 중' 영수증 만들기 (#47, API 초안 #45).

- 만들기 · 고치기: 총액 · 품목을 비워도 된다. 같은 정산방에 같은 가게 이름이면 409 STORE_NAME_DUPLICATE
- 확정: 총액이 없거나 품목(ITEM)이 없으면 409 RECEIPT_INCOMPLETE
- 새 흐름: 만들기 → 사진 올리기 → 사진 읽기(save=true) → 고치기 → 확정
"""

from __future__ import annotations

import pytest

from app import storage
from app.db import get_db
from app.main import app
from app.models import Receipt
from tests.conftest import error

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
FULL = {"total_amount": 30000, "items": [{"name": "김치찌개", "amount": 10000}, {"name": "고기", "amount": 20000}]}


@pytest.fixture
def room(api) -> dict:
    return api.post("/rooms", {"name": "제주 여행", "members": ["A", "B", "C"]}).json()


def url(room, rid=None, tail="") -> str:
    base = f"/rooms/{room['room_token']}/receipts"
    return base if rid is None else f"{base}/{rid}{tail}"


def draft(room, store="1차 식당", **more) -> dict:
    """가장 짧은 영수증 만들기: 가게 이름 + 결제자(A)."""
    return {"store_name": store, "payer_member_id": room["members"][0]["id"], **more}


def make(api, room, store="1차 식당", **more) -> dict:
    return api.post(url(room), draft(room, store, **more)).json()


# ------------------------------------------------------------------ 만들기: 가게 이름 + 결제자만

def test_create_with_store_and_payer_only(api, room):
    r = make(api, room)
    assert r["status"] == "CHECKING" and r["store_name"] == "1차 식당"
    assert r["payer"]["name"] == "A"
    assert r["total_amount"] is None and r["items"] == []
    assert r["check"] == {"items_sum": 0, "difference": None, "is_matched": False}
    assert api.get(url(room, r["id"])).json() == r
    assert api.get(url(room)).json() == [r]


def test_null_total_and_empty_items_can_be_sent(api, room):
    r = make(api, room, total_amount=None, items=[])
    assert r["total_amount"] is None and r["items"] == []


@pytest.mark.parametrize(("more", "check"), [
    ({"total_amount": 30000}, {"items_sum": 0, "difference": 30000, "is_matched": False}),
    ({"items": [{"name": "고기", "amount": 20000}]}, {"items_sum": 20000, "difference": None, "is_matched": False}),
    ({"total_amount": 1000, "items": [{"name": "쿠폰", "amount": -1000, "kind": "DISCOUNT"}]},
     {"items_sum": -1000, "difference": 2000, "is_matched": False}),
])
def test_partial_receipt_is_allowed_while_checking(api, room, more, check):
    assert make(api, room, **more)["check"] == check


# ------------------------------------------------------------------ 같은 가게 이름 → 409

def test_same_store_name_in_room_is_409(api, room):
    first = make(api, room, "카페")
    res = api.post(url(room), draft(room, " 카페 "), expect=409)  # 앞뒤 공백을 뗀 이름으로 비교
    assert error(res) == {
        "code": "STORE_NAME_DUPLICATE",
        "message": "이 정산방에 '카페' 영수증이 이미 있습니다. '카페 2'처럼 다른 이름을 적어 주세요.",
        "details": {"fields": {"store_name": "같은 이름의 영수증이 이미 있습니다"}},
    }
    make(api, room, "카페 2")  # 다른 이름은 된다
    api.delete(url(room, first["id"]))
    make(api, room, "카페")  # 지운 뒤에는 다시 쓸 수 있다


def test_same_store_name_in_other_room_is_fine(api, room):
    other = api.post("/rooms", {"name": "부산", "members": ["X", "Y"]}).json()
    make(api, room, "카페")
    make(api, other, "카페")


def test_update_checks_name_only_when_it_changes(api, room):
    cafe = make(api, room, "카페")
    bar = make(api, room, "술집")
    res = api.put(url(room, bar["id"]), draft(room, "카페"), expect=409)
    assert error(res)["code"] == "STORE_NAME_DUPLICATE"
    assert api.put(url(room, bar["id"]), draft(room, "술집", **FULL)).json()["total_amount"] == 30000  # 이름 그대로
    assert api.put(url(room, bar["id"]), draft(room, "2차 술집")).json()["store_name"] == "2차 술집"
    assert api.put(url(room, cafe["id"]), draft(room, " 카페 ")).json()["store_name"] == "카페"  # 자기 이름 그대로


def test_old_duplicates_can_still_be_edited(api, room):
    """이 규칙 전에 같은 이름으로 만든 영수증도 이름을 그대로 두면 고칠 수 있다."""
    first = make(api, room, "카페")
    second = make(api, room, "임시")
    db = next(app.dependency_overrides[get_db]())
    db.get(Receipt, second["id"]).store_name = "카페"
    db.commit()
    assert api.put(url(room, second["id"]), draft(room, "카페", **FULL)).json()["total_amount"] == 30000
    assert api.put(url(room, first["id"]), draft(room, "카페", total_amount=5000)).json()["total_amount"] == 5000


# ------------------------------------------------------------------ 확정: 총액 · 품목이 없으면 409

@pytest.mark.parametrize(("more", "message", "fields"), [
    ({}, "총액과 품목을 입력해야 확정할 수 있습니다.",
     {"total_amount": "총액을 입력해 주세요", "items": "품목을 1개 이상 넣어 주세요"}),
    ({"total_amount": 30000}, "품목을 1개 이상 넣어야 확정할 수 있습니다.", {"items": "품목을 1개 이상 넣어 주세요"}),
    ({"total_amount": 1000, "items": [{"name": "쿠폰", "amount": -1000, "kind": "DISCOUNT"}]},
     "품목을 1개 이상 넣어야 확정할 수 있습니다.", {"items": "품목을 1개 이상 넣어 주세요"}),
    ({"items": [{"name": "고기", "amount": 20000}]}, "총액을 입력해야 확정할 수 있습니다.",
     {"total_amount": "총액을 입력해 주세요"}),
])
def test_confirm_incomplete_is_409(api, room, more, message, fields):
    r = make(api, room, **more)
    res = api.post(url(room, r["id"], "/confirm"), expect=409)
    assert error(res) == {"code": "RECEIPT_INCOMPLETE", "message": message, "details": {"fields": fields}}
    assert api.get(url(room, r["id"])).json()["status"] == "CHECKING"


def test_fill_then_confirm_and_settle(api, room):
    r = make(api, room)
    api.put(url(room, r["id"]), draft(room, **FULL))
    assert api.post(url(room, r["id"], "/confirm"), expect=200).json()["status"] == "CONFIRMED"
    empty = make(api, room, "2차")  # 총액이 빈 '확인 중' 영수증이 같이 있어도 체크 표 · 정산은 그대로 돈다
    table = api.get(f"/rooms/{room['room_token']}/checks").json()
    assert [i["name"] for i in table["items"]] == ["김치찌개", "고기"]
    s = api.post(f"/rooms/{room['room_token']}/settlements").json()
    assert s["excluded_receipts"] == [{"id": empty["id"], "store_name": "2차"}]


def test_emptied_after_unconfirm_cannot_be_confirmed_again(api, room):
    r = make(api, room, **FULL)
    api.post(url(room, r["id"], "/confirm"), expect=200)
    api.post(url(room, r["id"], "/unconfirm"), expect=200)
    api.put(url(room, r["id"]), draft(room))  # 확인 중에는 총액 · 품목을 다시 비울 수 있다
    assert error(api.post(url(room, r["id"], "/confirm"), expect=409))["code"] == "RECEIPT_INCOMPLETE"


# ------------------------------------------------------------------ 새 흐름: 만들기 → 사진 → 사진 읽기 → 확정

def test_new_flow_with_photo(api, client, room, tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "storage_dir", lambda: tmp_path)
    r = make(api, room)
    base = "/api/v1" + url(room, r["id"])
    assert client.post(base + "/photo", files={"file": ("r.png", PNG, "image/png")}).status_code == 200
    res = client.post(base + "/photo/ocr", params={"engine": "stub", "save": "true"})
    assert res.status_code == 200, res.text
    filled = res.json()["receipt"]
    assert filled["status"] == "CHECKING" and filled["total_amount"] == 93000 and len(filled["items"]) == 5
    assert api.post(url(room, r["id"], "/confirm"), expect=200).json()["status"] == "CONFIRMED"
