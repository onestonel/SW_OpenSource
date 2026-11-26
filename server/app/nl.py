"""문장 해석 — "D는 술 안 마셨어" 같은 문장을 체크 표 변경안으로 바꾼다 (V3 미리 연결).

흐름: 정산방 데이터 + 문장 → 해석기(llama.cpp 또는 stub) → 규칙 JSON → 서버 검사 → 체크 표 변경안.
변경안은 저장하지 않는다. 화면이 사용자에게 보여 주고, 적용하면 기존 체크 표 저장 API(PUT /checks)로 저장한다.

프롬프트 · JSON schema · 서버 검사는 llm/bench.py(PR #13, 11/4 노트북 시험 20문장 중 19개)와 같은 것을 쓴다.
V1 정산은 "체크한 사람끼리 똑같이"만 계산하므로, 규칙 중
EQUAL(~끼리만) · EXCLUDE(~빼고) · FULL(~가 다 낼게) · PAID(~는 이미 보냈어)만 반영한다.
WEIGHTED(비율) · QUANTITY(수량)는 안내만 한다.

PAID는 금액을 바꾼다. 모델은 누가 보냈는지만 알려 주고, 남은 금액은 서버가 계산한다 (모델은 돈 계산을 하지 않는다).
결제자와 이미 보낸 사람의 몫을 품목 금액에서 빼고, 아직 안 보낸 사람만 체크한다.
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from .core.config import settings
from .core.errors import AppError

log = logging.getLogger("settle.nl")

TYPES = ["EQUAL", "EXCLUDE", "FULL", "PAID", "WEIGHTED", "QUANTITY"]
CHECKABLE = {"EQUAL", "EXCLUDE", "FULL", "PAID"}

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
    "PAID": ({"member_ids": IDS}, ["member_ids"]),
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
  - PAID: 몇 명이 그 항목의 자기 몫을 결제한 사람에게 이미 보냈다 → params.member_ids (이미 보낸 사람). 금액은 계산하지 않는다
  - WEIGHTED: 비율로 나눔 → params.weights = [{member_id, weight}]
  - QUANTITY: 각자 먹은 수량 → params.quantities = [{member_id, quantity}], 수량 합이 항목 quantity와 같아야 한다
- 항목 · 사람 · 비율 · 수량 중 하나라도 문장만으로 정할 수 없으면 status="NEEDS_CLARIFICATION", proposals=[], clarification에 짧은 질문과 missing을 넣는다.
  질문은 빠진 것을 묻고, 답해 주면 무엇을 할지 덧붙인다. 예: "아침밥 메뉴가 무엇인가요? 알려 주시면 수아를 그 메뉴에서 뺄게요."
- 문장이 여러 개면 (앞의 질문에 이어서 답한 경우 포함) 모두 합쳐서 한 번에 해석한다.
- 정산과 관계없는 문장이면 status="UNSUPPORTED", proposals=[].
- 문장에 없는 사람 · 항목 · 숫자를 만들지 않는다.
- PARSED일 때 clarification은 null이다. evidence에는 근거가 된 문장 부분을 넣는다.
- 한 항목에는 규칙을 하나만 만든다. 수량은 한 규칙의 quantities에 모두 넣는다.

종류 고르는 법:
- "~만", "~끼리", "~둘이서/셋이서" → 말한 사람들만 낸다 → EQUAL (member_ids = 말한 사람들)
- "~빼고", "~는 안 먹었어/안 마셨어" → 말한 사람을 뺀다 → EXCLUDE (member_ids = 빠지는 사람들)
- "~가 전부/다 낼게" → FULL
- "~는 (항목) 보냈어/줬어/입금했어" → 이미 돈을 보낸 사람 → PAID (member_ids = 보낸 사람들)
- 데이터에 없는 말(예: "아침")로 항목을 가리켜서 어떤 항목인지 정할 수 없으면 NEEDS_CLARIFICATION
- "1:1:2", "두 배" 처럼 비율 숫자 → WEIGHTED
- "~인분", "~개" 처럼 각자 먹은 수량 → QUANTITY. 일부 사람의 수량만 나와서 합이 항목 quantity와 맞지 않으면 NEEDS_CLARIFICATION

예시 (데이터에 '커피'(id 900, quantity 1)가 있을 때):
문장: 커피는 A만 마셨어
답: {"status":"PARSED","proposals":[{"receipt_item_id":900,"type":"FULL","params":{"member_id":1},"evidence":"커피는 A만 마셨어"}],"clarification":null}
문장: B랑 C만 커피 마셨어
답: {"status":"PARSED","proposals":[{"receipt_item_id":900,"type":"EQUAL","params":{"member_ids":[2,3]},"evidence":"B랑 C만 커피 마셨어"}],"clarification":null}
문장: C는 커피 안 마셨어
답: {"status":"PARSED","proposals":[{"receipt_item_id":900,"type":"EXCLUDE","params":{"member_ids":[3]},"evidence":"C는 커피 안 마셨어"}],"clarification":null}
문장: B랑 C는 커피값 보냈어
답: {"status":"PARSED","proposals":[{"receipt_item_id":900,"type":"PAID","params":{"member_ids":[2,3]},"evidence":"B랑 C는 커피값 보냈어"}],"clarification":null}
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
    payer_id: int = 0  # 이 품목이 있는 영수증의 결제자


@dataclass
class RoomData:
    members: list[tuple[int, str]]  # (id, 이름), 구성원 순서
    items: list[Item]
    # 영수증별 '총액 − 품목 합' (할인 · 차액). 정산에서 그 영수증 참여자끼리 나눈다
    extra: dict[int, int] = field(default_factory=dict)
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


def _messages(room: RoomData, text: str) -> list[dict]:
    user = ("<데이터>\n" + json.dumps(room.context(), ensure_ascii=False)
            + "\n</데이터>\n<문장>\n" + text + "\n</문장>")
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


def _post_chat(base_url: str, body: dict, headers: dict | None = None, timeout: float = 60) -> str:
    """OpenAI 형식 /chat/completions에 보내고 답 글자를 받는다. llama.cpp와 OpenAI가 같은 형식이다."""
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]
    except (urllib.error.URLError, TimeoutError, OSError, KeyError, IndexError, ValueError) as exc:
        reason = type(exc).__name__
        if isinstance(exc, urllib.error.HTTPError):
            reason = f"HTTP {exc.code}"
        raise AppError(503, "NL_UNAVAILABLE",
                       "문장 해석기에 연결하지 못했습니다. 잠시 뒤 다시 시도하거나 체크 표에서 직접 바꿔 주세요.",
                       {"reason": reason}) from exc


def _call_llama(room: RoomData, text: str) -> str:
    body = {
        "messages": _messages(room, text),
        "temperature": 0,
        "max_tokens": 400,
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": "allocation_rules", "strict": True, "schema": SCHEMA}},
        "chat_template_kwargs": {"enable_thinking": False},
    }
    return _post_chat(settings.nl_base_url, body, timeout=settings.nl_timeout)


def _strict(schema: Any) -> Any:
    """OpenAI strict 모드에 맞춘 schema: 모든 칸을 required로, 지원하지 않는 minItems는 뺀다 (뜻은 같고 서버 검사가 다시 본다)."""
    if isinstance(schema, list):
        return [_strict(x) for x in schema]
    if not isinstance(schema, dict):
        return schema
    out = {k: _strict(v) for k, v in schema.items() if k != "minItems"}
    if "properties" in out:
        out["required"] = list(out["properties"])
    return out


def _call_fallback(room: RoomData, text: str) -> str:
    """큰 모델(OpenAI)에 같은 프롬프트 · 같은 출력 모양으로 다시 묻는다."""
    body = {
        "model": settings.nl_fallback_model,
        "messages": _messages(room, text),
        "temperature": 0,
        "max_completion_tokens": 400,
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": "allocation_rules", "strict": True, "schema": _strict(SCHEMA)}},
    }
    return _post_chat(settings.nl_fallback_base_url, body,
                      headers={"Authorization": f"Bearer {settings.nl_fallback_api_key}"}, timeout=30)


def fallback_enabled() -> bool:
    return bool(settings.nl_fallback_api_key)


def _call_stub(room: RoomData, text: str) -> str:
    """모델 없이 화면 · 테스트를 만들 때 쓰는 간단한 흉내. 실제 시연은 llama로 한다."""
    who = [i for i, n in room.members if n in text]
    what = [it for it in room.items if it.name in text]
    has = lambda *keys: any(k in text for k in keys)  # noqa: E731
    if who and not what:
        question = menu_question(text, room) or "어떤 품목인지 알려 주세요."
        return json.dumps({"status": "NEEDS_CLARIFICATION", "proposals": [],
                           "clarification": {"question": question, "missing": ["item"]}}, ensure_ascii=False)
    if not who or not what:
        return json.dumps({"status": "NEEDS_CLARIFICATION", "proposals": [],
                           "clarification": {"question": "어떤 품목을 누가 내는지 알려 주세요.",
                                             "missing": ["item", "member"]}}, ensure_ascii=False)
    if has("보냈", "줬", "입금", "송금"):
        rule = ("PAID", {"member_ids": [i for i in who if all(i != it.payer_id for it in what)] or who})
    elif has("전부", "다 낼", "다 내", "쏠게", "쏜다") and len(who) == 1:
        rule = ("FULL", {"member_id": who[0]})
    elif has("빼고", "안 먹", "안 마", "안먹", "안마"):
        rule = ("EXCLUDE", {"member_ids": who})
    elif has("만", "끼리"):
        rule = ("EQUAL", {"member_ids": who})
    else:
        return json.dumps({"status": "NEEDS_CLARIFICATION", "proposals": [], "clarification": None})
    proposals = [{"receipt_item_id": it.id, "type": rule[0], "params": rule[1], "evidence": text} for it in what]
    return json.dumps({"status": "PARSED", "proposals": proposals, "clarification": None}, ensure_ascii=False)


def call_fallback(room: RoomData, text: str) -> str:
    """큰 모델을 부른다. 테스트에서는 이 함수를 바꿔 끼운다."""
    return _call_fallback(room, text)


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
    follow_up: bool = False  # 진짜 질문이라 다음 말을 이 문장에 이어서 해석하면 되는지
    model_rules: list[str] = field(default_factory=list)  # 모델이 원래 고른 규칙 종류 (고치기 전)
    repairs: list[str] = field(default_factory=list)  # 서버가 고친 것


def _clarify(question: str | None = None, follow_up: bool = False) -> Checked:
    """follow_up=True는 빠진 것(메뉴 · 사람)을 묻는 진짜 질문이라 답을 앞 문장에 이어 붙이면 되는 경우다.
    "다시 말해 주세요" 같은 안내는 False라서, 사용자가 다음에 하는 말은 새 문장으로 해석한다."""
    return Checked("NEEDS_CLARIFICATION", [], question or ASK_AGAIN, follow_up=follow_up)


WHICH = re.compile(r"(\S+?)(?:은|는|을|를|도)?\s+안\s*(?:먹|마)")


def menu_question(text: str, room: RoomData) -> str | None:
    """"수아는 아침 안 먹었어"처럼 사람은 있는데 품목이 없으면, 무엇을 물을지와 답하면 무엇을 할지 같이 묻는다.

    예: "아침 메뉴가 무엇인가요? 알려 주시면 수아를 그 메뉴에서 뺄게요."
    """
    names = [n for _, n in room.members if n in text]
    if not names or not any(k in text for k in ("안 먹", "안 마", "안먹", "안마")):
        return None
    m = WHICH.search(text)
    word = m.group(1) if m and not any(n in m.group(1) for n in names) else None
    who = _josa(", ".join(names), "을", "를")
    return f"{word + ' 메뉴가 무엇인가요' if word else '어떤 메뉴인가요'}? 알려 주시면 {who} 그 메뉴에서 뺄게요."


def _item_names_in(text: str, room: RoomData) -> set[str]:
    """문장에 나온 품목 이름. 긴 이름부터 찾고 지워서, '아이스커피'만 말하면 그 안의 '커피'는 나온 것으로 보지 않는다."""
    left, found = text, set()
    for name in sorted({it.name for it in room.items}, key=len, reverse=True):
        if name in left:
            found.add(name)
            left = left.replace(name, "\0")
    return found


ONLY = re.compile(r"(만|끼리)\s*(먹|마시|마셨|탔|타|했|하|썼|쓰|갔|가|샀|사|시켰|이용|$)")
NOT = ("안 ", "안먹", "안마", "안탔", "안 탔", "빼고", "빼줘", "빼 줘", "제외", "못 ")


def _repair(p: dict, text: str, room: RoomData, used: set[int]) -> tuple[dict, list[str]]:
    """작은 모델이 자주 하는 실수를 문장에 근거해서만 고친다 (11/18 실제 EXAONE 시험에서 본 실수).

    - "~만 탔어"를 빼기(EXCLUDE)로, "~ 안 먹었어"를 끼리만(EQUAL)으로 거꾸로 고른 경우 → 문장 표현대로 바꾼다
    - 품목 · 사람 번호를 틀리게 낸 경우 → 문장에 이름이 그대로 나온 품목 · 사람으로 바꾼다
    문장에 근거가 없으면 고치지 않고, 뒤의 검사에서 다시 묻기로 간다.
    """
    p = {**p, "params": dict(p.get("params") or {})}
    fixed: list[str] = []  # 무엇을 고쳤는지 (기록 · 집계용)
    items = {it.id: it for it in room.items}
    said = _item_names_in(text, room)
    named_items = [it.id for it in room.items if it.name in said and it.id not in used]
    named_people = [i for i, n in room.members if n in text]
    item = p.get("receipt_item_id")
    if (item not in items or items[item].name not in said) and len(named_items) == 1:
        p["receipt_item_id"] = named_items[0]
        fixed.append("품목")
    t = p.get("type")
    only, neg = bool(ONLY.search(text)), any(k in text for k in NOT)
    if t == "EXCLUDE" and only and not neg:
        p["type"] = "EQUAL"
        fixed.append("EXCLUDE→EQUAL")
    elif t == "EQUAL" and neg and not only:
        p["type"] = "EXCLUDE"
        fixed.append("EQUAL→EXCLUDE")
    t = p["type"]
    if t in ("EQUAL", "EXCLUDE", "PAID"):
        ids = p["params"].get("member_ids")
        bad = not isinstance(ids, list) or not ids or any(i not in room.names or room.names[i] not in text for i in ids)
        if bad and named_people:
            p["params"]["member_ids"] = named_people
            fixed.append("사람")
    elif t == "FULL":
        mid = p["params"].get("member_id")
        if (mid not in room.names or room.names[mid] not in text) and len(named_people) == 1:
            p["params"]["member_id"] = named_people[0]
            fixed.append("사람")
    return p, fixed


def validate(raw: str, text: str, room: RoomData) -> Checked:
    """모델 답을 검사한다. 고칠 수 있으면 고치고, 아니면 다시 묻기로 바꾼다."""
    try:
        result = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return _clarify()
    if not isinstance(result, dict) or result.get("status") not in ("PARSED", "NEEDS_CLARIFICATION", "UNSUPPORTED"):
        return _clarify()
    if result["status"] == "UNSUPPORTED":
        return Checked("UNSUPPORTED", [], "정산과 관계없는 문장 같아요. 누가 어떤 품목을 내는지 말해 주세요.",
                       model_rules=["UNSUPPORTED"])
    if result["status"] == "NEEDS_CLARIFICATION":
        question = (result.get("clarification") or {}).get("question")
        # 사람과 "안 먹었어"가 있으면, 답하면 무엇을 할지까지 말하는 질문으로 바꾼다 (모델 질문은 짧고 매번 다르다)
        question = menu_question(text, room) or question
        real = isinstance(question, str) and bool(question.strip())
        c = _clarify(question if real else None, follow_up=real)
        c.model_rules = ["NEEDS_CLARIFICATION"]
        return c

    proposals = [p for p in (result.get("proposals") or []) if isinstance(p, dict)]
    model_rules = [str(p.get("type")) for p in proposals]
    repairs: list[str] = []
    checked = _check_parsed(result, text, room, repairs)
    checked.model_rules, checked.repairs = model_rules, repairs
    return checked


def _check_parsed(result: dict, text: str, room: RoomData, repairs: list[str]) -> Checked:
    items = {it.id: it for it in room.items}
    member_ids = [i for i, _ in room.members]
    said = _item_names_in(text, room)
    merged: dict[int, dict] = {}
    for p in result.get("proposals") or []:
        if not isinstance(p, dict):
            return _clarify()
        p, fixed = _repair(p, text, room, set(merged))
        repairs += fixed
        item, rule_type, params = p.get("receipt_item_id"), p.get("type"), p.get("params") or {}
        if item not in items or rule_type not in PARAMS:
            return _clarify()
        keys, _ = PARAMS[rule_type]
        params = {k: v for k, v in params.items() if k in keys}  # 종류에 맞지 않는 칸은 버린다
        if item in merged:
            # "현우랑 수아는 숙소비 보냈어, 민수만 보내면 돼"처럼 이미 보냄(PAID)과 그 결과(민수만)를 같이 말하면
            # 같은 품목에 규칙이 둘 나온다. 이미 보냄이 남은 사람을 이미 정하므로 이미 보냄만 남긴다
            kinds = {merged[item]["type"], rule_type}
            if "PAID" in kinds and kinds <= {"PAID", "FULL", "EQUAL"}:
                if rule_type == "PAID":
                    merged[item] = {"receipt_item_id": item, "type": rule_type, "params": params,
                                    "evidence": p.get("evidence") if isinstance(p.get("evidence"), str) else None}
                repairs.append("규칙 2개 합침")
                continue
            return _clarify()  # 같은 품목에 서로 다른 규칙 2개
        merged[item] = {"receipt_item_id": item, "type": rule_type, "params": params,
                        "evidence": p.get("evidence") if isinstance(p.get("evidence"), str) else None}
    if not merged:
        return _clarify()

    # "해장국이랑 김밥"처럼 문장에 품목 여러 개가 나왔는데 모델이 그중 일부에만 규칙을 냈고(11/19 실제 EXAONE),
    # 낸 규칙이 모두 같은 하나라면, 문장에 이름이 나온 나머지 품목에도 같은 규칙을 적용한다
    rules = {(p["type"], json.dumps(p["params"], sort_keys=True)) for p in merged.values()}
    if len(rules) == 1 and next(iter(rules))[0] in CHECKABLE:
        one = next(iter(merged.values()))
        for it in room.items:
            if it.name in said and it.id not in merged:
                merged[it.id] = {**one, "receipt_item_id": it.id, "params": dict(one["params"])}
                repairs.append("빠진 품목 추가")

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
        if items[item].name not in said:
            q = menu_question(text, room)
            return _clarify(q, follow_up=True) if q else _clarify(
                "문장에 나온 품목을 찾지 못했어요. 체크 표의 품목 이름을 그대로 써 주세요.")
    return Checked("PARSED", list(merged.values()), "")


# ------------------------------------------------------------------ 규칙 → 체크 표 변경안

RULE_NOTE = {"EXCLUDE": "빼기", "FULL": "한 명이 다 내기", "EQUAL": "~끼리만", "PAID": "이미 보낸 돈 빼기"}


def _josa(name: str, with_batchim: str, without: str) -> str:
    """이름 끝 글자에 받침이 있으면 with_batchim(을 · 은 · 이), 없으면 without(를 · 는 · 가)."""
    last = name[-1] if name else ""
    has = "가" <= last <= "힣" and (ord(last) - 0xAC00) % 28 != 0
    return name + (with_batchim if has else without)


def _paid_change(it: Item, paid_ids: list[int], room: RoomData) -> tuple[dict | None, str | None]:
    """이미 보낸 사람 몫을 빼고 남은 금액 · 체크를 계산한다. (변경안, 막힌 이유)"""
    from .engine import Member, split_equal

    order = {i: n for n, (i, _) in enumerate(room.members)}
    before = list(it.member_ids)
    done = set(paid_ids) | {it.payer_id}  # 결제한 사람은 자기 몫을 이미 낸 셈이다
    left = [m for m in before if m not in done]
    if not left:
        return None, f"'{it.name}'은(는) 체크된 사람이 모두 이미 냈어요. 바꿀 것이 없습니다."
    shares = split_equal(it.amount, [Member(m, room.names[m], order[m]) for m in before])
    after_amount = sum(shares[m] for m in left)
    sent = [m for m in before if m in done and m != it.payer_id]
    sent_names = ", ".join(room.names[m] for m in sent)
    left_names = ", ".join(room.names[m] for m in left)
    payer = room.names.get(it.payer_id, "결제자")
    note = (f"{_josa(sent_names, '은', '는')} 이미 {payer}에게 보냈으니, "
            if sent else f"{_josa(payer, '이', '가')} 결제했으니, ")
    note += f"{it.name} {it.amount:,}원 중 {left_names} 몫 {after_amount:,}원만 남기고 {left_names}만 체크할게요."
    return {"before_amount": it.amount, "after_amount": after_amount, "after_member_ids": left, "note": note}, None


def _paid_moves_extra(changes: list[dict], room: RoomData) -> str | None:
    """이미 보냄은 품목 금액을 줄이고 결제자 · 보낸 사람을 뺀다. 그래서 그 사람들이 영수증의 모든 품목에서 빠지면
    할인 · 차액(총액 − 품목 합)을 남은 사람끼리만 나누게 된다. 그런 영수증이면 막는다. (막힌 이유, 아니면 None)"""
    paid = {c["item_id"]: c["after_member_ids"] for c in changes if c["rule"] == "PAID"}
    for rid in dict.fromkeys(c["receipt_id"] for c in changes if c["rule"] == "PAID"):
        if not room.extra.get(rid):
            continue
        its = [it for it in room.items if it.receipt_id == rid]
        before = {m for it in its for m in it.member_ids}
        after = {m for it in its for m in paid.get(it.id, it.member_ids)}
        if after != before:
            return (f"'{its[0].store_name}' 영수증에는 할인이나 품목 합과 총액의 차이가 있어서, 이미 보낸 돈을 빼면 "
                    "그 금액을 남은 사람끼리만 나누게 돼요. 이 영수증은 아직 '이미 보냄'을 반영할 수 없어요.")
    return None


def to_changes(checked: Checked, room: RoomData) -> tuple[str, str, list[dict]]:
    """검사를 통과한 규칙을 '품목마다 누가 내는지(+ 금액)' 변경안으로 바꾼다. (status, message, changes)"""
    if checked.status != "PARSED":
        return checked.status, checked.message, []
    order = {i: n for n, (i, _) in enumerate(room.members)}
    items = {it.id: it for it in room.items}
    changes = []
    for p in checked.proposals:
        it, t, prm = items[p["receipt_item_id"]], p["type"], p["params"]
        before = list(it.member_ids)
        extra: dict[str, Any] = {"before_amount": it.amount, "after_amount": it.amount, "note": None}
        if t == "PAID":
            paid, blocked = _paid_change(it, list(prm["member_ids"]), room)
            if blocked:
                return "PARSED", blocked, []
            after = paid.pop("after_member_ids")
            extra = paid
        elif t == "FULL":
            after = [prm["member_id"]]
        elif t == "EQUAL":
            after = list(prm["member_ids"])
        else:  # EXCLUDE: 지금 체크된 사람에서 뺀다 (앞서 뺀 사람은 그대로 빠져 있다)
            after = [m for m in before if m not in prm["member_ids"]]
        after = sorted(set(after), key=order.__getitem__)
        if not after:
            checked.follow_up = True
            return "NEEDS_CLARIFICATION", f"'{it.name}'을(를) 낼 사람이 아무도 남지 않아요. 누가 내는지 알려 주세요.", []
        if after == before and extra["after_amount"] == it.amount:
            continue
        changes.append({"item_id": it.id, "receipt_id": it.receipt_id, "store_name": it.store_name,
                        "name": it.name, "rule": t, "evidence": p.get("evidence"),
                        "before_member_ids": before, "after_member_ids": after, **extra})
    blocked = _paid_moves_extra(changes, room)
    if blocked:
        return "PARSED", blocked, []
    if not changes:
        return "PARSED", "이미 체크 표에 그렇게 되어 있어요. 바꿀 것이 없습니다.", []
    return "PARSED", "이렇게 바꿀까요?", changes


def interpret(room: RoomData, text: str, previous: str | None = None) -> dict[str, Any]:
    """previous가 있으면 앞 문장(되물은 질문 전에 한 말)에 이어서 답한 것으로 보고 합쳐서 해석한다."""
    full = f"{previous.strip()} {text.strip()}" if previous and previous.strip() else text.strip()
    start = time.perf_counter()
    provider = settings.nl_provider
    small_down = False
    try:
        raw = call_model(room, full)
        checked = validate(raw, full, room)
    except AppError:
        if not fallback_enabled():
            raise
        small_down = True
        raw, checked = "(작은 모델에 연결하지 못함)", _clarify()
    log.info("문장 해석 provider=%s text=%r raw=%s", provider, full, raw)
    # 작은 모델 답이 서버 검사에서 걸렸으면(빠진 것을 묻는 진짜 질문이 아닌 다시 묻기) 큰 모델에 한 번 더 묻는다
    if fallback_enabled() and checked.status == "NEEDS_CLARIFICATION" and not checked.follow_up:
        small = checked
        try:
            raw2 = call_fallback(room, full)
        except AppError:
            if small_down:
                raise  # 두 모델 모두 연결하지 못함 → 503
            # 큰 모델이 안 되면 작은 모델의 다시 묻기를 그대로 돌려준다 (503이면 AI 총무 전체가 꺼진 것처럼 보인다)
            log.warning("큰 모델에 연결하지 못해 작은 모델 답을 그대로 씀 text=%r", full)
            checked.repairs = [*checked.repairs, "큰 모델 연결 실패"]
        else:
            log.info("문장 해석 provider=openai(%s) text=%r raw=%s", settings.nl_fallback_model, full, raw2)
            checked = validate(raw2, full, room)
            checked.repairs = [*small.repairs, "큰 모델로 넘김", *checked.repairs]
            checked.model_rules = small.model_rules  # 규칙 표는 기본 모델이 고른 것 × 최종 (넘겨서 고친 것이 보이게)
            raw = f"{raw}\n--- {settings.nl_fallback_model} ---\n{raw2}"
            provider = f"{provider}→openai"
    elapsed_ms = int((time.perf_counter() - start) * 1000)
    status, message, changes = to_changes(checked, room)
    trace = {"raw": raw, "model_rules": checked.model_rules, "repairs": checked.repairs,
             "final_rules": [p["type"] for p in checked.proposals] if checked.status == "PARSED" else [checked.status]}
    return {"status": status, "message": message, "changes": changes, "text": full,
            "follow_up": status == "NEEDS_CLARIFICATION" and checked.follow_up,
            "provider": provider, "elapsed_ms": elapsed_ms, "trace": trace}
