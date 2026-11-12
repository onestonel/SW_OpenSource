"""영수증 API (API 명세서 3절, 사진 제외). 만들기 · 목록 · 보기 · 고치기 · 지우기 · 확정 · 확정 취소와 오류 경우."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db import get_db
from app.main import app
from app.models import ReceiptItemPayer
from tests.conftest import error


@pytest.fixture
def room(api) -> dict:
    return api.post("/rooms", {"name": "제주 여행", "members": ["A", "B", "C", "D"]}).json()


def ids(room) -> list[int]:
    return [m["id"] for m in room["members"]]


def body(room, **over) -> dict:
    return {
        "store_name": "1차 식당",
        "payer_member_id": ids(room)[0],
        "total_amount": 150000,
        "items": [
            {"name": "김치찌개", "amount": 10000, "kind": "ITEM"},
            {"name": "고기", "amount": 50000, "kind": "ITEM"},
            {"name": "술", "amount": 90000, "kind": "ITEM"},
        ],
        **over,
    }


def url(room, rid=None, tail="") -> str:
    base = f"/rooms/{room['room_token']}/receipts"
    return base if rid is None else f"{base}/{rid}{tail}"


def checks(client, receipt) -> dict[str, set[int]]:
    """줄 이름 → 체크된 구성원 id (DB에서 직접 읽는다. 체크 표 API는 4절 PR에서)."""
    db = next(app.dependency_overrides[get_db]())
    rows = db.execute(select(ReceiptItemPayer.receipt_item_id, ReceiptItemPayer.member_id)).all()
    by_id = {i["id"]: i["name"] for i in receipt["items"]}
    out: dict[str, set[int]] = {name: set() for name in by_id.values()}
    for item_id, member_id in rows:
        if item_id in by_id:
            out[by_id[item_id]].add(member_id)
    return out


# ------------------------------------------------------------------ 만들기 · 보기 · 목록

def test_create_matches_spec_example(api, client, room):
    r = api.post(url(room), body(room)).json()
    a = room["members"][0]
    assert r["store_name"] == "1차 식당" and r["status"] == "CHECKING"
    assert r["payer"] == {"id": a["id"], "name": "A"}
    assert [(i["name"], i["amount"], i["kind"]) for i in r["items"]] == [
        ("김치찌개", 10000, "ITEM"), ("고기", 50000, "ITEM"), ("술", 90000, "ITEM")]
    assert r["check"] == {"items_sum": 150000, "difference": 0, "is_matched": True}
    assert r["photo_url"] is None and r["created_at"].endswith("+09:00")
    # 품목은 모든 구성원 체크로 시작
    assert all(v == set(ids(room)) for v in checks(client, r).values())

    assert api.get(url(room, r["id"])).json() == r
    assert api.get(url(room)).json() == [r]


def test_discount_and_mismatch_are_allowed(api, client, room):
    items = body(room)["items"] + [{"name": "할인", "amount": -5000, "kind": "DISCOUNT"}]
    r = api.post(url(room), body(room, items=items, total_amount=150000)).json()
    assert r["check"] == {"items_sum": 145000, "difference": 5000, "is_matched": False}
    assert checks(client, r)["할인"] == set()  # 할인 줄은 체크하지 않는다


def test_kind_defaults_to_item_and_names_are_trimmed(api, room):
    r = api.post(url(room), body(room, store_name=" 카페 ", items=[{"name": " 커피 ", "amount": 4500}],
                                  total_amount=4500)).json()
    assert r["store_name"] == "카페" and r["items"][0] == {"id": r["items"][0]["id"], "name": "커피",
                                                          "amount": 4500, "kind": "ITEM"}


def test_list_is_in_created_order(api, room):
    first = api.post(url(room), body(room, store_name="1차")).json()["id"]
    second = api.post(url(room), body(room, store_name="2차")).json()["id"]
    assert [r["id"] for r in api.get(url(room)).json()] == [first, second]


# ------------------------------------------------------------------ 서버 검사 5개 → 422

@pytest.mark.parametrize(("over", "fields"), [
    # 1. 결제자가 이 정산방 구성원인가
    ({"payer_member_id": 9999}, {"payer_member_id": "이 정산방 구성원이 아닙니다"}),
    # 2. ITEM 줄이 1개 이상인가
    ({"items": []}, {"items": "품목(ITEM) 줄이 1개 이상 있어야 합니다"}),
    ({"items": [{"name": "할인", "amount": -1000, "kind": "DISCOUNT"}]},
     {"items": "품목(ITEM) 줄이 1개 이상 있어야 합니다"}),
    # 3. ITEM 금액 > 0, DISCOUNT 금액 < 0
    ({"items": [{"name": "x", "amount": 0, "kind": "ITEM"}]}, {"items.0.amount": "품목 금액은 0보다 커야 합니다"}),
    ({"items": [{"name": "x", "amount": 100}, {"name": "할인", "amount": 100, "kind": "DISCOUNT"}]},
     {"items.1.amount": "할인 금액은 0보다 작아야 합니다 (예: -5000)"}),
    # 4. 모든 줄에 이름이 있는가
    ({"items": [{"name": " ", "amount": 100}]}, {"items.0.name": "빈 값은 안 됩니다"}),
    ({"store_name": ""}, {"store_name": "빈 값은 안 됩니다"}),
    # 5. 총액이 있고 0보다 큰가
    ({"total_amount": 0}, {"total_amount": "0보다 커야 합니다"}),
    ({"total_amount": None}, {"total_amount": "정수여야 합니다"}),
    # 그 밖의 모양 검사
    ({"items": [{"name": "x", "amount": 100, "kind": "TAX"}]},
     {"items.0.kind": "'ITEM' 또는 'DISCOUNT' 중 하나여야 합니다"}),
    ({"items": [{"name": "x", "amount": 100, "id": 1}]}, {"items.0.id": "새 영수증에는 줄 id를 보낼 수 없습니다"}),
])
def test_create_validation(api, room, over, fields):
    res = api.post(url(room), body(room, **over), expect=422)
    assert error(res)["code"] == "VALIDATION_ERROR"
    assert error(res)["details"]["fields"] == fields


def test_missing_total_and_payer(api, room):
    b = body(room)
    del b["total_amount"], b["payer_member_id"]
    res = api.post(url(room), b, expect=422)
    assert error(res)["details"]["fields"] == {"payer_member_id": "필수", "total_amount": "필수"}


def test_payer_from_other_room_is_rejected(api, room):
    other = api.post("/rooms", {"name": "x", "members": ["X", "Y"]}).json()
    res = api.post(url(room), body(room, payer_member_id=ids(other)[0]), expect=422)
    assert error(res) == {"code": "VALIDATION_ERROR", "message": "결제자를 골라주세요.",
                          "details": {"fields": {"payer_member_id": "이 정산방 구성원이 아닙니다"}}}


# ------------------------------------------------------------------ 없는 것 → 404

def test_not_found(api, room):
    res = api.get(url(room, 9999), expect=404)
    assert error(res) == {"code": "NOT_FOUND", "message": "영수증을 찾을 수 없습니다."}
    api.get("/rooms/wrong-token/receipts", expect=404)

    other = api.post("/rooms", {"name": "x", "members": ["X", "Y"]}).json()
    rid = api.post(url(other), body(other)).json()["id"]
    api.get(url(room, rid), expect=404)  # 다른 정산방의 영수증
    api.put(url(room, rid), body(room), expect=404)
    api.delete(url(room, rid), expect=404)
    api.post(url(room, rid, "/confirm"), expect=404)


# ------------------------------------------------------------------ 고치기

def test_update_keeps_checks_of_kept_lines(api, client, room):
    a, b, c, d = ids(room)
    r = api.post(url(room), body(room)).json()
    kimchi, meat, _drink = r["items"]

    # 체크 표 PR 전이라 DB에서 직접 '술'에서 D를 뺀 것처럼 만든다
    db = next(app.dependency_overrides[get_db]())
    db.query(ReceiptItemPayer).filter_by(receipt_item_id=kimchi["id"], member_id=d).delete()
    db.commit()

    new = api.put(url(room, r["id"]), body(room, store_name="1차 고깃집", payer_member_id=b, total_amount=70000, items=[
        {"id": kimchi["id"], "name": "김치찌개 2인", "amount": 12000, "kind": "ITEM"},  # 고침
        {"name": "냉면", "amount": 8000},  # 새 줄
        {"id": meat["id"], "name": "고기", "amount": 50000, "kind": "ITEM"},  # 그대로 (순서만 바뀜)
        # 술은 보내지 않음 → 지움
    ])).json()

    assert new["id"] == r["id"] and new["store_name"] == "1차 고깃집" and new["payer"]["name"] == "B"
    assert [(i["name"], i["amount"]) for i in new["items"]] == [("김치찌개 2인", 12000), ("냉면", 8000), ("고기", 50000)]
    assert new["items"][0]["id"] == kimchi["id"] and new["items"][2]["id"] == meat["id"]
    assert new["check"] == {"items_sum": 70000, "difference": 0, "is_matched": True}
    got = checks(client, new)
    assert got["김치찌개 2인"] == {a, b, c}  # 체크 그대로 유지
    assert got["냉면"] == {a, b, c, d}  # 새 줄은 모두 체크
    assert db.query(ReceiptItemPayer).filter_by(receipt_item_id=_drink["id"]).count() == 0  # 지운 줄의 체크도 지움
    db.close()


def test_update_kind_change_resets_checks(api, client, room):
    r = api.post(url(room), body(room, items=[{"name": "커피", "amount": 5000},
                                              {"name": "쿠폰", "amount": -1000, "kind": "DISCOUNT"}])).json()
    coffee, coupon = r["items"]
    new = api.put(url(room, r["id"]), body(room, items=[
        {"id": coffee["id"], "name": "커피", "amount": 5000, "kind": "ITEM"},
        {"id": coupon["id"], "name": "케이크", "amount": 3000, "kind": "ITEM"},  # 할인 → 품목
    ])).json()
    assert checks(client, new)["케이크"] == set(ids(room))


@pytest.mark.parametrize("which", ["other_receipt", "other_room", "missing"])
def test_update_rejects_foreign_line_id(api, room, which):
    r = api.post(url(room), body(room)).json()
    if which == "other_receipt":
        line_id = api.post(url(room), body(room)).json()["items"][0]["id"]
    elif which == "other_room":
        other = api.post("/rooms", {"name": "x", "members": ["X", "Y"]}).json()
        line_id = api.post(url(other), body(other)).json()["items"][0]["id"]
    else:
        line_id = 9999
    res = api.put(url(room, r["id"]), body(room, items=[{"id": line_id, "name": "x", "amount": 100}]), expect=422)
    assert error(res)["details"]["fields"] == {"items.0.id": "이 영수증에 없는 줄입니다"}
    assert api.get(url(room, r["id"])).json() == r  # 아무것도 바뀌지 않음


def test_update_rejects_duplicate_line_id(api, room):
    r = api.post(url(room), body(room)).json()
    line = r["items"][0]
    res = api.put(url(room, r["id"]), body(room, items=[line, line]), expect=422)
    assert error(res)["details"]["fields"] == {"items": "같은 줄 id가 두 번 들어 있습니다"}


# ------------------------------------------------------------------ 확정 · 확정 취소 · 상태별로 막기

def test_confirm_flow(api, room):
    r = api.post(url(room), body(room, total_amount=160000)).json()  # 품목 합 ≠ 총액이어도 확정된다
    rid = r["id"]
    confirmed = api.post(url(room, rid, "/confirm"), expect=200).json()
    assert confirmed["status"] == "CONFIRMED" and confirmed["check"]["is_matched"] is False
    assert api.post(url(room, rid, "/confirm"), expect=200).json()["status"] == "CONFIRMED"  # 다시 눌러도 그대로

    res = api.put(url(room, rid), body(room), expect=409)
    assert error(res) == {"code": "RECEIPT_CONFIRMED",
                          "message": "확정된 영수증은 고치거나 지울 수 없습니다. 먼저 '확정 취소'를 눌러 주세요."}
    assert error(api.delete(url(room, rid), expect=409))["code"] == "RECEIPT_CONFIRMED"

    back = api.post(url(room, rid, "/unconfirm"), expect=200).json()
    assert back["status"] == "CHECKING"
    res = api.post(url(room, rid, "/unconfirm"), expect=409)
    assert error(res) == {"code": "RECEIPT_NOT_CONFIRMED", "message": "확정된 영수증만 확정 취소할 수 있습니다."}

    api.put(url(room, rid), body(room))  # 취소한 뒤에는 고칠 수 있다
    api.delete(url(room, rid))
    api.get(url(room, rid), expect=404)
    assert api.get(url(room)).json() == []


# ------------------------------------------------------------------ 구성원 삭제 (2절)

def test_payer_cannot_be_deleted(api, room):
    a, b, c, d = ids(room)
    rid = api.post(url(room), body(room, payer_member_id=b, store_name="카페")).json()["id"]
    res = api.delete(f"/rooms/{room['room_token']}/members/{b}", expect=409)
    assert error(res) == {"code": "MEMBER_IN_USE",
                          "message": "영수증 결제자로 들어가 있어 지울 수 없습니다. 먼저 결제자를 바꿔 주세요. (영수증: 카페)",
                          "details": {"receipt_ids": [rid]}}

    api.put(url(room, rid), body(room, payer_member_id=a))  # 결제자를 바꾸면 지울 수 있다
    api.delete(f"/rooms/{room['room_token']}/members/{b}")


def test_deleting_member_removes_their_checks(api, client, room):
    a, b, c, d = ids(room)
    r = api.post(url(room), body(room)).json()
    api.delete(f"/rooms/{room['room_token']}/members/{d}")
    assert all(v == {a, b, c} for v in checks(client, r).values())


def test_docs_lists_receipt_api(client):
    paths = client.get("/openapi.json").json()["paths"]
    base = "/api/v1/rooms/{room_token}/receipts"
    assert {base, base + "/{receipt_id}", base + "/{receipt_id}/confirm", base + "/{receipt_id}/unconfirm"} <= set(paths)
