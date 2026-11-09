# 같이정산 V1 API 명세서

화면(web)과 서버(server)가 **무엇을 보내고 무엇을 돌려받는지** 정한 문서입니다.
화면 담당은 이 문서대로 요청을 보내고, 서버 담당은 이 문서대로 답장을 돌려줍니다.
바꿀 일이 생기면 **코드보다 이 문서를 먼저 고치고**(PR), 서로 확인한 뒤 코드를 고칩니다.

- 기준: 노션 「V1 요구 명세 (11/4 확정)」
- 상태: **확정 (11/9)** — 리뷰 의견과 정한 것 7개를 반영했습니다 (맨 아래 「정한 것」 참고)

---

## 0. 공통 약속

| 항목 | 약속 |
| --- | --- |
| 주소 앞부분 | `http://localhost:8000/api/v1` (화면에서는 `VITE_API_BASE_URL`) |
| 데이터 형식 | 요청 · 답장 모두 JSON. 사진 올리기만 `multipart/form-data` |
| 이름 짓기 | `snake_case` (예: `payer_member_id`) |
| 금액 | 정수(원). 소수점 없음. 할인은 음수 |
| 날짜 · 시각 | ISO 8601, 한국 시간 (예: `2026-11-16T14:30:00+09:00`) |
| 로그인 | 없음. 정산방마다 추측하기 어려운 `room_token`이 주소에 들어가고, 이 주소를 아는 사람만 들어올 수 있음 |

### 오류 답장 형식

어떤 오류든 이 모양으로 돌려줍니다. 화면은 `code`로 경우를 나누고, `message`는 그대로 사용자에게 보여 줘도 됩니다.

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "결제자를 골라주세요.",
    "details": { "fields": { "payer_member_id": "필수" } }
  }
}
```

### 오류 코드

| HTTP | code | 언제 |
| --- | --- | --- |
| 404 | `NOT_FOUND` | 없는 정산방 · 영수증 · 구성원 (주소의 `room_token`이 틀린 경우 포함) |
| 409 | `RECEIPT_CONFIRMED` | 확정된 영수증을 고치거나 지우려 함 → 먼저 '확정 취소' |
| 409 | `RECEIPT_NOT_CONFIRMED` | 확인 중인 영수증을 '확정 취소'하려 함 |
| 409 | `MEMBER_IN_USE` | 결제자로 쓰인 구성원을 지우려 함 · 지우면 아무도 체크하지 않은 품목이 생김 |
| 409 | `MEMBER_NAME_DUPLICATE` | 같은 이름의 구성원을 추가하려 함 |
| 409 | `MEMBERS_TOO_FEW` | 지우면 구성원이 2명 미만이 됨 |
| 413 | `FILE_TOO_LARGE` | 사진이 10MB를 넘음 |
| 415 | `UNSUPPORTED_MEDIA_TYPE` | jpg · png가 아닌 파일 |
| 422 | `VALIDATION_ERROR` | 입력 검사 실패 (`details.fields`에 칸별 이유) |
| 422 | `CHECK_EMPTY` | 아무도 체크하지 않은 품목이 있음 |
| 422 | `NO_CONFIRMED_RECEIPTS` | 확정된 영수증 없이 '다시 계산' |
| 500 | `INTERNAL_ERROR` | 그 밖의 서버 오류 |

---

## 1. 상태 확인

| 주소 | 하는 일 | 답장 |
| --- | --- | --- |
| `GET /health` | 서버와 DB가 살아 있는지 | `200 {"status": "ok", "db": "ok"}` · DB가 꺼져 있으면 `503 {"status": "error", "db": "error"}` |

화면은 첫 화면에서 이 주소를 불러 "서버 연결됨"을 표시합니다 (Issue #7).

---

## 2. 정산방 · 구성원 (1단계)

| 주소 | 하는 일 |
| --- | --- |
| `POST /rooms` | 정산방 만들기 |
| `GET /rooms/{room_token}` | 정산방 정보 보기 |
| `PATCH /rooms/{room_token}` | 이름 · 원 단위 설정 바꾸기 |
| `POST /rooms/{room_token}/members` | 구성원 추가 |
| `DELETE /rooms/{room_token}/members/{member_id}` | 구성원 삭제 (아래 「구성원 삭제」 참고) |

### 정산방 만들기 `POST /rooms`

보내는 것:
```json
{
  "name": "제주 여행",
  "members": ["A", "B", "C", "D"],
  "rounding": "WON_1"
}
```

- `members`: 2명 이상, 빈 이름 · 같은 이름 없음 (같은 이름이면 `409 MEMBER_NAME_DUPLICATE`). **입력한 순서가 구성원 순서**이고, 나누고 남는 1원을 앞 사람부터 붙이는 순서로 씁니다
- `rounding`: `WON_1`(1원 단위, 기본) 또는 `WON_10`(10원 올림). 빼면 `WON_1`

받는 것 `201`:
```json
{
  "room_token": "k3Jx9QpL2vTz8mWb",
  "name": "제주 여행",
  "rounding": "WON_1",
  "members": [
    { "id": 1, "name": "A", "order": 1 },
    { "id": 2, "name": "B", "order": 2 },
    { "id": 3, "name": "C", "order": 3 },
    { "id": 4, "name": "D", "order": 4 }
  ],
  "created_at": "2026-11-16T14:00:00+09:00"
}
```

- `room_token`: 길이는 정해져 있지 않습니다 (지금 서버는 22자). 화면은 길이를 가정하지 말아 주세요
- `order`: 구성원을 지우면 1, 3, 4처럼 중간이 빌 수 있습니다. 화면은 정렬에만 쓰고 번호로 보여 주지 않습니다

화면은 `room_token`으로 정산방 주소(예: `http://localhost:3000/rooms/k3Jx9QpL2vTz8mWb`)를 만들어 "이 링크를 저장해 두세요"와 복사 버튼을 보여 줍니다.

### 정산방 정보 보기 `GET /rooms/{room_token}`

받는 것 `200`: 위와 같은 모양에 최신 정산 상태를 더합니다.
```json
{
  "room_token": "k3Jx9QpL2vTz8mWb",
  "name": "제주 여행",
  "rounding": "WON_1",
  "members": [ { "id": 1, "name": "A", "order": 1 } ],
  "latest_settlement": { "version": 3, "is_stale": false }
}
```
아직 한 번도 계산하지 않았으면 `"latest_settlement": null`.

### 이름 · 원 단위 바꾸기 `PATCH /rooms/{room_token}`

보내는 것: 바꿀 칸만 `{ "rounding": "WON_10" }` → 받는 것 `200`: 정산방 정보.
원 단위를 바꾸면 최신 정산은 '최신 아님'이 됩니다.

### 구성원 추가 `POST /rooms/{room_token}/members`

보내는 것 `{ "name": "E" }` → 받는 것 `201 { "id": 5, "name": "E", "order": 5 }`.
새 구성원은 이미 있는 품목 체크에는 들어가지 않습니다 (필요하면 체크 표에서 켬).
같은 이름이 이미 있으면 `409 MEMBER_NAME_DUPLICATE`.

### 구성원 삭제 `DELETE /rooms/{room_token}/members/{member_id}`

받는 것 `204`. 아래 경우는 막습니다.
- 지우면 구성원이 2명 미만 → `409 MEMBERS_TOO_FEW`
- 영수증 결제자로 쓰인 구성원 → `409 MEMBER_IN_USE`
- 품목 체크에서 이 사람을 빼면 아무도 체크하지 않은 품목이 생김 → `409 MEMBER_IN_USE`

그 밖에는 이 사람의 체크를 모두 지우고 삭제합니다.

---

## 3. 영수증 입력 · 확인 · 확정 (2 · 3단계)

| 주소 | 하는 일 |
| --- | --- |
| `GET /rooms/{room_token}/receipts` | 영수증 목록 |
| `POST /rooms/{room_token}/receipts` | 영수증 만들기 (상태: 확인 중) |
| `GET /rooms/{room_token}/receipts/{receipt_id}` | 영수증 하나 보기 |
| `PUT /rooms/{room_token}/receipts/{receipt_id}` | 영수증 통째로 고치기 (확인 중일 때만) |
| `DELETE /rooms/{room_token}/receipts/{receipt_id}` | 영수증 지우기 (확인 중일 때만) |
| `POST /rooms/{room_token}/receipts/{receipt_id}/confirm` | 확정 |
| `POST /rooms/{room_token}/receipts/{receipt_id}/unconfirm` | 확정 취소 (확인 중으로 되돌림) |
| `POST /rooms/{room_token}/receipts/{receipt_id}/photo` | 사진 올리기 (선택) |
| `GET /rooms/{room_token}/receipts/{receipt_id}/photo` | 사진 보기 |

### 영수증 상태

| status | 화면 표시 | 할 수 있는 것 |
| --- | --- | --- |
| `CHECKING` | 확인 중 | 고치기 · 지우기 · 확정 |
| `CONFIRMED` | 확정 | 확정 취소만. 정산 계산에 들어감 |

### 영수증 만들기 `POST /rooms/{room_token}/receipts`

보내는 것:
```json
{
  "store_name": "1차 식당",
  "payer_member_id": 1,
  "total_amount": 150000,
  "items": [
    { "name": "김치찌개", "amount": 10000, "kind": "ITEM" },
    { "name": "고기", "amount": 50000, "kind": "ITEM" },
    { "name": "술", "amount": 90000, "kind": "ITEM" }
  ]
}
```

- 할인은 `items`에 한 줄로 넣습니다: `{ "name": "할인", "amount": -5000, "kind": "DISCOUNT" }`
- 서버 검사 5개 (통과 못 하면 `422 VALIDATION_ERROR`)
  1. 결제자가 이 정산방 구성원인가
  2. `ITEM` 줄이 1개 이상인가
  3. `ITEM` 금액은 0보다 크고, `DISCOUNT` 금액은 0보다 작은가
  4. 모든 줄에 이름이 있는가
  5. 총액이 있고 0보다 큰가
- 품목 합 ≠ 총액이어도 **막지 않습니다**

받는 것 `201`:
```json
{
  "id": 2,
  "store_name": "1차 식당",
  "payer": { "id": 1, "name": "A" },
  "status": "CHECKING",
  "total_amount": 150000,
  "items": [
    { "id": 21, "name": "김치찌개", "amount": 10000, "kind": "ITEM" },
    { "id": 22, "name": "고기", "amount": 50000, "kind": "ITEM" },
    { "id": 23, "name": "술", "amount": 90000, "kind": "ITEM" }
  ],
  "check": { "items_sum": 150000, "difference": 0, "is_matched": true },
  "photo_url": null,
  "created_at": "2026-11-16T14:05:00+09:00"
}
```

- `check.items_sum`: 할인 포함 모든 줄의 합 · `difference`: `total_amount − items_sum`
- 화면은 `is_matched`가 `false`면 "품목 합 ≠ 총액" 경고를 보여 주고, 확정은 그대로 할 수 있게 둡니다

### 영수증 고치기 `PUT /rooms/{room_token}/receipts/{receipt_id}`

보내는 것: 만들기와 같은 모양. 단, **이미 있는 줄은 `id`를 같이 보냅니다.**
- `id`가 있는 줄 → 고침 (체크 그대로 유지)
- `id`가 없는 줄 → 새 줄 (모든 구성원 체크로 시작)
- 보내지 않은 기존 줄 → 지움 (그 줄의 체크도 지움)

확정된 영수증이면 `409 RECEIPT_CONFIRMED`. 다른 영수증(또는 다른 정산방)의 줄 `id`를 보내면 `422 VALIDATION_ERROR`.

### 확정 · 확정 취소

- `POST …/confirm` → 받는 것 `200`: 영수증 (`status: "CONFIRMED"`). 품목 합 ≠ 총액이어도 확정됨
- `POST …/unconfirm` → 받는 것 `200`: 영수증 (`status: "CHECKING"`)
- 둘 다 최신 정산을 '최신 아님'으로 만듭니다

### 사진 `POST …/photo`

- 보내는 것: `multipart/form-data`, 칸 이름 `file`, jpg · png, 10MB 이하
- 받는 것 `200 { "photo_url": "/api/v1/rooms/{room_token}/receipts/2/photo" }`
- 서버는 사진을 `RECEIPT_STORAGE_PATH`(볼륨 `/data/receipts`)에 무작위 파일 이름으로 저장합니다
- 다시 올리면 이전 사진을 바꿉니다

---

## 4. 분담 조건 — 체크 표 (4단계)

| 주소 | 하는 일 |
| --- | --- |
| `GET /rooms/{room_token}/checks` | 체크 표 받기 (확정된 영수증의 품목만) |
| `PUT /rooms/{room_token}/checks` | 체크 표 저장 |

### 체크 표 받기 `GET /rooms/{room_token}/checks`

받는 것 `200`:
```json
{
  "members": [
    { "id": 1, "name": "A" }, { "id": 2, "name": "B" },
    { "id": 3, "name": "C" }, { "id": 4, "name": "D" }
  ],
  "items": [
    { "item_id": 21, "receipt_id": 2, "store_name": "1차 식당", "name": "김치찌개", "amount": 10000, "member_ids": [1, 2, 3, 4] },
    { "item_id": 22, "receipt_id": 2, "store_name": "1차 식당", "name": "고기", "amount": 50000, "member_ids": [1, 2, 3, 4] },
    { "item_id": 23, "receipt_id": 2, "store_name": "1차 식당", "name": "술", "amount": 90000, "member_ids": [1, 2, 3, 4] }
  ]
}
```
- `ITEM` 줄만 나옵니다. 할인(`DISCOUNT`) 줄은 V1에서 체크하지 않고, 그 영수증 참여자끼리 똑같이 나눕니다

### 체크 표 저장 `PUT /rooms/{room_token}/checks`

보내는 것: 바뀐 품목만 보내도 됩니다.
```json
{ "items": [ { "item_id": 23, "member_ids": [1, 2, 3] } ] }
```
- 품목마다 1명 이상 (아니면 `422 CHECK_EMPTY`)
- 없는 `item_id` · 확정 안 된 영수증의 품목 · 정산방에 없는 `member_id`를 보내면 `422 VALIDATION_ERROR`
- 받는 것 `200`: 체크 표 전체 (위 「받기」와 같은 모양)
- 최신 정산을 '최신 아님'으로 만듭니다

---

## 5. 정산 결과 (5단계)

| 주소 | 하는 일 |
| --- | --- |
| `POST /rooms/{room_token}/settlements` | **다시 계산** → 새 버전 저장 |
| `GET /rooms/{room_token}/settlements/latest` | 최신 결과 보기 |

### 다시 계산 `POST /rooms/{room_token}/settlements`

보내는 것: 없음. 서버가 확정된 영수증과 체크로 계산하고 새 버전으로 저장합니다.

받는 것 `201` (예시 1: A가 항공권 400,000 + 식당 150,000을 내고 D는 술 제외):
```json
{
  "version": 1,
  "created_at": "2026-11-16T14:20:00+09:00",
  "rounding": "WON_1",
  "is_stale": false,
  "members": [
    { "member_id": 1, "name": "A", "paid": 550000, "owed": 145000, "net": 405000 },
    { "member_id": 2, "name": "B", "paid": 0, "owed": 145000, "net": -145000 },
    { "member_id": 3, "name": "C", "paid": 0, "owed": 145000, "net": -145000 },
    { "member_id": 4, "name": "D", "paid": 0, "owed": 115000, "net": -115000 }
  ],
  "transfers": [
    { "from": { "id": 2, "name": "B" }, "to": { "id": 1, "name": "A" }, "amount": 145000 },
    { "from": { "id": 3, "name": "C" }, "to": { "id": 1, "name": "A" }, "amount": 145000 },
    { "from": { "id": 4, "name": "D" }, "to": { "id": 1, "name": "A" }, "amount": 115000 }
  ],
  "excluded_receipts": [],
  "copy_text": "[같이정산 · 제주 여행 · 버전 1]\nB → A 145,000원\nC → A 145,000원\nD → A 115,000원"
}
```

- `paid`: 낸 돈 · `owed`: 내야 할 돈 · `net`: `paid − owed` (양수면 받을 돈)
- `excluded_receipts`: 아직 확인 중이라 계산에서 빠진 영수증 `[{ "id": 3, "store_name": "카페" }]` — 화면은 "확정 안 된 영수증 1개는 빠졌어요"를 보여 줍니다
- `copy_text`: '송금 목록 복사' 버튼이 그대로 복사할 글
- 확정된 영수증이 없으면 `422 NO_CONFIRMED_RECEIPTS`

계산 규칙 (서버 담당):
1. 품목 금액 ÷ 체크된 사람 수
2. 차액(`difference`) · 할인 ÷ 그 영수증 참여자 수 (참여자 = 그 영수증 품목에 한 번이라도 체크된 사람)
   - 나누고 남는 돈은 구성원 순서대로 앞 사람부터 1원씩 더 냅니다. 할인도 같아서 앞 사람이 할인을 1원 덜 받습니다 (−5,000원 ÷ 3명 → A −1,666 · B −1,667 · C −1,667)
3. 원 단위 — `WON_1`: 1원 단위 그대로 / `WON_10`: 품목마다 올리지 않고, **영수증마다 한 사람이 낼 돈을 다 더한 뒤 한 번만** 10원 단위로 올립니다. 올리면서 생긴 차이는 결제자 몫입니다 (결제자가 그 영수증에서 먹지 않았어도 같음 — 결제자가 몇십 원 더 받을 수 있음)
4. 영수증마다 '각자 → 결제자', 같은 두 사람 사이는 하나로 합침 (반대 방향이면 차이만)
5. 정답 확인용: 노션 「V1 요구 명세」의 예시 1 · 예시 2

### 최신 결과 보기 `GET /rooms/{room_token}/settlements/latest`

받는 것 `200`: 위와 같은 모양. `is_stale`이 `true`면 화면 위에 "최신 결과가 아닙니다. 다시 계산을 눌러주세요"를 띄웁니다.
한 번도 계산하지 않았으면 `404 NOT_FOUND`.

**'최신 아님'이 되는 때**: 영수증 확정 · 확정 취소 · 확정 영수증 삭제(취소 후) · 체크 저장 · 구성원 추가 · 삭제 · 원 단위 변경

---

## 6. 화면 ↔ 주소 한눈에

| 화면 | 쓰는 주소 |
| --- | --- |
| 첫 화면 | `GET /health` |
| 정산방 만들기 | `POST /rooms` |
| 정산방 (영수증 목록) | `GET /rooms/{t}` · `GET /rooms/{t}/receipts` |
| 영수증 입력 · 고치기 | `POST` · `PUT /rooms/{t}/receipts…` · `POST …/photo` |
| 확인 · 확정 | `GET …/receipts/{id}` · `POST …/confirm` · `POST …/unconfirm` |
| 분담 조건 (체크 표) | `GET` · `PUT /rooms/{t}/checks` |
| 정산 결과 | `GET /rooms/{t}/settlements/latest` · `POST /rooms/{t}/settlements` |

---

## 정한 것 (11/9 확정 · 모두 초안대로)

| # | 정할 것 | 정한 안 | 고르지 않은 안 |
| --- | --- | --- | --- |
| 1 | 정산방 주소 이름 | `/rooms/{room_token}` | 백엔드 명세의 `/groups/{group_id}` |
| 2 | 영수증 상태 이름 | `CHECKING` · `CONFIRMED` | 백엔드 명세의 `DRAFT` · `CONFIRMED` |
| 3 | 할인 넣는 곳 | `items` 안의 `kind: "DISCOUNT"` 줄 | 영수증에 `discount_amount` 칸 |
| 4 | 체크 표에 할인 줄 | 넣지 않음 (참여자끼리 똑같이) | 할인 줄도 체크 |
| 5 | 송금 복사 글 | 서버가 `copy_text`로 만들어 줌 | 화면이 만듦 |
| 6 | 영수증 고치기 방식 | `PUT`으로 통째로 (줄마다 `id`) | 줄 하나씩 고치는 주소를 따로 |
| 7 | 지난 버전 보기 | V1에서는 최신만 | 버전 목록 주소 추가 |
