"""문장 해석 — "D는 술 안 마셨어" 같은 문장을 체크 표 변경안으로 바꾼다 (V3 미리 연결).

흐름: 정산방 데이터 + 문장 → 해석기(llama.cpp 또는 stub) → 규칙 JSON → 서버 검사 → 체크 표 변경안.
변경안은 저장하지 않는다. 화면이 사용자에게 보여 주고, 적용하면 기존 체크 표 저장 API(PUT /checks)로 저장한다.

프롬프트 · JSON schema · 서버 검사는 llm/bench.py(PR #13, 11/4 노트북 시험 20문장 중 19개)와 같은 것을 쓴다.
V1 정산은 "체크한 사람끼리 똑같이"만 계산하므로, 규칙 다섯 가지 중
EQUAL(~끼리만) · EXCLUDE(~빼고) · FULL(~가 다 낼게)만 체크 표로 바꾼다. WEIGHTED(비율) · QUANTITY(수량)는 안내만 한다.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from .core.config import settings
from .core.errors import AppError

TYPES = ["EQUAL", "EXCLUDE", "FULL", "WEIGHTED", "QUANTITY"]
CHECKABLE = {"EQUAL", "EXCLUDE", "FULL"}

# ------------------------------------------------------------------ 출력 모양 (bench.py와 같음)

INT = {"type": "integer"}
IDS = {"type": "array", "items": INT, "minItems": 1}


def _pairs(key: str) -> dict:
    return {
        "type": "array",
        "minItems": 1,
        "items": {
            "type": "object",
            "properties": {"member_id": INT, key: INT},
            "required": ["member_id", key],
            "additionalProperties": False,
        },
    }


PARAMS = {
    "EQUAL": ({"member_ids": IDS}, ["member_ids"]),
    "EXCLUDE": ({"member_ids": IDS}, ["member_ids"]),
    "FULL": ({"member_id": INT}, ["member_id"]),
    "WEIGHTED": ({"weights": _pairs("weight")}, ["weights"]),
    "QUANTITY": ({"quantities": _pairs("quantity")}, ["quantities"]),
}


def _proposal_schema(rule_type: str) -> dict:
    props, required = PARAMS[rule_type]
    return {
        "type": "object",
        "properties": {
            "receipt_item_id": INT,
            "type": {"type": "string", "enum": [rule_type]},
            "params": {"type": "object", "properties": props, "required": required, "additionalProperties": False},
            "evidence": {"type": "string"},
        },
        "required": ["receipt_item_id", "type", "params"],
        "additionalProperties": False,
    }


SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["PARSED", "NEEDS_CLARIFICATION", "UNSUPPORTED"]},
        "proposals": {"type": "array", "items": {"anyOf": [_proposal_schema(t) for t in TYPES]}},
        "clarification": {
            "anyOf": [
                {"type": "null"},
                {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string"},
                        "missing": {
                            "type": "array",
                            "items": {"type": "string", "enum": ["item", "member", "ratio", "quantity"]},
                        },
                    },
                    "required": ["question", "missing"],
                    "additionalProperties": False,
                },
            ]
        },
    },
    "required": ["status", "proposals", "clarification"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """너는 정산 앱의 '분담 조건 해석기'다. 사용자의 문장을 분담 규칙 JSON으로 바꾼다. 금액 계산은 하지 않는다.

규칙:
- 구성원과 항목은 <데이터>에 있는 id 숫자로만 가리킨다. 이름 문자열을 쓰지 않는다.
- type 다섯 가지:
  - EQUAL: 지정한 사람끼리만 똑같이 → params.member_ids
  - EXCLUDE: 전체 구성원에서 몇 명을 빼고 똑같이 → params.member_ids (빠지는 사람)
  - FULL: 한 명이 전부 → params.member_id
  - WEIGHTED: 비율로 나눔 → params.weights = [{member_id, weight}]
  - QUANTITY: 각자 먹은 수량 → params.quantities = [{member_id, quantity}], 수량 합이 항목 quantity와 같아야 한다
- 항목 · 사람 · 비율 · 수량 중 하나라도 문장만으로 정할 수 없으면 status="NEEDS_CLARIFICATION", proposals=[], clarification에 짧은 질문과 missing을 넣는다.
- 정산과 관계없는 문장이면 status="UNSUPPORTED", proposals=[].
- 문장에 없는 사람 · 항목 · 숫자를 만들지 않는다.
- PARSED일 때 clarification은 null이다. evidence에는 근거가 된 문장 부분을 넣는다.
- 한 항목에는 규칙을 하나만 만든다. 수량은 한 규칙의 quantities에 모두 넣는다.

종류 고르는 법:
- "~만", "~끼리", "~둘이서/셋이서" → 말한 사람들만 낸다 → EQUAL (member_ids = 말한 사람들)
- "~빼고", "~는 안 먹었어/안 마셨어" → 말한 사람을 뺀다 → EXCLUDE (member_ids = 빠지는 사람들)
- "~가 전부/다 낼게" → FULL
- "1:1:2", "두 배" 처럼 비율 숫자 → WEIGHTED
- "~인분", "~개" 처럼 각자 먹은 수량 → QUANTITY. 일부 사람의 수량만 나와서 합이 항목 quantity와 맞지 않으면 NEEDS_CLARIFICATION

예시 (데이터에 '커피'(id 900, quantity 1)가 있을 때):
문장: 커피는 A만 마셨어
답: {"status":"PARSED","proposals":[{"receipt_item_id":900,"type":"FULL","params":{"member_id":1},"evidence":"커피는 A만 마셨어"}],"clarification":null}
"""


# ------------------------------------------------------------------ 해석기에 넘기는 데이터


@dataclass
class Item:
    id: int
    name: str
    amount: int
    receipt_id: int
    store_name: str
    member_ids: list[int]  # 지금 체크된 사람 (구성원 순서)


@dataclass
class RoomData:
    members: list[tuple[int, str]]  # (id, 이름), 구성원 순서
    items: list[Item]
    names: dict[int, str] = field(init=False)

    def __post_init__(self) -> None:
        self.names = dict(self.members)

    def context(self) -> dict:
        """bench.py의 CONTEXT와 같은 모양. V1에는 수량 칸이 없으므로 모두 1이다."""
        return {
            "members": [{"id": i, "name": n} for i, n in self.members],
            "items": [{"id": it.id, "name": it.name, "quantity": 1, "amount": it.amount,
                       "receipt_title": it.store_name} for it in self.items],
        }


# ------------------------------------------------------------------ 해석기 (provider)


def _call_llama(room: RoomData, text: str) -> str:
    user = ("<데이터>\n" + json.dumps(room.context(), ensure_ascii=False)
            + "\n</데이터>\n<문장>\n" + text + "\n</문장>")
    body = {
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}],
        "temperature": 0,
        "max_tokens": 400,
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": "allocation_rules", "strict": True, "schema": SCHEMA}},
        "chat_template_kwargs": {"enable_thinking": False},
    }
    req = urllib.request.Request(
        settings.nl_base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=settings.nl_timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]
    except (urllib.error.URLError, TimeoutError, OSError, KeyError, IndexError, ValueError) as exc:
        raise AppError(503, "NL_UNAVAILABLE",
                       "문장 해석기에 연결하지 못했습니다. 잠시 뒤 다시 시도하거나 체크 표에서 직접 바꿔 주세요.",
                       {"reason": type(exc).__name__}) from exc


def _call_stub(room: RoomData, text: str) -> str:
    """모델 없이 화면 · 테스트를 만들 때 쓰는 간단한 흉내. 실제 시연은 llama로 한다."""
    who = [i for i, n in room.members if n in text]
    what = [it for it in room.items if it.name in text]
    clarify = {"status": "NEEDS_CLARIFICATION", "proposals": [],
               "clarification": {"question": "어떤 품목을 누가 내는지 알려 주세요.", "missing": ["item", "member"]}}
    if not who or len(what) != 1:
        return json.dumps(clarify, ensure_ascii=False)
    item = what[0].id
    if any(k in text for k in ("전부", "다 낼", "다 내", "쏠게", "쏜다")) and len(who) == 1:
        p = {"receipt_item_id": item, "type": "FULL", "params": {"member_id": who[0]}}
    elif any(k in text for k in ("빼고", "안 먹", "안 마", "안먹", "안마")):
        p = {"receipt_item_id": item, "type": "EXCLUDE", "params": {"member_ids": who}}
    elif any(k in text for k in ("만", "끼리")):
        p = {"receipt_item_id": item, "type": "EQUAL", "params": {"member_ids": who}}
    else:
        return json.dumps(clarify, ensure_ascii=False)
    p["evidence"] = text
    return json.dumps({"status": "PARSED", "proposals": [p], "clarification": None}, ensure_ascii=False)


def call_model(room: RoomData, text: str) -> str:
    """해석기를 불러 JSON 문자열을 받는다. 테스트에서는 이 함수를 바꿔 끼운다."""
    if settings.nl_provider == "llama":
        return _call_llama(room, text)
    return _call_stub(room, text)


# ------------------------------------------------------------------ 서버 검사 (bench.py validate와 같은 규칙)

ASK_AGAIN = "어떤 품목을 누가 내는지 조금 더 구체적으로 말해 주세요. 예: \"D는 술 안 마셨어\""


@dataclass
class Checked:
    status: str  # PARSED · NEEDS_CLARIFICATION · UNSUPPORTED
    proposals: list[dict]
    message: str


def _clarify(question: str | None = None) -> Checked:
    return Checked("NEEDS_CLARIFICATION", [], question or ASK_AGAIN)


def validate(raw: str, text: str, room: RoomData) -> Checked:
    """모델 답을 검사한다. 고칠 수 있으면 고치고, 아니면 다시 묻기로 바꾼다."""
    try:
        result = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return _clarify()
    if not isinstance(result, dict) or result.get("status") not in ("PARSED", "NEEDS_CLARIFICATION", "UNSUPPORTED"):
        return _clarify()
    if result["status"] == "UNSUPPORTED":
        return Checked("UNSUPPORTED", [], "정산과 관계없는 문장 같아요. 누가 어떤 품목을 내는지 말해 주세요.")
    if result["status"] == "NEEDS_CLARIFICATION":
        question = (result.get("clarification") or {}).get("question")
        return _clarify(question if isinstance(question, str) and question.strip() else None)

    items = {it.id: it for it in room.items}
    member_ids = [i for i, _ in room.members]
    merged: dict[int, dict] = {}
    for p in result.get("proposals") or []:
        if not isinstance(p, dict):
            return _clarify()
        item, rule_type, params = p.get("receipt_item_id"), p.get("type"), p.get("params") or {}
        if item not in items or rule_type not in PARAMS:
            return _clarify()
        keys, _ = PARAMS[rule_type]
        params = {k: v for k, v in params.items() if k in keys}  # 종류에 맞지 않는 칸은 버린다
        if item in merged:
            return _clarify()  # 같은 품목에 규칙 2개
        merged[item] = {"receipt_item_id": item, "type": rule_type, "params": params,
                        "evidence": p.get("evidence") if isinstance(p.get("evidence"), str) else None}
    if not merged:
        return _clarify()

    for item, p in merged.items():
        t, prm = p["type"], p["params"]
        if t not in CHECKABLE:
            return Checked("UNSUPPORTED", [],
                           "비율이나 수량으로 나누기는 다음 버전에서 지원해요. "
                           "지금은 '~ 빼고', '~가 다 낼게', '~끼리만'을 알아들어요.")
        ids = [prm.get("member_id")] if t == "FULL" else list(prm.get("member_ids") or [])
        if not ids or any(i not in member_ids for i in ids) or len(ids) != len(set(ids)):
            return _clarify()
        # 문장에 없는 사람 · 품목을 모델이 지어내면 다시 묻는다
        if any(room.names[i] not in text for i in ids):
            return _clarify("문장에 나온 사람을 찾지 못했어요. 구성원 이름을 그대로 써 주세요.")
        if items[item].name not in text:
            return _clarify("문장에 나온 품목을 찾지 못했어요. 체크 표의 품목 이름을 그대로 써 주세요.")
    return Checked("PARSED", list(merged.values()), "")


# ------------------------------------------------------------------ 규칙 → 체크 표 변경안


def to_changes(checked: Checked, room: RoomData) -> tuple[str, str, list[dict]]:
    """검사를 통과한 규칙을 '품목마다 누가 내는지' 변경안으로 바꾼다. (status, message, changes)"""
    if checked.status != "PARSED":
        return checked.status, checked.message, []
    order = {i: n for n, (i, _) in enumerate(room.members)}
    items = {it.id: it for it in room.items}
    changes = []
    for p in checked.proposals:
        it, t, prm = items[p["receipt_item_id"]], p["type"], p["params"]
        before = list(it.member_ids)
        if t == "FULL":
            after = [prm["member_id"]]
        elif t == "EQUAL":
            after = list(prm["member_ids"])
        else:  # EXCLUDE: 지금 체크된 사람에서 뺀다 (앞서 뺀 사람은 그대로 빠져 있다)
            after = [m for m in before if m not in prm["member_ids"]]
        after = sorted(set(after), key=order.__getitem__)
        if not after:
            return "NEEDS_CLARIFICATION", f"'{it.name}'을(를) 낼 사람이 아무도 남지 않아요. 누가 내는지 알려 주세요.", []
        if after == before:
            continue
        changes.append({"item_id": it.id, "receipt_id": it.receipt_id, "store_name": it.store_name,
                        "name": it.name, "rule": t, "evidence": p.get("evidence"),
                        "before_member_ids": before, "after_member_ids": after})
    if not changes:
        return "PARSED", "이미 체크 표에 그렇게 되어 있어요. 바꿀 것이 없습니다.", []
    return "PARSED", "체크 표를 이렇게 바꿀까요?", changes


def interpret(room: RoomData, text: str) -> dict[str, Any]:
    start = time.perf_counter()
    raw = call_model(room, text)
    elapsed_ms = int((time.perf_counter() - start) * 1000)
    status, message, changes = to_changes(validate(raw, text, room), room)
    return {"status": status, "message": message, "changes": changes,
            "provider": settings.nl_provider, "elapsed_ms": elapsed_ms}
