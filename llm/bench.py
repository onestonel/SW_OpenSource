"""자연어 분담 조건 → 규칙 JSON 해석을 시험하는 도구.

llama.cpp 서버(llama-server)나 OpenAI 형식 API에 평가 문장을 보내고,
정답과 비교해 맞힌 개수와 응답 시간을 표로 출력한다.
파이썬 기본 라이브러리만 쓰므로 따로 설치할 것이 없다.

    python bench.py --base-url http://localhost:8080/v1 --out results.md
"""

import argparse
import json
import statistics
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent

# 해석기에 넘기는 정산방 데이터 (백엔드 명세의 해석기 입력 형식)
CONTEXT = {
    "members": [
        {"id": 1, "name": "A"},
        {"id": 2, "name": "B"},
        {"id": 3, "name": "C"},
        {"id": 4, "name": "D"},
    ],
    "items": [
        {"id": 101, "name": "김치찌개", "quantity": 1, "amount": 10000, "receipt_title": "1차 식당"},
        {"id": 102, "name": "고기", "quantity": 4, "amount": 50000, "receipt_title": "1차 식당"},
        {"id": 103, "name": "할인", "quantity": 1, "amount": -5000, "receipt_title": "1차 식당"},
        {"id": 201, "name": "술", "quantity": 1, "amount": 100000, "receipt_title": "2차 술집"},
        {"id": 301, "name": "택시", "quantity": 1, "amount": 20000, "receipt_title": "택시"},
    ],
}

TYPES = ["EQUAL", "EXCLUDE", "FULL", "WEIGHTED", "QUANTITY"]

# 출력 모양을 고정하는 JSON schema (llama.cpp는 이 모양 밖의 글자를 만들 수 없다)
# 규칙 종류마다 넣을 수 있는 칸을 따로 정해서, 작은 모델이 칸을 섞지 못하게 한다.
INT = {"type": "integer"}
IDS = {"type": "array", "items": INT, "minItems": 1}


def pairs(key):
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
    "WEIGHTED": ({"weights": pairs("weight")}, ["weights"]),
    "QUANTITY": ({"quantities": pairs("quantity")}, ["quantities"]),
}


def proposal_schema(rule_type):
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
        "proposals": {"type": "array", "items": {"anyOf": [proposal_schema(t) for t in TYPES]}},
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


def build_messages(text):
    user = (
        "<데이터>\n"
        + json.dumps(CONTEXT, ensure_ascii=False)
        + "\n</데이터>\n<문장>\n"
        + text
        + "\n</문장>"
    )
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


def call(args, text):
    body = {
        "messages": build_messages(text),
        "temperature": 0,
        "max_tokens": 400,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "allocation_rules", "strict": True, "schema": SCHEMA},
        },
    }
    if args.model:
        body["model"] = args.model
    if not args.plain_openai:
        # Qwen3처럼 '생각 모드'가 있는 모델이 생각 글을 쓰지 않게 끈다 (llama.cpp 전용 옵션)
        body["chat_template_kwargs"] = {"enable_thinking": False}
    headers = {"Content-Type": "application/json"}
    if args.api_key:
        headers["Authorization"] = f"Bearer {args.api_key}"
    req = urllib.request.Request(
        args.base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    start = time.perf_counter()
    with urllib.request.urlopen(req, timeout=args.timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    elapsed = time.perf_counter() - start
    content = data["choices"][0]["message"]["content"]
    return content, elapsed


MEMBER_IDS = [m["id"] for m in CONTEXT["members"]]
ITEMS = {i["id"]: i for i in CONTEXT["items"]}
CLARIFY = {"status": "NEEDS_CLARIFICATION", "proposals": [], "clarification": {"question": "(서버 검사)", "missing": []}}


def validate(result):
    """백엔드가 모델 답을 받은 뒤 하는 검사. 고칠 수 있으면 고치고, 아니면 다시 묻기로 바꾼다."""
    if not isinstance(result, dict) or result.get("status") not in ("PARSED", "NEEDS_CLARIFICATION", "UNSUPPORTED"):
        return dict(CLARIFY), "모양 오류"
    if result["status"] != "PARSED":
        return {"status": result["status"], "proposals": [], "clarification": result.get("clarification")}, ""
    merged, notes = {}, []
    for p in result.get("proposals") or []:
        item, rule_type, params = p.get("receipt_item_id"), p.get("type"), p.get("params") or {}
        if item not in ITEMS or rule_type not in PARAMS:
            return dict(CLARIFY), "없는 항목 · 종류"
        keys, _ = PARAMS[rule_type]
        params = {k: v for k, v in params.items() if k in keys}  # 종류에 맞지 않는 칸은 버린다
        if rule_type == "QUANTITY":
            params["quantities"] = [q for q in params.get("quantities", []) if q.get("quantity", 0) > 0]
        if item in merged:
            prev = merged[item]
            if rule_type == prev["type"] == "QUANTITY":  # 같은 항목 수량이 여러 줄이면 합친다
                prev["params"]["quantities"] += params["quantities"]
                notes.append("수량 합침")
                continue
            return dict(CLARIFY), "같은 항목 규칙 2개"
        merged[item] = {"receipt_item_id": item, "type": rule_type, "params": params}
    if not merged:
        return dict(CLARIFY), "규칙 없음"
    for item, p in merged.items():
        t, prm = p["type"], p["params"]
        ids = []
        if t in ("EQUAL", "EXCLUDE"):
            ids = prm.get("member_ids") or []
        elif t == "FULL":
            ids = [prm.get("member_id")]
        else:
            key = "weights" if t == "WEIGHTED" else "quantities"
            ids = [x["member_id"] for x in prm.get(key) or []]
            if len(ids) != len(set(ids)):
                return dict(CLARIFY), "같은 사람 두 번"
        if not ids or any(i not in MEMBER_IDS for i in ids):
            return dict(CLARIFY), "없는 사람"
        if t == "EXCLUDE" and len(set(MEMBER_IDS) - set(ids)) == 0:
            return dict(CLARIFY), "모두 빠짐"
        if t == "WEIGHTED" and any(not 1 <= w["weight"] <= 100 for w in prm["weights"]):
            return dict(CLARIFY), "비율 범위"
        if t == "QUANTITY" and sum(q["quantity"] for q in prm["quantities"]) != ITEMS[item]["quantity"]:
            return dict(CLARIFY), "수량 합 불일치"
    return {"status": "PARSED", "proposals": list(merged.values()), "clarification": None}, ", ".join(notes)


def effect(rule_type, params):
    """규칙이 실제로 만드는 '사람별 몫 비율'. 표현이 달라도 돈이 같으면 같다고 본다."""
    from fractions import Fraction

    if rule_type == "EQUAL":
        w = {m: 1 for m in params.get("member_ids") or []}
    elif rule_type == "EXCLUDE":
        w = {m: 1 for m in MEMBER_IDS if m not in (params.get("member_ids") or [])}
    elif rule_type == "FULL":
        w = {params.get("member_id"): 1}
    elif rule_type == "WEIGHTED":
        w = {x["member_id"]: x["weight"] for x in params.get("weights") or []}
    else:
        w = {x["member_id"]: x["quantity"] for x in params.get("quantities") or []}
    total = sum(w.values())
    return tuple(sorted((m, Fraction(v, total)) for m, v in w.items() if v)) if total else ()


def normalize(result):
    status = result.get("status")
    if status != "PARSED":
        return (status,)
    rules = {}
    for p in result.get("proposals") or []:
        rules.setdefault(p["receipt_item_id"], []).append(effect(p["type"], p.get("params") or {}))
    return (status, tuple(sorted((k, tuple(sorted(v))) for k, v in rules.items())))


def judge(expected, content):
    """모델 답 그대로(raw)와 서버 검사를 거친 뒤(final)를 따로 채점한다."""
    try:
        got = json.loads(content)
    except json.JSONDecodeError:
        return "형식 오류", "형식 오류", None, None, ""
    try:
        raw = "맞음" if normalize(got) == normalize(expected) else "틀림"
    except (KeyError, TypeError, AttributeError):
        raw = "틀림"
    fixed, note = validate(got)
    final = "맞음" if normalize(fixed) == normalize(expected) else "틀림"
    return raw, final, got, fixed, note


def short(obj):
    if obj is None:
        return "-"
    if obj.get("status") != "PARSED":
        return obj.get("status", "-")
    parts = []
    for p in obj.get("proposals") or []:
        parts.append(f"{p.get('receipt_item_id')} {p.get('type')} {json.dumps(p.get('params'), ensure_ascii=False)}")
    return " / ".join(parts) or "PARSED (비어 있음)"


def main():
    parser = argparse.ArgumentParser(description="분담 조건 해석 시험")
    parser.add_argument("--base-url", default="http://localhost:8080/v1", help="OpenAI 형식 API 주소")
    parser.add_argument("--model", default="", help="모델 이름 (llama.cpp는 비워도 됨)")
    parser.add_argument("--api-key", default="", help="외부 API 키 (llama.cpp는 비워도 됨)")
    parser.add_argument("--plain-openai", action="store_true", help="llama.cpp 전용 옵션을 빼고 보냄 (외부 API용)")
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--sentences", default=str(HERE / "eval_sentences.jsonl"))
    parser.add_argument("--out", default="", help="결과 표를 저장할 .md 파일")
    args = parser.parse_args()

    cases = [json.loads(line) for line in Path(args.sentences).read_text(encoding="utf-8").splitlines() if line.strip()]
    rows, times = [], []
    for case in cases:
        case.setdefault("set", "tuning")
        try:
            content, elapsed = call(args, case["text"])
        except (urllib.error.URLError, TimeoutError, KeyError) as e:
            print(f"[{case['id']}] 서버 호출 실패: {e}", file=sys.stderr)
            rows.append((case, "호출 실패", "호출 실패", None, None, "", None))
            continue
        raw, final, got, fixed, note = judge(case["expected"], content)
        times.append(elapsed)
        rows.append((case, raw, final, got, fixed, note, elapsed))
        print(f"[{case['id']:>2}] 모델 {raw:<5} 검사 후 {final:<5} {elapsed:5.1f}초  {case['text']}")

    lines = [
        f"모델: {args.model or '(서버 기본 모델)'} · 주소: {args.base_url}",
        "",
        "| # | 세트 | 문장 | 기대 | 모델 답 | 모델 | 검사 후 | 시간(초) |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for case, raw, final, got, fixed, note, elapsed in rows:
        t = f"{elapsed:.1f}" if elapsed is not None else "-"
        fin = final + (f" ({note})" if note else "")
        lines.append(
            f"| {case['id']} | {case['set']} | {case['text']} | {short(case['expected'])} | {short(got)} | {raw} | {fin} | {t} |"
        )
    avg = statistics.mean(times) if times else 0
    mx = max(times) if times else 0
    lines.append("")
    for name in ("tuning", "holdout"):
        part = [r for r in rows if r[0]["set"] == name]
        if part:
            r_ok = sum(r[1] == "맞음" for r in part)
            f_ok = sum(r[2] == "맞음" for r in part)
            label = "프롬프트 고칠 때 본 문장" if name == "tuning" else "처음 보는 문장"
            lines.append(f"- {label}({name}): 모델 {r_ok}/{len(part)} · 검사 후 {f_ok}/{len(part)}")
    total_final = sum(r[2] == "맞음" for r in rows)
    lines.append(f"- 전체 검사 후 {total_final}/{len(rows)} · 평균 {avg:.1f}초 · 최대 {mx:.1f}초")
    passed = total_final >= 0.8 * len(rows) and avg <= 15
    lines.append(f"\n**판정 기준(검사 후 80% 이상 · 평균 15초 이하): {'통과' if passed else '미달'}**")
    report = "\n".join(lines)
    print("\n" + report)
    if args.out:
        Path(args.out).write_text(report + "\n", encoding="utf-8")
        print(f"\n저장: {args.out}")


if __name__ == "__main__":
    main()
