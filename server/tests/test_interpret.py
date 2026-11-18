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
    # 없는 품목 id
    (parsed({"receipt_item_id": 999999, "type": "EXCLUDE", "params": {"member_ids": [1]}}), "수아는 소주 안 마셨어"),
])
def test_bad_model_answer_asks_again(api, room, receipt, monkeypatch, answer, text):
    model_says(monkeypatch, answer)
    got = ask(api, room, text).json()
    assert got["status"] == "NEEDS_CLARIFICATION" and got["changes"] == []
    assert got["message"]


def test_member_not_in_sentence_asks_again(api, room, receipt, monkeypatch):
    """모델이 문장에 없는 사람을 지어내면 다시 묻는다."""
    a, b, c, d = ids(room)
    model_says(monkeypatch, parsed({"receipt_item_id": item_id(receipt, "소주"), "type": "EXCLUDE",
                                    "params": {"member_ids": [b]}}))
    got = ask(api, room, "수아는 소주 안 마셨어").json()
    assert got["status"] == "NEEDS_CLARIFICATION"
    assert "사람" in got["message"]


def test_item_not_in_sentence_asks_again(api, room, receipt, monkeypatch):
    a, b, c, d = ids(room)
    model_says(monkeypatch, parsed({"receipt_item_id": item_id(receipt, "삼겹살"), "type": "EXCLUDE",
                                    "params": {"member_ids": [d]}}))
    got = ask(api, room, "수아는 소주 안 마셨어").json()
    assert got["status"] == "NEEDS_CLARIFICATION"
    assert "품목" in got["message"]


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
    ("소주는 지영이가 다 낼게", "FULL", [1]),
    ("삼겹살은 민수랑 현우끼리", "EQUAL", [0, 2]),
])
def test_stub_provider(api, room, receipt, text, rule, after):
    got = ask(api, room, text).json()
    assert got["provider"] == "stub"
    assert got["changes"][0]["rule"] == rule
    assert got["changes"][0]["after_member_ids"] == [ids(room)[n] for n in after]
