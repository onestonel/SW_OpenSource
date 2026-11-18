"""두 LLM을 같은 문장으로 비교한다 (기본: EXAONE = llm, Gemma 4 = llm2).

서버 컨테이너 안에서 실행한다:
    docker compose exec server python scripts/compare_llm.py                   llm · llm2 비교
    docker compose exec server python scripts/compare_llm.py --thinking        llm2는 추론 모드를 켜고
    docker compose exec server python scripts/compare_llm.py --only llm2       하나만

프롬프트 · 출력 모양 · 서버 검사 · 서버 보정은 실제 앱과 같다 (app/nl.py). DB는 쓰지 않는다.
문장마다 처음 상태(영수증 5장, 모두 체크)에서 따로 해석한다. 되묻기 답은 앞 문장에 이어 붙인다.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import nl  # noqa: E402
from app.core.errors import AppError  # noqa: E402

MODELS = {"llm": "http://llm:8080/v1", "llm2": "http://llm2:8080/v1"}
MEMBERS = [(1, "민수"), (2, "지영"), (3, "현우"), (4, "수아")]
N = dict(MEMBERS)
ID = {v: k for k, v in N.items()}
RECEIPTS = [  # (영수증 id, 가게, 결제자, [(품목 id, 품목, 금액)])
    (10, "숙소", 2, [(101, "숙소비", 387000)]),
    (20, "항공권", 1, [(201, "항공권", 532400)]),
    (30, "해장국집", 1, [(301, "해장국", 34000), (302, "김밥", 9500)]),
    (40, "패러글라이딩", 1, [(401, "패러글라이딩", 238000)]),
    (50, "흑돼지집", 1, [(501, "흑돼지", 96000), (502, "술", 27000), (503, "공깃밥", 4000)]),
]
ALL = ["민수", "지영", "현우", "수아"]
# (문장, 앞 문장(되묻기 답일 때), 기대: {품목: (체크될 사람, 금액)} · "ASK"(되묻기) · "NOT"(변경 없음))
CASES = [
    ("현우랑 수아는 숙소비 지영이한테 보냈어", None, {"숙소비": (["민수"], 96750)}),
    ("패러글라이딩은 지영이랑 현우만 탔어", None, {"패러글라이딩": (["지영", "현우"], 238000)}),
    ("수아는 아침 안 먹었어", None, "ASK"),
    ("해장국이랑 김밥", "수아는 아침 안 먹었어", {"해장국": (["민수", "지영", "현우"], 34000),
                                         "김밥": (["민수", "지영", "현우"], 9500)}),
    ("현우는 술 안 마셨어", None, {"술": (["민수", "지영", "수아"], 27000)}),
    # 대본 밖
    ("현우랑 수아는 숙소비를 보냈어 민수만 보내면 돼", None, {"숙소비": (["민수"], 96750)}),
    ("흑돼지는 민수랑 지영이만 먹었어", None, {"흑돼지": (["민수", "지영"], 96000)}),
    ("공깃밥은 현우가 다 낼게", None, {"공깃밥": (["현우"], 4000)}),
    ("수아는 술 안 마셨고 현우는 김밥 안 먹었어", None, {"술": (["민수", "지영", "현우"], 27000),
                                               "김밥": (["민수", "지영", "수아"], 9500)}),
    ("오늘 날씨 좋다", None, "NOT"),
]


def room() -> nl.RoomData:
    items = [nl.Item(id=i, name=n, amount=a, receipt_id=r, store_name=s, member_ids=[1, 2, 3, 4], payer_id=p)
             for r, s, p, its in RECEIPTS for i, n, a in its]
    return nl.RoomData(members=MEMBERS, items=items)


def run(name: str, base_url: str, thinking: bool) -> tuple[int, list[float]]:
    def call(room_: nl.RoomData, text: str) -> str:
        body = {
            "messages": nl._messages(room_, text), "temperature": 0, "max_tokens": 2000 if thinking else 400,
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": "allocation_rules", "strict": True, "schema": nl.SCHEMA}},
            "chat_template_kwargs": {"enable_thinking": thinking},
        }
        return nl._post_chat(base_url, body, timeout=300)

    nl.call_model = call
    nl.fallback_enabled = lambda: False  # 모델끼리 비교하므로 GPT로 넘기지 않는다
    passed, times = 0, []
    print(f"\n== {name} ({base_url}){' · 추론 모드' if thinking else ''} ==")
    for text, previous, want in CASES:
        start = time.perf_counter()
        try:
            r = nl.interpret(room(), text, previous)
        except AppError as e:
            print(f"  연결 실패: {e.message} {e.details or ''}")
            return passed, times
        sec = time.perf_counter() - start
        times.append(sec)
        got = {c["name"]: ([N[m] for m in c["after_member_ids"]], c["after_amount"]) for c in r["changes"]}
        if want == "ASK":
            ok = r["status"] == "NEEDS_CLARIFICATION" and r["follow_up"]
        elif want == "NOT":
            ok = r["status"] != "PARSED" or not r["changes"]
        else:
            ok = r["status"] == "PARSED" and got == want
        passed += ok
        fixed = f"  [서버 보정: {', '.join(r['trace']['repairs'])}]" if r["trace"]["repairs"] else ""
        print(f"  {'통과' if ok else '실패'} {sec:5.1f}초  {text}{fixed}")
        if not ok:
            print(f"        AI: {r['message']}  {json.dumps(got, ensure_ascii=False)}")
            print(f"        모델 답: {r['trace']['raw'][:300]}")
    return passed, times


def main() -> None:
    only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None
    results = {}
    for name, url in MODELS.items():
        if only and name != only:
            continue
        results[name] = run(name, url, thinking=("--thinking" in sys.argv and name == "llm2"))
    print("\n== 요약 ==")
    for name, (passed, times) in results.items():
        avg = sum(times) / len(times) if times else 0
        print(f"  {name}: {passed}/{len(CASES)} 통과, 평균 {avg:.1f}초, 최대 {max(times, default=0):.1f}초")


if __name__ == "__main__":
    main()
