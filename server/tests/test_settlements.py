"""정산 결과 API (API 명세서 5절). 다시 계산 → 새 버전 · 최신 결과 보기 · '최신 아님' · 송금 목록 복사 글."""

from __future__ import annotations

import pytest

from app.db import get_db
from app.main import app
from app.models import ReceiptItemPayer
from tests.conftest import error


@pytest.fixture
def db():
    session = next(app.dependency_overrides[get_db]())
    yield session
    session.close()


def make_room(api, members="ABCD", **over) -> tuple[str, dict[str, int]]:
    room = api.post("/rooms", {"name": "제주 여행", "members": list(members), **over}).json()
    return room["room_token"], {m["name"]: m["id"] for m in room["members"]}


def add_receipt(api, token, payer_id, store, total, items, confirm=True) -> dict:
    lines = [{"name": n, "amount": a, "kind": "DISCOUNT" if a < 0 else "ITEM"} for n, a in items]
    r = api.post(f"/rooms/{token}/receipts",
                 {"store_name": store, "payer_member_id": payer_id, "total_amount": total, "items": lines}).json()
    if confirm:
        api.post(f"/rooms/{token}/receipts/{r['id']}/confirm", expect=200)
    return r


def set_checks(db, item_id, member_ids) -> None:
    """체크 표 API(4절)가 들어오기 전이라 DB에서 직접 체크를 바꾼다."""
    db.query(ReceiptItemPayer).filter_by(receipt_item_id=item_id).delete()
    db.add_all(ReceiptItemPayer(receipt_item_id=item_id, member_id=m) for m in member_ids)
    db.commit()


def recalc(api, token, expect=201):
    return api.post(f"/rooms/{token}/settlements", expect=expect)


def latest(api, token, expect=200):
    return api.get(f"/rooms/{token}/settlements/latest", expect=expect)


def transfers(s) -> list[tuple[str, str, int]]:
    return [(t["from"]["name"], t["to"]["name"], t["amount"]) for t in s["transfers"]]


def example1(api, db, rounding="WON_1"):
    """명세서 5절 예시: A가 항공권 400,000 + 식당 150,000을 내고 D는 술 제외."""
    token, m = make_room(api, rounding=rounding)
    add_receipt(api, token, m["A"], "항공권", 400_000, [("항공권", 400_000)])
    r = add_receipt(api, token, m["A"], "1차 식당", 150_000, [("김치찌개", 10_000), ("고기", 50_000), ("술", 90_000)],
                    confirm=False)
    set_checks(db, r["items"][2]["id"], [m["A"], m["B"], m["C"]])
    api.post(f"/rooms/{token}/receipts/{r['id']}/confirm", expect=200)
    return token, m


def example2(api, db, rounding="WON_1"):
    """노션 예시 2: 1차 식당 60,000원은 A (김치찌개 A·B, 고기 A·B·C). 2차 술집 100,000원은 B (술 4명)."""
    token, m = make_room(api, rounding=rounding)
    r = add_receipt(api, token, m["A"], "1차 식당", 60_000, [("김치찌개", 10_000), ("고기", 50_000)], confirm=False)
    set_checks(db, r["items"][0]["id"], [m["A"], m["B"]])
    set_checks(db, r["items"][1]["id"], [m["A"], m["B"], m["C"]])
    api.post(f"/rooms/{token}/receipts/{r['id']}/confirm", expect=200)
    add_receipt(api, token, m["B"], "2차 술집", 100_000, [("술", 100_000)])
    return token, m


# ------------------------------------------------------------------ 계산 결과 (명세서 예시)

def test_example1_matches_spec(api, db):
    token, m = example1(api, db)
    s = recalc(api, token).json()
    assert s["created_at"].endswith("+09:00")
    assert {k: v for k, v in s.items() if k != "created_at"} == {
        "version": 1,
        "rounding": "WON_1",
        "is_stale": False,
        "members": [
            {"member_id": m["A"], "name": "A", "paid": 550000, "owed": 145000, "net": 405000},
            {"member_id": m["B"], "name": "B", "paid": 0, "owed": 145000, "net": -145000},
            {"member_id": m["C"], "name": "C", "paid": 0, "owed": 145000, "net": -145000},
            {"member_id": m["D"], "name": "D", "paid": 0, "owed": 115000, "net": -115000},
        ],
        "transfers": [
            {"from": {"id": m["B"], "name": "B"}, "to": {"id": m["A"], "name": "A"}, "amount": 145000},
            {"from": {"id": m["C"], "name": "C"}, "to": {"id": m["A"], "name": "A"}, "amount": 145000},
            {"from": {"id": m["D"], "name": "D"}, "to": {"id": m["A"], "name": "A"}, "amount": 115000},
        ],
        "excluded_receipts": [],
        "copy_text": "[같이정산 · 제주 여행 · 버전 1]\nB → A 145,000원\nC → A 145,000원\nD → A 115,000원",
    }
    assert latest(api, token).json() == s


def test_example2_one_won_merges_pairs(api, db):
    """A↔B는 B→A 21,667원과 A→B 25,000원을 합쳐 A→B 3,333원 한 건. 남는 1원은 구성원 순서대로."""
    token, _ = example2(api, db)
    s = recalc(api, token).json()
    assert transfers(s) == [("A", "B", 3_333), ("C", "A", 16_666), ("C", "B", 25_000), ("D", "B", 25_000)]
    assert [(x["name"], x["paid"], x["owed"], x["net"]) for x in s["members"]] == [
        ("A", 60_000, 46_667, 13_333), ("B", 100_000, 46_667, 53_333),
        ("C", 0, 41_666, -41_666), ("D", 0, 25_000, -25_000)]


def test_example2_ten_won_round_up(api, db):
    """10원 단위: 결제자가 아닌 사람 몫을 영수증마다 한 번 올리고, 더 걷힌 돈만큼 결제자가 덜 낸다."""
    token, _ = example2(api, db, rounding="WON_10")
    s = recalc(api, token).json()
    assert s["rounding"] == "WON_10"
    assert transfers(s) == [("A", "B", 3_330), ("C", "A", 16_670), ("C", "B", 25_000), ("D", "B", 25_000)]
    assert s["copy_text"].splitlines()[1:] == ["A → B 3,330원", "C → A 16,670원", "C → B 25,000원", "D → B 25,000원"]


def test_discount_and_difference_split_among_participants(api, db):
    """할인 · 차액은 그 영수증 참여자(품목에 한 번이라도 체크된 사람)끼리. D는 참여자가 아니다."""
    token, m = make_room(api)
    r = add_receipt(api, token, m["A"], "피자", 18_000, [("피자", 15_000), ("콜라", 5_000), ("할인", -3_000)],
                    confirm=False)  # 품목 합 17,000 → 차액 1,000
    set_checks(db, r["items"][0]["id"], [m["A"], m["B"]])
    set_checks(db, r["items"][1]["id"], [m["C"]])
    api.post(f"/rooms/{token}/receipts/{r['id']}/confirm", expect=200)
    s = recalc(api, token).json()
    # A: 7,500 − 1,000 + 334 = 6,834 / B: 7,500 − 1,000 + 333 = 6,833 / C: 5,000 − 1,000 + 333 = 4,333
    assert [(x["name"], x["owed"]) for x in s["members"]] == [("A", 6_834), ("B", 6_833), ("C", 4_333), ("D", 0)]
    assert transfers(s) == [("B", "A", 6_833), ("C", "A", 4_333)]


def test_copy_text_when_no_transfers(api, db):
    token, m = make_room(api, "AB")
    r = add_receipt(api, token, m["A"], "편의점", 3_000, [("물", 3_000)], confirm=False)
    set_checks(db, r["items"][0]["id"], [m["A"]])  # A가 혼자 먹고 혼자 냄
    api.post(f"/rooms/{token}/receipts/{r['id']}/confirm", expect=200)
    s = recalc(api, token).json()
    assert s["transfers"] == []
    assert s["copy_text"] == "[같이정산 · 제주 여행 · 버전 1]\n주고받을 돈이 없습니다."


# ------------------------------------------------------------------ 확정된 영수증만 · 오류

def test_only_confirmed_receipts_count(api, db):
    token, m = example1(api, db)
    cafe = add_receipt(api, token, m["B"], "카페", 20_000, [("커피", 20_000)], confirm=False)
    s = recalc(api, token).json()
    assert s["excluded_receipts"] == [{"id": cafe["id"], "store_name": "카페"}]
    assert transfers(s) == [("B", "A", 145_000), ("C", "A", 145_000), ("D", "A", 115_000)]


def test_no_confirmed_receipts(api):
    token, m = make_room(api)
    res = recalc(api, token, expect=422)
    assert error(res) == {"code": "NO_CONFIRMED_RECEIPTS", "message": "확정된 영수증이 없습니다. 영수증을 먼저 확정해 주세요."}
    add_receipt(api, token, m["A"], "카페", 20_000, [("커피", 20_000)], confirm=False)
    assert error(recalc(api, token, expect=422))["code"] == "NO_CONFIRMED_RECEIPTS"
    latest(api, token, expect=404)  # 실패한 계산은 버전을 만들지 않는다


def test_item_without_checks(api, db):
    token, m = make_room(api)
    r = add_receipt(api, token, m["A"], "식당", 10_000, [("밥", 10_000)])
    set_checks(db, r["items"][0]["id"], [])
    res = recalc(api, token, expect=422)
    assert error(res)["code"] == "CHECK_EMPTY" and error(res)["message"] == "'밥' 품목에 체크된 사람이 없습니다."


def test_not_found(api):
    token, _ = make_room(api)
    res = latest(api, token, expect=404)
    assert error(res) == {"code": "NOT_FOUND", "message": "아직 계산한 정산 결과가 없습니다. '다시 계산'을 눌러 주세요."}
    api.post("/rooms/wrong/settlements", expect=404)
    api.get("/rooms/wrong/settlements/latest", expect=404)


# ------------------------------------------------------------------ 버전 · 최신 아님

def test_versions_go_up_and_latest_is_newest(api, db):
    token, m = example1(api, db)
    assert api.get(f"/rooms/{token}").json()["latest_settlement"] is None
    first = recalc(api, token).json()
    second = recalc(api, token).json()
    assert (first["version"], second["version"]) == (1, 2)
    assert second["copy_text"].startswith("[같이정산 · 제주 여행 · 버전 2]")
    assert latest(api, token).json() == second
    assert api.get(f"/rooms/{token}").json()["latest_settlement"] == {"version": 2, "is_stale": False}

    other, om = make_room(api)  # 정산방마다 버전은 따로 센다
    add_receipt(api, other, om["A"], "x", 1_000, [("x", 1_000)])
    assert recalc(api, other).json()["version"] == 1


def stale(api, token) -> bool:
    assert latest(api, token).json()["is_stale"] == api.get(f"/rooms/{token}").json()["latest_settlement"]["is_stale"]
    return latest(api, token).json()["is_stale"]


@pytest.mark.parametrize("event", ["confirm", "unconfirm", "add_member", "delete_member", "rounding"])
def test_changes_after_calculation_make_it_stale(api, db, event):
    token, m = example1(api, db)
    draft = add_receipt(api, token, m["B"], "카페", 20_000, [("커피", 20_000)], confirm=False)
    confirmed = api.get(f"/rooms/{token}/receipts").json()[0]
    recalc(api, token)
    assert stale(api, token) is False

    if event == "confirm":
        api.post(f"/rooms/{token}/receipts/{draft['id']}/confirm", expect=200)
    elif event == "unconfirm":
        api.post(f"/rooms/{token}/receipts/{confirmed['id']}/unconfirm", expect=200)
    elif event == "add_member":
        api.post(f"/rooms/{token}/members", {"name": "E"})
    elif event == "delete_member":
        e = api.post(f"/rooms/{token}/members", {"name": "E"}).json()["id"]
        recalc(api, token)
        api.delete(f"/rooms/{token}/members/{e}")
    elif event == "rounding":
        api.patch(f"/rooms/{token}", {"rounding": "WON_10"})
    assert stale(api, token) is True

    again = recalc(api, token).json()  # 다시 계산하면 새 버전은 최신
    assert again["is_stale"] is False and stale(api, token) is False


def test_changes_outside_calculation_keep_it_fresh(api, db):
    """확인 중인 영수증 만들기 · 고치기 · 지우기, 같은 원 단위 다시 저장, 이름 바꾸기는 계산 결과를 바꾸지 않는다."""
    token, m = example1(api, db)
    recalc(api, token)
    draft = add_receipt(api, token, m["B"], "카페", 20_000, [("커피", 20_000)], confirm=False)
    api.put(f"/rooms/{token}/receipts/{draft['id']}",
            {"store_name": "카페 2", "payer_member_id": m["C"], "total_amount": 9_000,
             "items": [{"name": "차", "amount": 9_000}]})
    api.delete(f"/rooms/{token}/receipts/{draft['id']}")
    api.patch(f"/rooms/{token}", {"rounding": "WON_1", "name": "제주 2박 3일"})
    assert stale(api, token) is False


def test_old_result_keeps_names_after_member_change(api, db):
    """저장한 결과는 그때의 모습 그대로다. 나중에 구성원이 바뀌어도 그 버전의 송금 목록은 바뀌지 않는다."""
    token, m = make_room(api, "ABC")
    add_receipt(api, token, m["A"], "식당", 3_000, [("밥", 3_000)])
    before = recalc(api, token).json()
    api.post(f"/rooms/{token}/members", {"name": "D"})
    after = latest(api, token).json()
    assert after == {**before, "is_stale": True}


def test_docs_lists_settlement_api(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert {"/api/v1/rooms/{room_token}/settlements", "/api/v1/rooms/{room_token}/settlements/latest"} <= set(paths)
