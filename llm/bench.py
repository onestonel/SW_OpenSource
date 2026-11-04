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
SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["PARSED", "NEEDS_CLARIFICATION", "UNSUPPORTED"]},
        "proposals": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "receipt_item_id": {"type": "integer"},
                    "type": {"type": "string", "enum": TYPES},
                    "params": {
                        "type": "object",
                        "properties": {
                            "member_ids": {"type": "array", "items": {"type": "integer"}},
                            "member_id": {"type": "integer"},
                            "weights": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "member_id": {"type": "integer"},
                                        "weight": {"type": "integer"},
                                    },
                                    "required": ["member_id", "weight"],
                                },
                            },
                            "quantities": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "member_id": {"type": "integer"},
                                        "quantity": {"type": "integer"},
                                    },
                                    "required": ["member_id", "quantity"],
                                },
                            },
                        },
                        "additionalProperties": False,
                    },
                    "evidence": {"type": "string"},
                },
                "required": ["receipt_item_id", "type", "params"],
            },
        },
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
                },
            ]
        },
    },
    "required": ["status", "proposals", "clarification"],
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

예시 (데이터에 '커피'(id 900)가 있을 때):
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


def normalize_params(rule_type, params):
    if rule_type in ("EQUAL", "EXCLUDE"):
        return ("ids", tuple(sorted(params.get("member_ids") or [])))
    if rule_type == "FULL":
        return ("id", params.get("member_id"))
    if rule_type == "WEIGHTED":
        return ("w", tuple(sorted((w["member_id"], w["weight"]) for w in params.get("weights") or [])))
    if rule_type == "QUANTITY":
        return ("q", tuple(sorted((q["member_id"], q["quantity"]) for q in params.get("quantities") or [])))
    return ("?", None)


def normalize(result):
    status = result.get("status")
    if status != "PARSED":
        return (status,)
    rules = sorted(
        (p["receipt_item_id"], p["type"], normalize_params(p["type"], p.get("params") or {}))
        for p in result.get("proposals") or []
    )
    return (status, tuple(rules))


def judge(expected, content):
    try:
        got = json.loads(content)
    except json.JSONDecodeError:
        return "형식 오류", None
    try:
        ok = normalize(got) == normalize(expected)
    except (KeyError, TypeError):
        return "형식 오류", got
    return ("맞음" if ok else "틀림"), got


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
    rows, times, correct = [], [], 0
    for case in cases:
        try:
            content, elapsed = call(args, case["text"])
        except (urllib.error.URLError, TimeoutError, KeyError) as e:
            print(f"[{case['id']}] 서버 호출 실패: {e}", file=sys.stderr)
            rows.append((case, "호출 실패", None, None))
            continue
        verdict, got = judge(case["expected"], content)
        correct += verdict == "맞음"
        times.append(elapsed)
        rows.append((case, verdict, got, elapsed))
        print(f"[{case['id']:>2}] {verdict:<5} {elapsed:5.1f}초  {case['text']}")

    lines = [
        f"모델: {args.model or '(서버 기본 모델)'} · 주소: {args.base_url}",
        "",
        "| # | 문장 | 기대 | 결과 | 판정 | 시간(초) |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for case, verdict, got, elapsed in rows:
        t = f"{elapsed:.1f}" if elapsed is not None else "-"
        lines.append(f"| {case['id']} | {case['text']} | {short(case['expected'])} | {short(got)} | {verdict} | {t} |")
    avg = statistics.mean(times) if times else 0
    mx = max(times) if times else 0
    lines += ["", f"**맞힌 개수 {correct}/{len(cases)} · 평균 {avg:.1f}초 · 최대 {mx:.1f}초**"]
    passed = correct >= 8 and avg <= 15
    lines.append(f"판정 기준(8개 이상 · 평균 15초 이하): {'통과' if passed else '미달'}")
    report = "\n".join(lines)
    print("\n" + report)
    if args.out:
        Path(args.out).write_text(report + "\n", encoding="utf-8")
        print(f"\n저장: {args.out}")


if __name__ == "__main__":
    main()
