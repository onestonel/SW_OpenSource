"""분담 조건 — 체크 표 (API 명세서 4절) · 구성원 삭제 때 빈 체크 막기 (2절)."""

from __future__ import annotations

import pytest

from tests.conftest import error


@pytest.fixture
def room(api) -> dict:
    return api.post("/rooms", {"name": "제주 여행", "members": ["A", "B", "C", "D"]}).json()


def ids(room) -> list[int]:
    return [m["id"] for m in room["members"]]


def make_receipt(api, room, *, confirm=True, payer=0, store="1차 식당") -> dict:
    body = {
        "store_name": store,
        "payer_member_id": ids(room)[payer],
        "total_amount": 145000,
        "items": [
            {"name": "김치찌개", "amount": 10000},
            {"name": "술", "amount": 140000},
            {"name": "쿠폰", "amount": -5000, "kind": "DISCOUNT"},
        ],
    }
    receipt = api.post(f"/rooms/{room['room_token']}/receipts", body).json()
    if confirm:
        receipt = api.post(f"/rooms/{room['room_token']}/receipts/{receipt['id']}/confirm", expect=200).json()
    return receipt


def item_ids(receipt) -> list[int]:
    """할인 줄을 뺀 품목 줄 id."""
    return [i["id"] for i in receipt["items"] if i["kind"] == "ITEM"]


def checks_url(room) -> str:
    return f"/rooms/{room['room_token']}/checks"


def save(api, room, items, expect=200):
    return api.put(checks_url(room), {"items": items}, expect=expect)


# ------------------------------------------------------------------ 받기

def test_get_lists_only_items_of_confirmed_receipts(api, room):
    confirmed = make_receipt(api, room)
    make_receipt(api, room, confirm=False, store="2차 카페")  # 확인 중 → 안 나온다
    a, b, c, d = ids(room)

    got = api.get(checks_url(room)).json()
    assert got["members"] == [{"id": a, "name": "A"}, {"id": b, "name": "B"},
                              {"id": c, "name": "C"}, {"id": d, "name": "D"}]
    kimchi, sul = item_ids(confirmed)
    assert got["items"] == [  # 할인(쿠폰) 줄은 안 나온다
        {"item_id": kimchi, "receipt_id": confirmed["id"], "store_name": "1차 식당", "name": "김치찌개",
         "amount": 10000, "member_ids": [a, b, c, d]},
        {"item_id": sul, "receipt_id": confirmed["id"], "store_name": "1차 식당", "name": "술",
         "amount": 140000, "member_ids": [a, b, c, d]},
    ]


def test_get_empty_when_nothing_confirmed(api, room):
    make_receipt(api, room, confirm=False)
    assert api.get(checks_url(room)).json()["items"] == []


def test_wrong_room_token(api):
    api.get("/rooms/없는키/checks", expect=404)
    api.put("/rooms/없는키/checks", {"items": []}, expect=404)


# ------------------------------------------------------------------ 저장

def test_save_changes_only_sent_items(api, room):
    kimchi, sul = item_ids(make_receipt(api, room))
    a, b, c, d = ids(room)

    got = save(api, room, [{"item_id": sul, "member_ids": [c, a, b]}]).json()  # D는 술을 안 마심
    by_id = {i["item_id"]: i["member_ids"] for i in got["items"]}
    assert by_id == {kimchi: [a, b, c, d], sul: [a, b, c]}  # 구성원 순서로 돌려준다
    assert api.get(checks_url(room)).json() == got

    # 다시 켜기 · 끄기를 섞어도 된다
    got = save(api, room, [{"item_id": sul, "member_ids": [b, d]}]).json()
    assert {i["item_id"]: i["member_ids"] for i in got["items"]}[sul] == [b, d]


def test_save_marks_settlement_stale(api, room):
    _, sul = item_ids(make_receipt(api, room))
    token = room["room_token"]
    api.post(f"/rooms/{token}/settlements")
    assert api.get(f"/rooms/{token}").json()["latest_settlement"]["is_stale"] is False

    save(api, room, [{"item_id": sul, "member_ids": ids(room)[:3]}])
    assert api.get(f"/rooms/{token}").json()["latest_settlement"]["is_stale"] is True


def test_settlement_uses_saved_checks(api, room):
    """D를 술에서 빼면 D가 낼 돈이 줄어든다."""
    _, sul = item_ids(make_receipt(api, room))
    token = room["room_token"]
    before = api.post(f"/rooms/{token}/settlements").json()
    save(api, room, [{"item_id": sul, "member_ids": ids(room)[:3]}])
    after = api.post(f"/rooms/{token}/settlements").json()
    owed = lambda s: {m["name"]: m["owed"] for m in s["members"]}  # noqa: E731
    assert owed(after)["D"] < owed(before)["D"]


# ------------------------------------------------------------------ 저장 오류 경우

def test_empty_check(api, room):
    kimchi, sul = item_ids(make_receipt(api, room))
    res = save(api, room, [{"item_id": kimchi, "member_ids": ids(room)[:1]}, {"item_id": sul, "member_ids": []}],
               expect=422)
    assert error(res)["code"] == "CHECK_EMPTY"
    assert error(res)["details"] == {"item_ids": [sul]}
    # 하나라도 틀리면 아무것도 바뀌지 않는다
    assert all(len(i["member_ids"]) == 4 for i in api.get(checks_url(room)).json()["items"])


def test_unknown_item(api, room):
    make_receipt(api, room)
    res = save(api, room, [{"item_id": 99999, "member_ids": ids(room)}], expect=422)
    assert error(res)["code"] == "VALIDATION_ERROR"
    assert error(res)["details"]["fields"] == {"items.0.item_id": "이 정산방에 없는 품목입니다"}


def test_item_of_unconfirmed_receipt(api, room):
    kimchi, _ = item_ids(make_receipt(api, room, confirm=False))
    res = save(api, room, [{"item_id": kimchi, "member_ids": ids(room)[:1]}], expect=422)
    assert error(res)["code"] == "VALIDATION_ERROR"
    assert error(res)["details"]["fields"] == {"items.0.item_id": "확정하지 않은 영수증의 품목입니다"}


def test_discount_line_cannot_be_checked(api, room):
    receipt = make_receipt(api, room)
    coupon = next(i["id"] for i in receipt["items"] if i["kind"] == "DISCOUNT")
    res = save(api, room, [{"item_id": coupon, "member_ids": ids(room)}], expect=422)
    assert error(res)["code"] == "VALIDATION_ERROR"


def test_item_of_other_room(api, room):
    other = api.post("/rooms", {"name": "다른 방", "members": ["X", "Y"]}).json()
    theirs = item_ids(make_receipt(api, other))[0]
    res = save(api, room, [{"item_id": theirs, "member_ids": ids(room)}], expect=422)
    assert error(res)["code"] == "VALIDATION_ERROR"
    # 남의 방 체크는 그대로
    assert api.get(checks_url(other)).json()["items"][0]["member_ids"] == ids(other)


def test_member_not_in_room(api, room):
    kimchi, sul = item_ids(make_receipt(api, room))
    other = api.post("/rooms", {"name": "다른 방", "members": ["X", "Y"]}).json()
    res = save(api, room, [{"item_id": kimchi, "member_ids": ids(room)[:2]},
                           {"item_id": sul, "member_ids": [ids(room)[0], ids(other)[0]]}], expect=422)
    assert error(res)["code"] == "VALIDATION_ERROR"
    assert error(res)["details"]["fields"] == {"items.1.member_ids": "이 정산방 구성원이 아닌 id가 있습니다"}
    assert all(len(i["member_ids"]) == 4 for i in api.get(checks_url(room)).json()["items"])


def test_same_item_twice(api, room):
    kimchi, _ = item_ids(make_receipt(api, room))
    res = save(api, room, [{"item_id": kimchi, "member_ids": ids(room)[:1]},
                           {"item_id": kimchi, "member_ids": ids(room)[:2]}], expect=422)
    assert error(res)["code"] == "VALIDATION_ERROR"


def test_body_shape(api, room):
    res = api.put(checks_url(room), {"items": [{"item_id": 1}]}, expect=422)
    assert error(res)["details"]["fields"] == {"items.0.member_ids": "필수"}


# ------------------------------------------------------------------ 구성원 삭제 (2절)

def test_cannot_delete_member_who_is_only_check(api, room):
    receipt = make_receipt(api, room)
    _, sul = item_ids(receipt)
    a, b, c, d = ids(room)
    save(api, room, [{"item_id": sul, "member_ids": [c]}])  # 술은 C 혼자

    res = api.delete(f"/rooms/{room['room_token']}/members/{c}", expect=409)
    assert error(res)["code"] == "MEMBER_IN_USE"
    assert error(res)["details"] == {"item_ids": [sul]}
    assert "1차 식당 - 술" in error(res)["message"]

    # 다른 사람도 체크하면 지울 수 있고, C의 체크는 같이 지워진다
    save(api, room, [{"item_id": sul, "member_ids": [c, d]}])
    api.delete(f"/rooms/{room['room_token']}/members/{c}")
    by_id = {i["item_id"]: i["member_ids"] for i in api.get(checks_url(room)).json()["items"]}
    assert by_id[sul] == [d]


def test_only_check_in_unconfirmed_receipt_also_blocks(api, room):
    """확인 중인 영수증도 나중에 확정하면 계산에 들어가므로 막는다."""
    receipt = make_receipt(api, room)
    _, sul = item_ids(receipt)
    c = ids(room)[2]
    save(api, room, [{"item_id": sul, "member_ids": [c]}])
    api.post(f"/rooms/{room['room_token']}/receipts/{receipt['id']}/unconfirm", expect=200)

    res = api.delete(f"/rooms/{room['room_token']}/members/{c}", expect=409)
    assert error(res)["details"] == {"item_ids": [sul]}


def test_discount_lines_do_not_block_delete(api, room):
    """할인 줄은 원래 체크가 없다. 할인 줄이 있어도 구성원 삭제는 막히지 않는다."""
    make_receipt(api, room)
    api.delete(f"/rooms/{room['room_token']}/members/{ids(room)[3]}")
