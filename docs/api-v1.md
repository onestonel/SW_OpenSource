# 같이정산 V1 API 명세서

화면(web)과 서버(server)가 **무엇을 보내고 무엇을 돌려받는지** 정한 문서입니다.
화면 담당은 이 문서대로 요청을 보내고, 서버 담당은 이 문서대로 답장을 돌려줍니다.
바꿀 일이 생기면 **코드보다 이 문서를 먼저 고치고**(PR), 서로 확인한 뒤 코드를 고칩니다.

- 기준: 노션 「V1 요구 명세 (11/4 확정)」

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
| 409 | `MEMBER_IN_USE` | 결제자로 쓰인 구성원을 지우려 하거나, 지우면 아무도 체크하지 않은 품목이 생김 |
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

- `members`는 2명 이상이어야 하고, 빈 이름이나 같은 이름은 넣을 수 없습니다. 같은 이름이 있으면 `409 MEMBER_NAME_DUPLICATE`를 돌려줍니다. 입력한 순서가 그대로 구성원 순서가 됩니다.
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

- `room_token`은 길이가 정해져 있지 않습니다. 지금 서버는 22자로 만들고 있지만 바뀔 수 있어서, 화면에서는 길이를 정해 두고 쓰지 않도록 해 주세요.
- `order`는 구성원 순서이고, 정산방을 만들 때 입력한 순서대로 1, 2, 3…이 붙습니다. 남는 1원을 누가 낼지 정할 때와 목록을 보여 줄 때 이 순서를 씁니다.
- 구성원을 지워도 번호를 다시 매기지 않다 보니 1, 3, 4처럼 중간이 빌 수 있어서, 화면에서는 번호로 보여 주지 말고 순서를 맞추는 데만 써 주시면 됩니다.

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
같은 이름의 구성원이 이미 있으면 `409 MEMBER_NAME_DUPLICATE`를 돌려줍니다.

### 구성원 삭제 `DELETE /rooms/{room_token}/members/{member_id}`

삭제가 되면 `204`를 돌려주고, 이 사람이 체크된 품목에서도 체크를 같이 지웁니다. 다만 아래 경우에는 지우지 않고 막습니다.
- 지우고 나면 구성원이 2명보다 적어지는 경우에는 `409 MEMBERS_TOO_FEW`를 돌려줍니다.
- 영수증 결제자로 들어가 있는 구성원이면 `409 MEMBER_IN_USE`를 돌려줍니다.
- 이 사람을 체크에서 빼면 아무도 체크하지 않은 품목이 생기는 경우에도 `409 MEMBER_IN_USE`를 돌려줍니다 (`details.item_ids`에 그 품목 id). 확인 중인 영수증의 품목도 봅니다.

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

### 영수증 목록 `GET /rooms/{room_token}/receipts`

프론트엔드가 이 주소를 부르면, 백엔드는 정산방에 있는 영수증을 전부 목록으로 보내 줍니다. 목록 안의 영수증 하나하나에는 영수증을 만들 때 돌려받는 것과 같은 내용이 들어 있어서, 가게 이름, 결제자, 상태, 총액, 품목들, 사진 주소를 그대로 볼 수 있습니다. 먼저 만든 영수증이 목록 앞쪽에 옵니다.

정산방에 영수증이 여러 개 있으면, 아직 확인 중인 영수증이든 확정한 영수증이든 상관없이 전부 목록에 나옵니다. 그래서 화면에서는 영수증마다 '확인 중'인지 '확정'인지 따로 보여 줘야 합니다.

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
- 영수증을 고치다가 할인 줄을 품목으로 바꾸면, 그 줄은 새로 넣은 품목처럼 모든 구성원이 체크된 채로 시작합니다. 반대로 V1에서는 할인을 체크 표에서 고르지 않고 그 영수증에 참여한 사람끼리 똑같이 나누기 때문에, 품목을 할인으로 바꾸면 그 줄에 있던 체크는 지워집니다. 그래서 화면에서 줄 종류를 바꿀 때 체크를 따로 정리할 필요는 없을 거 같습니다.

확정된 영수증이면 `409 RECEIPT_CONFIRMED`.
다른 영수증이나 다른 정산방에 있는 줄의 `id`를 보내면 `422 VALIDATION_ERROR`를 돌려줍니다.

### 확정 · 확정 취소

- `POST …/confirm` → 받는 것 `200`: 영수증 (`status: "CONFIRMED"`). 품목 합 ≠ 총액이어도 확정됨
- `POST …/unconfirm` → 받는 것 `200`: 영수증 (`status: "CHECKING"`)
- 둘 다 최신 정산을 '최신 아님'으로 만듭니다

이미 확정된 영수증을 다시 확정하면, 백엔드는 오류를 내지 않고 그 영수증을 그대로 돌려줍니다. 그래서 화면에서 확정 버튼을 누르기 전에 이미 확정된 영수증인지 따로 확인할 필요는 없을 거 같습니다. 반대로 아직 확인 중인 영수증을 확정 취소하면 취소할 확정이 없어서, 백엔드는 `409 RECEIPT_NOT_CONFIRMED`를 돌려줍니다.

### 사진 `POST …/photo`

- 보내는 것: `multipart/form-data`, 칸 이름 `file`, jpg · png, 10MB 이하
- 받는 것 `200 { "photo_url": "/api/v1/rooms/{room_token}/receipts/2/photo" }`
- 서버는 사진을 `RECEIPT_STORAGE_PATH`(볼륨 `/data/receipts`)에 무작위 파일 이름으로 저장합니다
- 다시 올리면 이전 사진을 바꿉니다
- 사진은 영수증을 확정하기 전에 작성할 때 편하게 쓰려는 것이고, 부차적으로는 앞으로 OCR을 넣기 위해 사진 데이터 공간을 확보해 둔 것이기 때문에, 확정된 영수증에는 사진을 올릴 수 없습니다. 프론트엔드가 확정된 영수증에 사진을 보내면 백엔드는 `409 RECEIPT_CONFIRMED`를 돌려줍니다. 확정한 뒤에 사진을 바꾸고 싶으면 먼저 확정 취소를 하면 됩니다.

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
- 품목마다 1명 이상 (아니면 `422 CHECK_EMPTY`, `details.item_ids`에 빈 품목 id)
- 없는 `item_id`나 아직 확정하지 않은 영수증의 품목을 보내거나, 정산방에 없는 `member_id`를 보내면 `422 VALIDATION_ERROR`를 돌려줍니다. 하나라도 틀리면 아무것도 바꾸지 않습니다.
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
   - 금액이 딱 나누어떨어지지 않을 때는 구성원 순서가 앞인 사람부터 1원씩 더 내게 됩니다. 예를 들어 10,000원을 3명이 나누면 A가 3,334원, B와 C가 3,333원씩 냅니다.
   - 할인도 똑같이 처리해서 앞 사람이 할인을 1원 덜 받게 됩니다. 할인 5,000원을 3명이 나누면 A는 1,666원, B와 C는 1,667원씩 할인받습니다.
3. 원 단위
   - `WON_1`은 1원 단위 그대로 계산합니다.
   - `WON_10`은 결제자가 아닌 사람의 몫을 10원 단위로 올리는데, 품목마다 올리지 않고 영수증 하나에서 그 사람 몫을 다 더한 다음에 한 번만 올립니다. 예를 들어 B가 한 영수증에서 1,234원짜리와 2,345원짜리를 먹었으면 합쳐서 3,579원이 되고, 이걸 올려서 3,580원을 냅니다.
   - 이렇게 올려서 더 걷힌 돈만큼 결제자가 덜 내게 됩니다. 그래서 결제자가 그 영수증에서 먹은 게 없으면 결제자가 몇 원 더 받게 되는데, 이건 오류가 아니라 정해 둔 규칙입니다.
4. 영수증마다 '각자 → 결제자', 같은 두 사람 사이는 하나로 합침 (반대 방향이면 차이만)
5. 정답 확인용: 노션 「V1 요구 명세」의 예시 1 · 예시 2

### 최신 결과 보기 `GET /rooms/{room_token}/settlements/latest`

받는 것 `200`: 위와 같은 모양. `is_stale`이 `true`면 화면 위에 "최신 결과가 아닙니다. 다시 계산을 눌러주세요"를 띄웁니다.
한 번도 계산하지 않았으면 `404 NOT_FOUND`.

다시 계산할 때마다 버전 번호는 1씩 올라가지만, V1에서는 가장 최근 결과만 볼 수 있게 하고 예전 결과를 보는 주소는 따로 만들지 않습니다.

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
