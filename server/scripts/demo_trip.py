"""중간발표 시연용 '제주 여행' 정산방을 만들고, AI 총무 대본을 시험한다.

서버 컨테이너 안에서 실행한다 (파이썬 기본 라이브러리만 쓴다):

    docker compose exec server python scripts/demo_trip.py          정산방 + 영수증 5장만 만들기 (영상 녹화용)
    docker compose exec server python scripts/demo_trip.py --check  대본 4문장을 AI에게 보내고 정답과 비교하기

--check는 실제로 반영하고 다시 계산까지 하므로, 녹화용 정산방은 옵션 없이 새로 만든다.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

API = "http://localhost:8000/api/v1"
WEB = "http://localhost:3000"

MEMBERS = ["민수", "지영", "현우", "수아"]  # 민수가 총무
RECEIPTS = [  # (가게, 결제자, [(품목, 금액)])
    ("숙소", "지영", [("숙소비", 387000)]),
    ("항공권", "민수", [("항공권", 532400)]),
    ("해장국집", "민수", [("해장국", 34000), ("김밥", 9500)]),
    ("패러글라이딩", "민수", [("패러글라이딩", 238000)]),
    ("흑돼지집", "민수", [("흑돼지", 96000), ("술", 27000), ("공깃밥", 4000)]),
]
# (AI에게 할 말, 기대하는 결과: 품목 → 체크될 사람 · 금액. None이면 AI가 되물어야 함)
SCRIPT = [
    ("현우랑 수아는 숙소비 지영이한테 보냈어", {"숙소비": (["민수"], 96750)}),
    ("패러글라이딩은 지영이랑 현우만 탔어", {"패러글라이딩": (["지영", "현우"], 238000)}),
    ("수아는 아침 안 먹었어", None),
    ("해장국이랑 김밥", {"해장국": (["민수", "지영", "현우"], 34000), "김밥": (["민수", "지영", "현우"], 9500)}),
    ("현우는 술 안 마셨어", {"술": (["민수", "지영", "수아"], 27000)}),
]
EXPECTED_TRANSFERS = [("지영", "민수", 203850), ("현우", "민수", 291599), ("수아", "민수", 167100)]


def call(method: str, path: str, body: dict | None = None, timeout: float = 120) -> dict | None:
    req = urllib.request.Request(API + path, method=method, headers={"Content-Type": "application/json"},
                                 data=json.dumps(body, ensure_ascii=False).encode("utf-8") if body else None)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            raw = res.read()
    except urllib.error.HTTPError as e:
        sys.exit(f"  서버 오류 {e.code}: {e.read().decode('utf-8', 'replace')}")
    return json.loads(raw) if raw else None


def make_room() -> tuple[str, dict[str, int]]:
    room = call("POST", "/rooms", {"name": "제주 여행", "members": MEMBERS})
    token = room["room_token"]
    ids = {m["name"]: m["id"] for m in room["members"]}
    for store, payer, items in RECEIPTS:
        r = call("POST", f"/rooms/{token}/receipts", {
            "store_name": store, "payer_member_id": ids[payer], "total_amount": sum(a for _, a in items),
            "items": [{"name": n, "amount": a} for n, a in items],
        })
        call("POST", f"/rooms/{token}/receipts/{r['id']}/confirm")
    return token, ids


def check(token: str, ids: dict[str, int]) -> bool:
    name = {v: k for k, v in ids.items()}
    ok = True
    previous = None
    for text, want in SCRIPT:
        start = time.perf_counter()
        body = {"text": text, **({"previous": previous} if previous else {})}
        r = call("POST", f"/rooms/{token}/checks/interpret", body)
        sec = time.perf_counter() - start
        got = {c["name"]: ([name[m] for m in c["after_member_ids"]], c["after_amount"]) for c in r["changes"]}
        if want is None:
            good = r["status"] == "NEEDS_CLARIFICATION"
            previous = r["text"] if good else None
        else:
            good = r["status"] == "PARSED" and got == want
            previous = None
        ok &= good
        print(f"{'통과' if good else '실패'}  {sec:4.1f}초  {text}")
        print(f"      AI: {r['message']}  (해석기: {r['provider']})")
        for c in r["changes"]:
            print(f"      - {c['name']}: {', '.join(name[m] for m in c['after_member_ids'])}"
                  f"{'' if c['after_amount'] == c['before_amount'] else f' · 금액 {c['after_amount']:,}원'}")
        if not good:
            print(f"      기대: {'되묻기' if want is None else want}")
        if good and r["changes"]:
            call("POST", f"/rooms/{token}/checks/apply", {"changes": [
                {"item_id": c["item_id"], "member_ids": c["after_member_ids"],
                 **({"amount": c["after_amount"]} if c["after_amount"] != c["before_amount"] else {})}
                for c in r["changes"]]})
    s = call("POST", f"/rooms/{token}/settlements")
    got = [(t["from"]["name"], t["to"]["name"], t["amount"]) for t in s["transfers"]]
    good = got == EXPECTED_TRANSFERS
    ok &= good
    print(f"\n{'통과' if good else '실패'}  정산 결과")
    for t in s["transfers"]:
        print(f"      {t['from']['name']} → {t['to']['name']} {t['amount']:,}원")
    if not good:
        print(f"      기대: {EXPECTED_TRANSFERS}")
    return ok


def main() -> None:
    token, ids = make_room()
    print(f"정산방을 만들었습니다: {WEB}/rooms/{token}")
    print(f"AI 총무 화면:          {WEB}/rooms/{token}/split\n")
    if "--check" in sys.argv:
        ok = check(token, ids)
        print("\n모두 통과했습니다." if ok else "\n실패한 문장이 있습니다. 위 결과를 보내 주세요.")
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
