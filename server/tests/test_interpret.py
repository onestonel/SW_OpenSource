"""문장으로 체크 표 바꾸기 — 변경안 받기 (POST /checks/interpret).

해석기(모델)는 바꿔 끼워서, 모델 없이 서버 검사와 체크 표 변환만 확인한다.
"""

from __future__ import annotations

import json

import pytest

from app import nl
from tests.conftest import error


@pytest.fixture
def room(api) -> dict:
    return api.post("/rooms", {"name": "회식", "members": ["민수", "지영", "현우", "수아"]}).json()


def ids(room) -> list[int]:
    return [m["id"] for m in room["members"]]


@pytest.fixture
def receipt(api, room) -> dict:
    body = {
        "store_name": "1차 고깃집",
        "payer_member_id": ids(room)[0],
        "total_amount": 115000,
        "items": [
            {"name": "삼겹살", "amount": 80000},
            {"name": "소주", "amount": 40000},
            {"name": "쿠폰", "amount": -5000, "kind": "DISCOUNT"},
        ],
    }
    r = api.post(f"/rooms/{room['room_token']}/receipts", body).json()
    return api.post(f"/rooms/{room['room_token']}/receipts/{r['id']}/confirm", expect=200).json()


def item_id(receipt, name) -> int:
    return next(i["id"] for i in receipt["items"] if i["name"] == name)


def ask(api, room, text, expect=200):
    return api.post(f"/rooms/{room['room_token']}/checks/interpret", {"text": text}, expect=expect)


def model_says(monkeypatch, answer):
    """해석기가 이 답을 내도록 바꿔 끼운다 (dict면 JSON으로)."""
    raw = answer if isinstance(answer, str) else json.dumps(answer, ensure_ascii=False)
    monkeypatch.setattr(nl, "call_model", lambda room, text: raw)


def parsed(*proposals):
    return {"status": "PARSED", "proposals": list(proposals), "clarification": None}


# ------------------------------------------------------------------ 체크 표 변경안


def test_exclude_removes_member_and_does_not_save(api, room, receipt, monkeypatch):
    a, b, c, d = ids(room)
    soju = item_id(receipt, "소주")
    model_says(monkeypatch, parsed({"receipt_item_id": soju, "type": "EXCLUDE", "params": {"member_ids": [d]},
                                    "evidence": "수아는 소주 안 마셨어"}))

    got = ask(api, room, "수아는 소주 안 마셨어").json()

    assert got["status"] == "PARSED"
    assert got["changes"] == [{
        "item_id": soju, "receipt_id": receipt["id"], "store_name": "1차 고깃집", "name": "소주",
        "rule": "EXCLUDE", "evidence": "수아는 소주 안 마셨어",
        "before_member_ids": [a, b, c, d], "after_member_ids": [a, b, c],
        "before_amount": 40000, "after_amount": 40000, "note": None,
    }]
    # 저장하지 않는다
    checks = api.get(f"/rooms/{room['room_token']}/checks").json()
    assert next(i for i in checks["items"] if i["item_id"] == soju)["member_ids"] == [a, b, c, d]


def test_apply_with_put_checks_makes_settlement_stale(api, room, receipt, monkeypatch):
    a, b, c, d = ids(room)
    soju = item_id(receipt, "소주")
    model_says(monkeypatch, parsed({"receipt_item_id": soju, "type": "FULL", "params": {"member_id": b}}))
    change = ask(api, room, "소주는 지영이가 다 낼게").json()["changes"][0]
    assert change["after_member_ids"] == [b]

    api.put(f"/rooms/{room['room_token']}/checks",
            {"items": [{"item_id": change["item_id"], "member_ids": change["after_member_ids"]}]})
    checks = api.get(f"/rooms/{room['room_token']}/checks").json()
    assert next(i for i in checks["items"] if i["item_id"] == soju)["member_ids"] == [b]


def test_equal_keeps_member_order(api, room, receipt, monkeypatch):
    a, b, c, d = ids(room)
    meat = item_id(receipt, "삼겹살")
    model_says(monkeypatch, parsed({"receipt_item_id": meat, "type": "EQUAL", "params": {"member_ids": [c, a]}}))
    got = ask(api, room, "삼겹살은 현우랑 민수끼리").json()
    assert got["changes"][0]["after_member_ids"] == [a, c]


def test_exclude_twice_keeps_earlier_exclusion(api, room, receipt, monkeypatch):
    a, b, c, d = ids(room)
    soju = item_id(receipt, "소주")
    api.put(f"/rooms/{room['room_token']}/checks", {"items": [{"item_id": soju, "member_ids": [a, b, c]}]})
    model_says(monkeypatch, parsed({"receipt_item_id": soju, "type": "EXCLUDE", "params": {"member_ids": [c]}}))
    got = ask(api, room, "현우도 소주 안 마셨어").json()
    assert got["changes"][0]["before_member_ids"] == [a, b, c]
    assert got["changes"][0]["after_member_ids"] == [a, b]


def test_no_change_needed(api, room, receipt, monkeypatch):
    soju = item_id(receipt, "소주")
    model_says(monkeypatch, parsed({"receipt_item_id": soju, "type": "EQUAL", "params": {"member_ids": ids(room)}}))
    got = ask(api, room, "소주는 민수 지영 현우 수아끼리").json()
    assert got["status"] == "PARSED" and got["changes"] == []
    assert "바꿀 것이 없습니다" in got["message"]


# ------------------------------------------------------------------ 서버 검사 → 다시 묻기 · 지원 안 함


@pytest.mark.parametrize("rule", [
    {"type": "WEIGHTED", "params": {"weights": [{"member_id": 0, "weight": 1}]}},
    {"type": "QUANTITY", "params": {"quantities": [{"member_id": 0, "quantity": 1}]}},
])
def test_weighted_and_quantity_are_unsupported_in_v1(api, room, receipt, monkeypatch, rule):
    rule = json.loads(json.dumps(rule).replace('"member_id": 0', f'"member_id": {ids(room)[0]}'))
    model_says(monkeypatch, parsed({"receipt_item_id": item_id(receipt, "삼겹살"), **rule}))
    got = ask(api, room, "삼겹살은 민수가 두 배").json()
    assert got["status"] == "UNSUPPORTED" and got["changes"] == []
    assert "다음 버전" in got["message"]


@pytest.mark.parametrize("answer, text", [
    ("이건 JSON이 아님", "수아는 소주 안 마셨어"),
    ({"status": "PARSED", "proposals": [], "clarification": None}, "수아는 소주 안 마셨어"),
    # 없는 품목 id, 문장에도 품목 이름이 없음 (고칠 근거가 없음)
    (parsed({"receipt_item_id": 999999, "type": "EXCLUDE", "params": {"member_ids": [1]}}), "수아는 안 마셨어"),
])
def test_bad_model_answer_asks_again(api, room, receipt, monkeypatch, answer, text):
    model_says(monkeypatch, answer)
    got = ask(api, room, text).json()
    assert got["status"] == "NEEDS_CLARIFICATION" and got["changes"] == []
    assert got["message"]


def test_member_not_in_sentence_is_replaced_by_named_member(api, room, receipt, monkeypatch):
    """모델이 문장에 없는 사람(지영)을 고르면, 문장에 나온 사람(수아)으로 고친다."""
    a, b, c, d = ids(room)
    model_says(monkeypatch, parsed({"receipt_item_id": item_id(receipt, "소주"), "type": "EXCLUDE",
                                    "params": {"member_ids": [b]}}))
    got = ask(api, room, "수아는 소주 안 마셨어").json()
    assert got["changes"][0]["after_member_ids"] == [a, b, c]


def test_item_not_in_sentence_is_replaced_by_named_item(api, room, receipt, monkeypatch):
    """모델이 문장에 없는 품목(삼겹살)을 고르면, 문장에 나온 품목(소주)으로 고친다."""
    a, b, c, d = ids(room)
    model_says(monkeypatch, parsed({"receipt_item_id": item_id(receipt, "삼겹살"), "type": "EXCLUDE",
                                    "params": {"member_ids": [d]}}))
    got = ask(api, room, "수아는 소주 안 마셨어").json()
    assert (got["changes"][0]["name"], got["changes"][0]["after_member_ids"]) == ("소주", [a, b, c])


def test_excluding_everyone_asks_again(api, room, receipt, monkeypatch):
    soju = item_id(receipt, "소주")
    model_says(monkeypatch, parsed({"receipt_item_id": soju, "type": "EXCLUDE", "params": {"member_ids": ids(room)}}))
    got = ask(api, room, "민수 지영 현우 수아 모두 소주 안 마셨어").json()
    assert got["status"] == "NEEDS_CLARIFICATION"


def test_model_clarification_question_is_passed_through(api, room, receipt, monkeypatch):
    model_says(monkeypatch, {"status": "NEEDS_CLARIFICATION", "proposals": [],
                             "clarification": {"question": "어떤 품목인가요?", "missing": ["item"]}})
    assert ask(api, room, "수아는 안 먹었어").json()["message"] == "어떤 품목인가요?"


def test_unrelated_sentence(api, room, receipt, monkeypatch):
    model_says(monkeypatch, {"status": "UNSUPPORTED", "proposals": [], "clarification": None})
    assert ask(api, room, "오늘 날씨 좋다").json()["status"] == "UNSUPPORTED"


# ------------------------------------------------------------------ 오류


def test_no_confirmed_receipt_is_409(api, room, monkeypatch):
    model_says(monkeypatch, "{}")
    assert error(ask(api, room, "수아는 소주 안 마셨어", expect=409))["code"] == "NO_CHECK_ITEMS"


def test_model_down_is_503(api, room, receipt, monkeypatch):
    def down(room, text):
        raise nl.AppError(503, "NL_UNAVAILABLE", "문장 해석기에 연결하지 못했습니다.")
    monkeypatch.setattr(nl, "call_model", down)
    assert error(ask(api, room, "수아는 소주 안 마셨어", expect=503))["code"] == "NL_UNAVAILABLE"


def test_llama_unreachable_is_503(api, room, receipt, monkeypatch):
    """llama 서버가 꺼져 있으면 503 NL_UNAVAILABLE."""
    monkeypatch.setattr(nl, "settings", nl.settings.__class__(nl_provider="llama",
                                                              nl_base_url="http://127.0.0.1:9/v1", nl_timeout=2))
    assert error(ask(api, room, "수아는 소주 안 마셨어", expect=503))["code"] == "NL_UNAVAILABLE"


@pytest.mark.parametrize("text", ["", "가" * 201])
def test_text_length(api, room, receipt, text):
    assert error(ask(api, room, text, expect=422))["code"] == "VALIDATION_ERROR"


def test_unknown_room_is_404(api):
    assert error(api.post("/rooms/nope/checks/interpret", {"text": "x"}, expect=404))["code"] == "NOT_FOUND"


# ------------------------------------------------------------------ stub (모델 없이 화면을 만들 때)


@pytest.mark.parametrize("text, rule, after", [
    ("수아는 소주 안 마셨어", "EXCLUDE", [0, 1, 2]),
    ("현우랑 수아는 소주 민수한테 보냈어", "PAID", [1]),
    ("소주는 지영이가 다 낼게", "FULL", [1]),
    ("삼겹살은 민수랑 현우끼리", "EQUAL", [0, 2]),
])
def test_stub_provider(api, room, receipt, text, rule, after):
    got = ask(api, room, text).json()
    assert got["provider"] == "stub"
    assert got["changes"][0]["rule"] == rule
    assert got["changes"][0]["after_member_ids"] == [ids(room)[n] for n in after]


# ------------------------------------------------------------------ 이미 보낸 돈 (PAID) · 적용


@pytest.fixture
def lodging(api, room) -> dict:
    """지영(2번)이 숙소비 400,000원을 결제한 영수증. 4명 모두 체크."""
    body = {"store_name": "숙소", "payer_member_id": ids(room)[1], "total_amount": 400000,
            "items": [{"name": "숙소비", "amount": 400000}]}
    r = api.post(f"/rooms/{room['room_token']}/receipts", body).json()
    return api.post(f"/rooms/{room['room_token']}/receipts/{r['id']}/confirm", expect=200).json()


def apply(api, room, changes, expect=200):
    return api.post(f"/rooms/{room['room_token']}/checks/apply", {"changes": changes}, expect=expect)


def test_paid_leaves_only_unpaid_share_computed_by_server(api, room, lodging, monkeypatch):
    a, b, c, d = ids(room)  # 민수 · 지영(결제) · 현우 · 수아
    item = lodging["items"][0]["id"]
    model_says(monkeypatch, parsed({"receipt_item_id": item, "type": "PAID", "params": {"member_ids": [c, d]}}))

    got = ask(api, room, "현우랑 수아는 숙소비 지영이한테 보냈어").json()
    change = got["changes"][0]
    assert change["rule"] == "PAID"
    assert change["after_member_ids"] == [a]
    assert (change["before_amount"], change["after_amount"]) == (400000, 100000)
    assert change["note"] == ("현우, 수아는 이미 지영에게 보냈으니, 숙소비 400,000원 중 민수 몫 100,000원만 남기고 "
                              "민수만 체크할게요.")

    apply(api, room, [{"item_id": item, "member_ids": change["after_member_ids"], "amount": change["after_amount"]}])
    receipt = api.get(f"/rooms/{room['room_token']}/receipts/{lodging['id']}").json()
    assert receipt["total_amount"] == 100000 and receipt["items"][0]["amount"] == 100000
    assert receipt["status"] == "CONFIRMED"
    s = api.post(f"/rooms/{room['room_token']}/settlements").json()
    assert [(t["from"]["name"], t["to"]["name"], t["amount"]) for t in s["transfers"]] == [("민수", "지영", 100000)]


def test_paid_share_keeps_remainder_won(api, room, monkeypatch):
    a, b, c, d = ids(room)
    body = {"store_name": "숙소", "payer_member_id": b, "total_amount": 100001, "items": [{"name": "숙소비", "amount": 100001}]}
    r = api.post(f"/rooms/{room['room_token']}/receipts", body).json()
    api.post(f"/rooms/{room['room_token']}/receipts/{r['id']}/confirm", expect=200)
    model_says(monkeypatch, parsed({"receipt_item_id": r["items"][0]["id"], "type": "PAID", "params": {"member_ids": [c, d]}}))
    # 100,001 ÷ 4 → 민수 25,001 (남는 1원은 구성원 순서대로)
    assert ask(api, room, "현우랑 수아는 숙소비 보냈어").json()["changes"][0]["after_amount"] == 25001


def test_paid_by_everyone_changes_nothing(api, room, lodging, monkeypatch):
    a, b, c, d = ids(room)
    model_says(monkeypatch, parsed({"receipt_item_id": lodging["items"][0]["id"], "type": "PAID",
                                    "params": {"member_ids": [a, c, d]}}))
    got = ask(api, room, "민수 현우 수아 모두 숙소비 보냈어").json()
    assert got["changes"] == [] and "모두 이미 냈어요" in got["message"]


def test_apply_cannot_raise_amount(api, room, lodging):
    item = lodging["items"][0]["id"]
    res = apply(api, room, [{"item_id": item, "member_ids": [ids(room)[0]], "amount": 500000}], expect=422)
    assert error(res)["code"] == "VALIDATION_ERROR"


def test_apply_checks_only_and_marks_stale(api, room, receipt):
    a, b, c, d = ids(room)
    api.post(f"/rooms/{room['room_token']}/settlements")
    apply(api, room, [{"item_id": item_id(receipt, "소주"), "member_ids": [a, b]}])
    assert api.get(f"/rooms/{room['room_token']}/settlements/latest").json()["is_stale"] is True


def test_apply_empty_check_is_rejected(api, room, receipt):
    res = apply(api, room, [{"item_id": item_id(receipt, "소주"), "member_ids": []}], expect=422)
    assert error(res)["code"] == "CHECK_EMPTY"


# ------------------------------------------------------------------ 되묻기 → 이어서 답하기


def test_follow_up_answer_is_joined_with_previous(api, room, monkeypatch):
    """수아는 아침 안 먹었어 → (메뉴를 되물음) → 해장국이랑 김밥 → 두 품목에서 수아 빼기."""
    a, b, c, d = ids(room)
    body = {"store_name": "해장국집", "payer_member_id": a, "total_amount": 40000,
            "items": [{"name": "해장국", "amount": 30000}, {"name": "김밥", "amount": 10000}]}
    r = api.post(f"/rooms/{room['room_token']}/receipts", body).json()
    api.post(f"/rooms/{room['room_token']}/receipts/{r['id']}/confirm", expect=200)

    first = ask(api, room, "수아는 아침 안 먹었어").json()  # stub
    assert first["status"] == "NEEDS_CLARIFICATION"
    assert first["message"] == "어떤 메뉴인가요? 알려 주시면 수아를 그 메뉴에서 뺄게요."
    assert first["text"] == "수아는 아침 안 먹었어"

    seen = []
    real = nl.call_model
    monkeypatch.setattr(nl, "call_model", lambda room_, text: seen.append(text) or real(room_, text))
    second = api.post(f"/rooms/{room['room_token']}/checks/interpret",
                      {"text": "해장국이랑 김밥", "previous": first["text"]}, expect=200).json()
    assert seen == ["수아는 아침 안 먹었어 해장국이랑 김밥"]
    assert second["status"] == "PARSED"
    assert [(ch["name"], ch["after_member_ids"]) for ch in second["changes"]] == [("해장국", [a, b, c]), ("김밥", [a, b, c])]


# ------------------------------------------------------------------ 작은 모델의 실수를 문장에 근거해 고치기 (11/18 실제 EXAONE)


def test_only_sentence_read_as_exclude_is_fixed(api, room, receipt, monkeypatch):
    """'지영이랑 현우만 탔어'를 EXAONE이 '지영 · 현우 빼기'로 답했다 → 끼리만으로 고친다."""
    a, b, c, d = ids(room)
    model_says(monkeypatch, parsed({"receipt_item_id": item_id(receipt, "삼겹살"), "type": "EXCLUDE",
                                    "params": {"member_ids": [b, c]}}))
    got = ask(api, room, "삼겹살은 지영이랑 현우만 먹었어").json()
    assert (got["changes"][0]["rule"], got["changes"][0]["after_member_ids"]) == ("EQUAL", [b, c])


def test_negative_sentence_read_as_equal_is_fixed(api, room, receipt, monkeypatch):
    a, b, c, d = ids(room)
    model_says(monkeypatch, parsed({"receipt_item_id": item_id(receipt, "소주"), "type": "EQUAL",
                                    "params": {"member_ids": [c]}}))
    got = ask(api, room, "현우는 소주 안 마셨어").json()
    assert got["changes"][0]["after_member_ids"] == [a, b, d]


def test_wrong_item_and_member_ids_are_fixed_from_sentence(api, room, receipt, monkeypatch):
    a, b, c, d = ids(room)
    model_says(monkeypatch, parsed({"receipt_item_id": 999999, "type": "EXCLUDE", "params": {"member_ids": [77]}}))
    got = ask(api, room, "현우는 소주 안 마셨어").json()
    assert got["status"] == "PARSED"
    assert (got["changes"][0]["name"], got["changes"][0]["after_member_ids"]) == ("소주", [a, b, d])


def test_no_fix_without_grounding(api, room, receipt, monkeypatch):
    """문장에 품목 이름이 없으면 고치지 않고 다시 묻는다."""
    model_says(monkeypatch, parsed({"receipt_item_id": 999999, "type": "EXCLUDE", "params": {"member_ids": [ids(room)[2]]}}))
    assert ask(api, room, "현우는 안 마셨어").json()["status"] == "NEEDS_CLARIFICATION"


# ------------------------------------------------------------------ AI 판단 기록 (nl_logs)


@pytest.fixture
def db(client):
    from app.db import get_db
    from app.main import app
    session = next(app.dependency_overrides[get_db]())
    yield session
    session.close()


def logs(db):
    from app.models import NlLog
    db.expire_all()
    return db.query(NlLog).order_by(NlLog.id).all()


def test_log_records_model_answer_repair_and_apply(api, db, room, receipt, monkeypatch):
    a, b, c, d = ids(room)
    meat = item_id(receipt, "삼겹살")
    model_says(monkeypatch, parsed({"receipt_item_id": meat, "type": "EXCLUDE", "params": {"member_ids": [b, c]}}))
    got = ask(api, room, "삼겹살은 지영이랑 현우만 먹었어").json()

    [entry] = logs(db)
    assert got["interpretation_id"] == entry.id
    assert (entry.model_rules, entry.final_rules, entry.repairs) == (["EXCLUDE"], ["EQUAL"], ["EXCLUDE→EQUAL"])
    assert entry.text == "삼겹살은 지영이랑 현우만 먹었어" and entry.status == "PARSED" and entry.outcome is None
    assert '"EXCLUDE"' in entry.raw

    ch = got["changes"][0]
    apply_body = {"changes": [{"item_id": ch["item_id"], "member_ids": ch["after_member_ids"]}],
                  "interpretation_id": got["interpretation_id"]}
    api.post(f"/rooms/{room['room_token']}/checks/apply", apply_body, expect=200)
    assert logs(db)[0].outcome == "APPLIED"


def test_moving_on_without_apply_is_recorded(api, db, room, receipt, monkeypatch):
    model_says(monkeypatch, parsed({"receipt_item_id": item_id(receipt, "소주"), "type": "EXCLUDE",
                                    "params": {"member_ids": [ids(room)[3]]}}))
    ask(api, room, "수아는 소주 안 마셨어")
    ask(api, room, "수아는 소주 안 마셨다니까")
    first, second = logs(db)
    assert (first.outcome, second.outcome) == ("MOVED_ON", None)


def test_answering_a_question_is_linked(api, db, room, receipt):
    q = ask(api, room, "수아는 안 마셨어").json()  # stub: 품목이 없어서 되묻는다
    assert q["status"] == "NEEDS_CLARIFICATION"
    ans = api.post(f"/rooms/{room['room_token']}/checks/interpret", {"text": "소주", "previous": q["text"]},
                   expect=200).json()
    first, second = logs(db)
    assert first.outcome == "ANSWERED" and second.answers_id == first.id
    assert ans["interpretation_id"] == second.id


def test_manual_fix_after_apply_is_recorded(api, db, room, receipt, monkeypatch):
    """AI가 '수아 빼기'를 반영했는데 사용자가 체크 표에서 현우까지 빼면, AI가 틀렸다는 기록이 남는다."""
    a, b, c, d = ids(room)
    soju = item_id(receipt, "소주")
    model_says(monkeypatch, parsed({"receipt_item_id": soju, "type": "EXCLUDE", "params": {"member_ids": [d]}}))
    got = ask(api, room, "수아는 소주 안 마셨어").json()
    api.post(f"/rooms/{room['room_token']}/checks/apply",
             {"changes": [{"item_id": soju, "member_ids": [a, b, c]}], "interpretation_id": got["interpretation_id"]},
             expect=200)
    api.put(f"/rooms/{room['room_token']}/checks", {"items": [{"item_id": soju, "member_ids": [a, b]}]})
    [entry] = logs(db)
    assert [(f["name"], f["ai_member_ids"], f["user_member_ids"]) for f in entry.manual_fixes] == [
        ("소주", [a, b, c], [a, b])]


def test_saving_same_checks_is_not_a_fix(api, db, room, receipt, monkeypatch):
    a, b, c, d = ids(room)
    soju = item_id(receipt, "소주")
    model_says(monkeypatch, parsed({"receipt_item_id": soju, "type": "EXCLUDE", "params": {"member_ids": [d]}}))
    got = ask(api, room, "수아는 소주 안 마셨어").json()
    api.post(f"/rooms/{room['room_token']}/checks/apply",
             {"changes": [{"item_id": soju, "member_ids": [a, b, c]}], "interpretation_id": got["interpretation_id"]},
             expect=200)
    api.put(f"/rooms/{room['room_token']}/checks", {"items": [{"item_id": soju, "member_ids": [c, b, a]}]})
    assert logs(db)[0].manual_fixes == []
