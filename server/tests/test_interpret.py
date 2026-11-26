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
    assert ask(api, room, "그거는 따로 계산해 줘").json()["message"] == "어떤 품목인가요?"


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


def apply(api, room, changes, expect=200, interpretation_id=None):
    body = {"changes": changes, "interpretation_id": interpretation_id}
    return api.post(f"/rooms/{room['room_token']}/checks/apply", body, expect=expect)


def apply_all(api, room, got, expect=200):
    """변경안을 화면처럼 반영한다 (금액은 바뀔 때만, 해석 기록 번호와 같이)."""
    changes = [{"item_id": c["item_id"], "member_ids": c["after_member_ids"],
                **({"amount": c["after_amount"]} if c["after_amount"] != c["before_amount"] else {})}
               for c in got["changes"]]
    return apply(api, room, changes, expect, got["interpretation_id"])


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

    apply_all(api, room, got)
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


def confirmed(api, room, body) -> dict:
    r = api.post(f"/rooms/{room['room_token']}/receipts", body).json()
    return api.post(f"/rooms/{room['room_token']}/receipts/{r['id']}/confirm", expect=200).json()


def test_apply_amount_must_come_from_interpretation(api, room, lodging, monkeypatch):
    """금액은 서버가 계산한 변경안 그대로만 바꾼다. 해석 없이 보내거나 다른 숫자를 보내면 422."""
    a, b, c, d = ids(room)
    item = lodging["items"][0]["id"]
    res = apply(api, room, [{"item_id": item, "member_ids": [a], "amount": 1}], expect=422)
    assert error(res)["details"]["fields"] == {"changes.0.amount": "AI 총무 변경안의 금액이 아닙니다"}
    model_says(monkeypatch, parsed({"receipt_item_id": item, "type": "PAID", "params": {"member_ids": [c, d]}}))
    got = ask(api, room, "현우랑 수아는 숙소비 보냈어").json()
    apply(api, room, [{"item_id": item, "member_ids": [a], "amount": 1}], expect=422,
          interpretation_id=got["interpretation_id"])
    assert api.get(f"/rooms/{room['room_token']}/receipts/{lodging['id']}").json()["total_amount"] == 400000


def test_apply_outdated_paid_change_is_409(api, room, lodging, monkeypatch):
    """같은 체크 표로 만든 변경안 두 개를 차례로 반영하면, 두 번째는 바뀌기 전 금액 · 체크로 계산한 것이라 409."""
    a, b, c, d = ids(room)  # 지영(b)이 결제
    item = lodging["items"][0]["id"]
    model_says(monkeypatch, parsed({"receipt_item_id": item, "type": "PAID", "params": {"member_ids": [c]}}))
    first = ask(api, room, "현우는 숙소비 보냈어").json()
    model_says(monkeypatch, parsed({"receipt_item_id": item, "type": "PAID", "params": {"member_ids": [d]}}))
    second = ask(api, room, "수아는 숙소비 보냈어").json()
    # 남은 금액이 우연히 같아도(200,000) 막아야 한다. 아니면 수아가 다시 체크된다
    assert first["changes"][0]["after_amount"] == second["changes"][0]["after_amount"] == 200000
    apply_all(api, room, first)
    assert error(apply_all(api, room, second, expect=409))["code"] == "CHANGE_OUTDATED"


def test_paid_is_blocked_when_discount_would_go_to_others(api, room, monkeypatch):
    """숙소 300,000 − 쿠폰 20,000 (1인 70,000). 지영 · 현우가 보냈다고 빼면 쿠폰을 수아 혼자 받게 되므로 막는다."""
    a, b, c, d = ids(room)
    r = confirmed(api, room, {"store_name": "숙소", "payer_member_id": a, "total_amount": 280000,
                              "items": [{"name": "숙소비", "amount": 300000},
                                        {"name": "쿠폰", "amount": -20000, "kind": "DISCOUNT"}]})
    model_says(monkeypatch, parsed({"receipt_item_id": item_id(r, "숙소비"), "type": "PAID",
                                    "params": {"member_ids": [b, c]}}))
    got = ask(api, room, "지영이랑 현우는 숙소비 보냈어").json()
    assert got["changes"] == [] and "할인이나 품목 합과 총액의 차이" in got["message"]


def test_paid_is_allowed_when_discount_split_stays(api, room, receipt, monkeypatch):
    """보낸 사람이 같은 영수증의 다른 품목에 남아 있으면 쿠폰을 나누는 사람이 그대로라서 정산이 맞다."""
    a, b, c, d = ids(room)  # 민수(결제) · 지영 · 현우 · 수아. 115,000 ÷ 4 = 1인 28,750
    model_says(monkeypatch, parsed({"receipt_item_id": item_id(receipt, "소주"), "type": "PAID",
                                    "params": {"member_ids": [b]}}))
    got = ask(api, room, "지영은 소주값 보냈어").json()
    assert [(ch["after_member_ids"], ch["after_amount"]) for ch in got["changes"]] == [([c, d], 20000)]
    apply_all(api, room, got)
    s = api.post(f"/rooms/{room['room_token']}/settlements").json()
    # 지영은 소주 몫 10,000원을 이미 보냈으니 18,750원만
    assert [(t["from"]["name"], t["amount"]) for t in s["transfers"]] == [("지영", 18750), ("현우", 28750),
                                                                         ("수아", 28750)]


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
    assert first["message"] == "아침 메뉴가 무엇인가요? 알려 주시면 수아를 그 메뉴에서 뺄게요."
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


def test_ai_log_summary(api, db, room, receipt, monkeypatch):
    a, b, c, d = ids(room)
    meat, soju = item_id(receipt, "삼겹살"), item_id(receipt, "소주")
    model_says(monkeypatch, parsed({"receipt_item_id": meat, "type": "EXCLUDE", "params": {"member_ids": [b, c]}}))
    got = ask(api, room, "삼겹살은 지영이랑 현우만 먹었어").json()
    api.post(f"/rooms/{room['room_token']}/checks/apply",
             {"changes": [{"item_id": meat, "member_ids": [b, c]}], "interpretation_id": got["interpretation_id"]},
             expect=200)
    model_says(monkeypatch, {"status": "NEEDS_CLARIFICATION", "proposals": [], "clarification": None})
    ask(api, room, "수아는 안 마셨어")
    api.put(f"/rooms/{room['room_token']}/checks", {"items": [{"item_id": meat, "member_ids": [b]}]})
    assert soju

    log = api.get(f"/rooms/{room['room_token']}/checks/ai-log").json()
    s = log["summary"]
    assert s["total"] == 2
    assert s["by_status"] == {"PARSED": 1, "NEEDS_CLARIFICATION": 1}
    assert (s["proposals"], s["applied"], s["apply_rate"]) == (1, 1, 1.0)
    assert (s["fixed_after_apply"], s["fix_rate"]) == (1, 1.0)
    assert s["repairs"] == {"EXCLUDE→EQUAL": 1}
    m = s["rule_matrix"]
    assert m["cells"][m["rows"].index("EXCLUDE")][m["cols"].index("EQUAL")] == 1
    assert [e["text"] for e in log["entries"]] == ["수아는 안 마셨어", "삼겹살은 지영이랑 현우만 먹었어"]


def test_report_script_runs(api, room, receipt, monkeypatch, tmp_path):
    """스크립트가 모델 · 집계와 맞물려 도는지만 본다 (출력 형식은 사람이 읽는 용도)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("nl_report_script", "scripts/nl_report.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.pct(0.5) == "50%" and mod.pct(None) == "-"


@pytest.mark.parametrize("model_answer", [
    # 11/18 실제 EXAONE: 품목을 짐작해서 냄 → 서버 검사에서 막힘
    "guess",
    # 모델이 스스로 되물음 (질문이 짧음)
    {"status": "NEEDS_CLARIFICATION", "proposals": [], "clarification": {"question": "아침 메뉴가 무엇인가요?", "missing": ["item"]}},
])
def test_menu_question_says_what_happens_next(api, room, receipt, monkeypatch, model_answer):
    if model_answer == "guess":
        model_answer = parsed({"receipt_item_id": item_id(receipt, "삼겹살"), "type": "EXCLUDE",
                               "params": {"member_ids": [ids(room)[3]]}})
    model_says(monkeypatch, model_answer)
    got = ask(api, room, "수아는 아침 안 먹었어").json()
    assert got["status"] == "NEEDS_CLARIFICATION"
    assert got["message"] == "아침 메뉴가 무엇인가요? 알려 주시면 수아를 그 메뉴에서 뺄게요."


def test_paid_with_restated_result_is_merged(api, room, lodging, monkeypatch):
    """'현우랑 수아는 숙소비를 보냈어 민수만 보내면 돼' → 모델이 PAID와 EQUAL(민수)을 같이 내도 이미 보냄 하나로."""
    a, b, c, d = ids(room)
    item = lodging["items"][0]["id"]
    model_says(monkeypatch, parsed({"receipt_item_id": item, "type": "PAID", "params": {"member_ids": [c, d]}},
                                   {"receipt_item_id": item, "type": "EQUAL", "params": {"member_ids": [a]}}))
    got = ask(api, room, "현우랑 수아는 숙소비를 보냈어 민수만 보내면 돼").json()
    assert got["status"] == "PARSED"
    assert [(ch["rule"], ch["after_member_ids"], ch["after_amount"]) for ch in got["changes"]] == [("PAID", [a], 100000)]


def test_conflicting_rules_still_ask_again(api, room, receipt, monkeypatch):
    a, b, c, d = ids(room)
    soju = item_id(receipt, "소주")
    model_says(monkeypatch, parsed({"receipt_item_id": soju, "type": "EXCLUDE", "params": {"member_ids": [d]}},
                                   {"receipt_item_id": soju, "type": "FULL", "params": {"member_id": a}}))
    got = ask(api, room, "수아는 소주 안 마셨고 민수가 소주 다 낼게").json()
    assert got["status"] == "NEEDS_CLARIFICATION" and got["follow_up"] is False


def test_follow_up_only_for_real_questions(api, room, receipt, monkeypatch):
    model_says(monkeypatch, "JSON 아님")
    assert ask(api, room, "수아는 소주 안 마셨어").json()["follow_up"] is False  # 다시 말해 주세요
    model_says(monkeypatch, {"status": "NEEDS_CLARIFICATION", "proposals": [], "clarification": None})
    assert ask(api, room, "수아는 아침 안 먹었어").json()["follow_up"] is True  # 메뉴를 묻는 진짜 질문


# ------------------------------------------------------------------ 큰 모델로 넘기기 (작은 모델이 못 알아들을 때만)


@pytest.fixture
def with_key(monkeypatch):
    monkeypatch.setattr(nl, "settings", nl.settings.__class__(nl_provider="llama", nl_fallback_api_key="sk-test"))


def big_says(monkeypatch, answer, seen=None):
    raw = answer if isinstance(answer, str) else json.dumps(answer, ensure_ascii=False)

    def call(room_, text):
        if seen is not None:
            seen.append(text)
        return raw
    monkeypatch.setattr(nl, "call_fallback", call)


def test_escalates_when_small_model_fails_check(api, db, room, receipt, monkeypatch, with_key):
    a, b, c, d = ids(room)
    soju = item_id(receipt, "소주")
    model_says(monkeypatch, "JSON 아님")  # 작은 모델 실패 → 다시 묻기
    seen = []
    big_says(monkeypatch, parsed({"receipt_item_id": soju, "type": "EXCLUDE", "params": {"member_ids": [d]}}), seen)
    got = ask(api, room, "수아는 소주 안 마셨어").json()
    assert seen == ["수아는 소주 안 마셨어"]
    assert got["provider"] == "llama→openai" and got["changes"][0]["after_member_ids"] == [a, b, c]
    [entry] = logs(db)
    assert "큰 모델로 넘김" in entry.repairs and entry.provider == "llama→openai"
    assert "--- gpt-4.1-mini ---" in entry.raw
    s = api.get(f"/rooms/{room['room_token']}/checks/ai-log").json()["summary"]
    assert s["escalated"] == 1 and s["by_provider"] == {"llama→openai": 1}


def test_no_escalation_for_real_question_or_success(api, room, receipt, monkeypatch, with_key):
    seen = []
    big_says(monkeypatch, "{}", seen)
    model_says(monkeypatch, {"status": "NEEDS_CLARIFICATION", "proposals": [], "clarification": None})
    assert ask(api, room, "수아는 아침 안 먹었어").json()["follow_up"] is True  # 메뉴를 묻는 진짜 질문
    model_says(monkeypatch, parsed({"receipt_item_id": item_id(receipt, "소주"), "type": "EXCLUDE",
                                    "params": {"member_ids": [ids(room)[3]]}}))
    assert ask(api, room, "수아는 소주 안 마셨어").json()["provider"] == "llama"
    assert seen == []


def test_no_escalation_without_key(api, room, receipt, monkeypatch):
    seen = []
    big_says(monkeypatch, "{}", seen)
    model_says(monkeypatch, "JSON 아님")
    assert ask(api, room, "수아는 소주 안 마셨어").json()["status"] == "NEEDS_CLARIFICATION"
    assert seen == []


def test_escalates_when_small_model_is_down(api, room, receipt, monkeypatch, with_key):
    def down(room_, text):
        raise nl.AppError(503, "NL_UNAVAILABLE", "x")
    monkeypatch.setattr(nl, "call_model", down)
    big_says(monkeypatch, parsed({"receipt_item_id": item_id(receipt, "소주"), "type": "EXCLUDE",
                                  "params": {"member_ids": [ids(room)[3]]}}))
    got = ask(api, room, "수아는 소주 안 마셨어").json()
    assert got["status"] == "PARSED" and got["provider"] == "llama→openai"


def test_big_model_down_keeps_small_model_answer(api, db, room, receipt, monkeypatch, with_key):
    """작은 모델은 답했는데 큰 모델만 안 되면, 503 대신 작은 모델의 다시 묻기를 그대로 돌려준다."""
    model_says(monkeypatch, "JSON 아님")

    def down(room_, text):
        raise nl.AppError(503, "NL_UNAVAILABLE", "x")
    monkeypatch.setattr(nl, "call_fallback", down)
    got = ask(api, room, "수아는 소주 안 마셨어").json()
    assert got["status"] == "NEEDS_CLARIFICATION" and got["provider"] == "llama"
    assert "큰 모델 연결 실패" in logs(db)[0].repairs


def test_both_models_down_is_503(api, room, receipt, monkeypatch, with_key):
    def down(room_, text):
        raise nl.AppError(503, "NL_UNAVAILABLE", "x")
    monkeypatch.setattr(nl, "call_model", down)
    monkeypatch.setattr(nl, "call_fallback", down)
    assert error(ask(api, room, "수아는 소주 안 마셨어", expect=503))["code"] == "NL_UNAVAILABLE"


def test_openai_schema_is_strict_compatible():
    s = nl._strict(nl.SCHEMA)
    dumped = json.dumps(s)
    assert "minItems" not in dumped

    def check(x):
        if isinstance(x, dict):
            if "properties" in x:
                assert sorted(x["required"]) == sorted(x["properties"]) and x.get("additionalProperties") is False
            for v in x.values():
                check(v)
        elif isinstance(x, list):
            for v in x:
                check(v)
    check(s)


def test_missing_named_item_gets_same_rule(api, room, monkeypatch):
    """'수아는 아침 안 먹었어 해장국이랑 김밥'에서 모델이 해장국만 냈다(11/19 실제 EXAONE) → 김밥에도 같은 빼기."""
    a, b, c, d = ids(room)
    body = {"store_name": "해장국집", "payer_member_id": a, "total_amount": 43500,
            "items": [{"name": "해장국", "amount": 34000}, {"name": "김밥", "amount": 9500}]}
    r = api.post(f"/rooms/{room['room_token']}/receipts", body).json()
    api.post(f"/rooms/{room['room_token']}/receipts/{r['id']}/confirm", expect=200)
    soup = next(i["id"] for i in r["items"] if i["name"] == "해장국")
    model_says(monkeypatch, parsed({"receipt_item_id": soup, "type": "EXCLUDE", "params": {"member_ids": [d]}}))
    got = api.post(f"/rooms/{room['room_token']}/checks/interpret",
                   {"text": "해장국이랑 김밥", "previous": "수아는 아침 안 먹었어"}, expect=200).json()
    assert [(ch["name"], ch["after_member_ids"]) for ch in got["changes"]] == [("해장국", [a, b, c]), ("김밥", [a, b, c])]


def test_different_rules_do_not_spread(api, room, receipt, monkeypatch):
    """규칙이 서로 다르면 문장에 나온 다른 품목으로 퍼뜨리지 않는다."""
    a, b, c, d = ids(room)
    model_says(monkeypatch, parsed({"receipt_item_id": item_id(receipt, "소주"), "type": "EXCLUDE", "params": {"member_ids": [d]}},
                                   {"receipt_item_id": item_id(receipt, "삼겹살"), "type": "FULL", "params": {"member_id": a}}))
    got = ask(api, room, "수아는 소주 안 마셨고 삼겹살은 민수가 다 낼게").json()
    assert sorted(ch["name"] for ch in got["changes"]) == ["삼겹살", "소주"]


def test_item_inside_longer_name_is_not_changed(api, room, monkeypatch):
    """'아이스커피'만 말했으면 이름이 그 안에 들어 있는 '커피'는 바꾸지 않는다 (빠진 품목 추가 · 품목 고치기 모두)."""
    d = ids(room)[3]
    r = confirmed(api, room, {"store_name": "카페", "payer_member_id": ids(room)[0], "total_amount": 9000,
                              "items": [{"name": "커피", "amount": 4000}, {"name": "아이스커피", "amount": 5000}]})

    def names(item, text):
        model_says(monkeypatch, parsed({"receipt_item_id": item_id(r, item), "type": "EXCLUDE",
                                        "params": {"member_ids": [d]}}))
        return sorted(ch["name"] for ch in ask(api, room, text).json()["changes"])

    assert names("아이스커피", "수아는 아이스커피 안 마셨어") == ["아이스커피"]
    assert names("커피", "수아는 아이스커피 안 마셨어") == ["아이스커피"]  # 모델이 짧은 이름을 골라도 문장대로
    assert names("커피", "수아는 커피랑 아이스커피 안 마셨어") == ["아이스커피", "커피"]
