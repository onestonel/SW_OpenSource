"""켜져 있는 서버에 새 영수증 흐름을 처음부터 끝까지 한 번 돌려 본다 (GitHub Actions compose-test가 쓴다).

docker compose로 서버와 DB를 켠 뒤 내 컴퓨터에서 실행해도 된다 (파이썬 기본 라이브러리만 쓴다):

    python server/scripts/smoke_test.py                       기본 주소 http://localhost:8000/api/v1
    python server/scripts/smoke_test.py http://localhost:8000/api/v1

정산방과 영수증을 새로 만들기 때문에, 돌릴 때마다 DB에 정산방이 하나씩 늘어난다.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

API = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000/api/v1"


def call(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(API + path, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            raw = res.read()
            return res.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def expect(step: str, got: tuple[int, dict], status: int, code: str | None = None) -> dict:
    got_status, body = got
    got_code = body.get("error", {}).get("code") if isinstance(body, dict) else None
    if got_status != status or (code and got_code != code):
        want = f"{status} {code or ''}".strip()
        print(f"실패: {step} (기대 {want}, 받은 값 {got_status} {got_code or ''})\n{json.dumps(body, ensure_ascii=False)}")
        sys.exit(1)
    print(f"통과: {step}")
    return body


def main() -> None:
    expect("서버 상태 확인", call("GET", "/health"), 200)

    room = expect("정산방 만들기", call("POST", "/rooms", {"name": "자동 테스트", "members": ["민지", "준호", "서연"]}), 201)
    t = room["room_token"]
    minji, junho, _ = (m["id"] for m in room["members"])

    # 새 영수증 흐름 1단계: 가게 이름과 결제자만 보낸다 (명세서 #45, 서버 #48)
    rc = expect("가게 이름과 결제자만으로 영수증 만들기",
                call("POST", f"/rooms/{t}/receipts", {"store_name": "1차 식당", "payer_member_id": minji}), 201)
    if rc["total_amount"] is not None or rc["items"]:
        print(f"실패: 새 영수증은 총액이 비어 있고 품목이 없어야 합니다\n{json.dumps(rc, ensure_ascii=False)}")
        sys.exit(1)
    rid = rc["id"]

    expect("같은 가게 이름은 409",
           call("POST", f"/rooms/{t}/receipts", {"store_name": "1차 식당", "payer_member_id": junho}),
           409, "STORE_NAME_DUPLICATE")
    expect("총액과 품목이 비면 확정 막기", call("POST", f"/rooms/{t}/receipts/{rid}/confirm"), 409, "RECEIPT_INCOMPLETE")

    # 사용자가 총액과 품목을 채운다 (실제로는 사진 읽기가 먼저 채우고 사용자가 고친다)
    expect("총액과 품목 채우기", call("PUT", f"/rooms/{t}/receipts/{rid}", {
        "store_name": "1차 식당", "payer_member_id": minji, "total_amount": 30000,
        "items": [{"name": "삼겹살", "amount": 24000, "kind": "ITEM"}, {"name": "콜라", "amount": 6000, "kind": "ITEM"}],
    }), 200)
    expect("확정", call("POST", f"/rooms/{t}/receipts/{rid}/confirm"), 200)

    result = expect("다시 계산", call("POST", f"/rooms/{t}/settlements"), 201)
    transfers = sorted((tr["from"]["name"], tr["to"]["name"], tr["amount"]) for tr in result["transfers"])
    want = [("서연", "민지", 10000), ("준호", "민지", 10000)]
    if transfers != want:
        print(f"실패: 송금 목록이 다릅니다 (기대 {want}, 받은 값 {transfers})")
        sys.exit(1)
    print("통과: 송금 목록 (준호 → 민지 10,000원, 서연 → 민지 10,000원)")


if __name__ == "__main__":
    main()
