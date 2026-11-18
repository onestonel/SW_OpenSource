"""요청·답장 모양 (API 약속서 docs/api-v1.md). 이름은 snake_case, 시각은 한국 시간 ISO 8601."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, StringConstraints, ValidationInfo, field_validator

KST = ZoneInfo("Asia/Seoul")


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:  # SQLite는 시간대를 저장하지 않는다. 저장값은 UTC다
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(KST).isoformat(timespec="seconds")


Timestamp = Annotated[datetime, PlainSerializer(_iso, return_type=str)]
MemberName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]
Rounding = Literal["WON_1", "WON_10"]
ReceiptStatus = Literal["CHECKING", "CONFIRMED"]
ItemKind = Literal["ITEM", "DISCOUNT"]
MAX_AMOUNT = 100_000_000  # 한 줄 · 한 영수증 금액 상한 (1억 원). 잘못 친 숫자를 막는다


class In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Out(BaseModel):
    pass


# ------------------------------------------------------------------ 정산방 · 구성원 (1단계)

class RoomCreateIn(In):
    name: str = Field(min_length=1, max_length=50, description="정산방 이름 (예: 제주 여행)")
    members: list[MemberName] = Field(min_length=2, max_length=50,
                                      description="구성원 이름. 2명 이상, 빈 이름 불가. 같은 이름은 409 MEMBER_NAME_DUPLICATE. "
                                                  "입력한 순서가 구성원 순서")
    rounding: Rounding = Field(default="WON_1", description="WON_1 = 1원 단위(기본), WON_10 = 10원 단위 올림")


class RoomUpdateIn(In):
    name: str | None = Field(default=None, min_length=1, max_length=50)
    rounding: Rounding | None = None


class MemberCreateIn(In):
    name: MemberName


class MemberOut(Out):
    id: int
    name: str
    order: int


class LatestSettlementRef(Out):
    version: int
    is_stale: bool = Field(description="true면 영수증·체크가 바뀌어 '다시 계산'이 필요하다")


class RoomOut(Out):
    room_token: str = Field(description="정산방 링크 키. 화면은 이 값으로 정산방 주소를 만든다")
    name: str
    rounding: Rounding
    members: list[MemberOut]
    created_at: Timestamp


class RoomDetailOut(RoomOut):
    latest_settlement: LatestSettlementRef | None = Field(description="아직 한 번도 계산하지 않았으면 null")


# ------------------------------------------------------------------ 영수증 (2 · 3단계)

class ReceiptItemIn(In):
    """영수증 한 줄. 고치기(PUT)에서는 이미 있는 줄에 id를 같이 보낸다."""

    id: int | None = Field(default=None, description="고치기에서 이미 있는 줄의 id. 새 줄이면 뺀다")
    name: str = Field(min_length=1, max_length=50, description="품목 이름 (할인 줄은 예: 할인)")
    kind: ItemKind = Field(default="ITEM", description="ITEM = 품목, DISCOUNT = 할인")
    amount: int = Field(ge=-MAX_AMOUNT, le=MAX_AMOUNT, description="정수 원. 품목은 0보다 크고, 할인은 0보다 작다")

    @field_validator("amount")
    @classmethod
    def _sign(cls, amount: int, info: ValidationInfo) -> int:
        kind = info.data.get("kind")  # kind가 잘못됐으면 그쪽 오류만 보여 준다
        if kind == "ITEM" and amount <= 0:
            raise ValueError("품목 금액은 0보다 커야 합니다")
        if kind == "DISCOUNT" and amount >= 0:
            raise ValueError("할인 금액은 0보다 작아야 합니다 (예: -5000)")
        return amount


class ReceiptIn(In):
    """영수증 만들기 · 고치기. 품목 합 ≠ 총액이어도 막지 않는다 (답장의 check로 알려 준다)."""

    store_name: str = Field(min_length=1, max_length=50, description="가게 이름 (예: 1차 식당)")
    payer_member_id: int = Field(description="결제자. 이 정산방 구성원이어야 한다")
    total_amount: int = Field(gt=0, le=MAX_AMOUNT, description="영수증 총액. 정산은 총액 기준이다")
    items: list[ReceiptItemIn] = Field(max_length=100, description="품목 · 할인 줄. ITEM 줄이 1개 이상")

    @field_validator("items")
    @classmethod
    def _items(cls, items: list[ReceiptItemIn]) -> list[ReceiptItemIn]:
        if not any(i.kind == "ITEM" for i in items):
            raise ValueError("품목(ITEM) 줄이 1개 이상 있어야 합니다")
        ids = [i.id for i in items if i.id is not None]
        if len(ids) != len(set(ids)):
            raise ValueError("같은 줄 id가 두 번 들어 있습니다")
        return items


class PayerOut(Out):
    id: int
    name: str


class ReceiptItemOut(Out):
    id: int
    name: str
    amount: int
    kind: ItemKind


class ReceiptCheckOut(Out):
    items_sum: int = Field(description="할인을 포함한 모든 줄의 합")
    difference: int = Field(description="total_amount − items_sum")
    is_matched: bool = Field(description="false면 화면에 '품목 합 ≠ 총액' 경고 (확정은 그대로 가능)")


class ReceiptOut(Out):
    id: int
    store_name: str
    payer: PayerOut
    status: ReceiptStatus = Field(description="CHECKING = 확인 중, CONFIRMED = 확정 (정산에 들어감)")
    total_amount: int
    items: list[ReceiptItemOut]
    check: ReceiptCheckOut
    photo_url: str | None = Field(description="사진이 없으면 null")
    created_at: Timestamp


# ------------------------------------------------------------------ 체크 표 (4단계)

class CheckMemberOut(Out):
    id: int
    name: str


class CheckItemOut(Out):
    item_id: int
    receipt_id: int
    store_name: str
    name: str
    amount: int
    member_ids: list[int] = Field(description="이 품목을 나눠 내는 구성원 id (구성원 순서)")


class ChecksOut(Out):
    members: list[CheckMemberOut] = Field(description="구성원 순서")
    items: list[CheckItemOut] = Field(description="확정된 영수증의 품목(ITEM) 줄만. 할인 줄은 체크하지 않는다")


class CheckItemIn(In):
    item_id: int
    member_ids: list[int] = Field(description="이 품목을 나눠 낼 구성원 id. 빈 배열이면 422 CHECK_EMPTY")


class ChecksIn(In):
    items: list[CheckItemIn] = Field(description="바뀐 품목만 보내도 된다. 보내지 않은 품목의 체크는 그대로")


class InterpretIn(In):
    text: str = Field(min_length=1, max_length=200, description="분담 조건 문장. 예: \"D는 술 안 마셨어\"")
    previous: str | None = Field(default=None, max_length=400,
                                 description="되묻기(NEEDS_CLARIFICATION)에 답할 때, 앞에서 보낸 문장 (답장의 text)")


class InterpretChangeOut(Out):
    item_id: int
    receipt_id: int
    store_name: str
    name: str
    rule: Literal["EQUAL", "EXCLUDE", "FULL", "PAID"] = Field(
        description="EQUAL ~끼리만 · EXCLUDE ~빼고 · FULL ~가 다 냄 · PAID ~는 이미 보냄 (금액이 바뀜)")
    evidence: str | None = Field(description="해석기가 근거로 든 문장 부분")
    before_member_ids: list[int] = Field(description="지금 체크된 구성원 (구성원 순서)")
    after_member_ids: list[int] = Field(description="바꾼 뒤 체크될 구성원")
    before_amount: int = Field(description="지금 품목 금액")
    after_amount: int = Field(description="바꾼 뒤 품목 금액. PAID일 때만 달라진다 (서버가 계산)")
    note: str | None = Field(description="PAID일 때 무엇을 어떻게 바꾸는지 설명하는 문장")


class InterpretOut(Out):
    status: Literal["PARSED", "NEEDS_CLARIFICATION", "UNSUPPORTED"]
    message: str = Field(description="사용자에게 그대로 보여 줄 한국어 문장 (다시 묻기 질문 포함)")
    text: str = Field(description="해석한 문장 전체 (previous + text). 되물으면 다음 요청의 previous로 보낸다")
    changes: list[InterpretChangeOut] = Field(description="PARSED일 때만 채워진다. 저장은 하지 않는다")
    provider: str = Field(description="stub(모델 없이 흉내) 또는 llama(llama.cpp · EXAONE)")
    elapsed_ms: int = Field(description="해석에 걸린 시간 (밀리초)")


class ApplyLineIn(In):
    item_id: int
    member_ids: list[int] = Field(description="이 품목을 나눠 낼 구성원 id")
    amount: int | None = Field(default=None, gt=0, description="바꿀 품목 금액 (PAID 변경안의 after_amount). 줄이기만 된다")


class ApplyIn(In):
    changes: list[ApplyLineIn] = Field(min_length=1)


# ------------------------------------------------------------------ 정산 결과 (5단계)

class SettlementMemberOut(Out):
    member_id: int
    name: str
    paid: int = Field(description="낸 돈 (결제한 영수증 총액의 합)")
    owed: int = Field(description="내야 할 돈")
    net: int = Field(description="paid − owed. 양수면 받을 돈, 음수면 보낼 돈")


class TransferLineOut(Out):
    store_name: str
    from_id: int
    to_id: int
    amount: int


class TransferOut(Out):
    model_config = ConfigDict(populate_by_name=True)

    from_: PayerOut = Field(alias="from", description="보내는 사람")
    to: PayerOut = Field(description="받는 사람")
    amount: int
    breakdown: list[TransferLineOut] = Field(default_factory=list,
                                             description="합치기 전 두 사람 사이에 영수증별로 오간 돈 (양쪽 방향 모두)")
    explanation: str | None = Field(default=None, description="서로 보낼 돈이 있어서 합쳐졌을 때, 어떻게 합쳤는지 설명")


class ExcludedReceiptOut(Out):
    id: int
    store_name: str


class SettlementOut(Out):
    version: int = Field(description="다시 계산할 때마다 1씩 올라간다")
    created_at: Timestamp = Field(description="계산한 시각")
    rounding: Rounding = Field(description="계산할 때 쓴 원 단위")
    is_stale: bool = Field(description="true면 계산 뒤에 영수증 · 체크 · 구성원 · 원 단위가 바뀌었다 → '다시 계산' 안내")
    members: list[SettlementMemberOut] = Field(description="구성원 순서")
    transfers: list[TransferOut] = Field(description="같은 두 사람 사이는 하나로 합친 송금 목록")
    excluded_receipts: list[ExcludedReceiptOut] = Field(description="아직 확인 중이라 계산에서 빠진 영수증")
    copy_text: str = Field(description="'송금 목록 복사' 버튼이 그대로 복사할 글")
