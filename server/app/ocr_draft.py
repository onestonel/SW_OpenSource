"""OCR 결과 → 영수증 초안 값 정리 (V2 OCR).

OCR 엔진이 읽은 가게 이름 · 합계 · 줄(이름 + 금액)을 영수증 입력 규칙(schemas.ReceiptIn)에 맞게 고친다.
결과는 '확인 중'(CHECKING) 영수증으로 저장할 값이고, 사용자가 확인 화면에서 고친 뒤 확정한다.

- OCR은 틀릴 수 있다. 값을 버리거나 고칠 때마다 notes에 이유를 남겨 확인 화면에서 보여 줄 수 있게 한다.
- 결제자는 OCR이 알 수 없으므로 여기서 정하지 않는다 (to_receipt_in에 넘긴다).
- 합계가 품목 합과 달라도 맞추지 않는다. 차이는 영수증 답장의 check로도 보인다 (receipts.receipt_out).
- OCR 엔진의 결과 모양이 정해지면 OcrResult.from_dict 하나만 맞추면 된다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .schemas import MAX_AMOUNT, ReceiptIn

NAME_MAX = 50  # ReceiptIn.store_name · ReceiptItemIn.name 길이 상한
ITEMS_MAX = 100  # ReceiptIn.items 개수 상한
STORE_DEFAULT = "영수증"
DISCOUNT_WORDS = ("할인", "쿠폰")

# 12000 · 12,000 · 12.000 · 12,000원 · ₩12,000 · -3,000 (영수증 금액은 원 단위 정수라 . 도 천 단위 구분으로 본다)
_AMOUNT = re.compile(r"^(-)?(\d{1,3}(?:[,.]\d{3})+|\d+)원?$")
_MINUS = str.maketrans({"−": "-", "－": "-", "–": "-"})


@dataclass
class OcrLine:
    """OCR이 읽은 영수증 한 줄. 이름이나 금액을 못 읽었으면 None."""

    name: str | None
    amount: int | float | str | None


@dataclass
class OcrResult:
    store_name: str | None
    total_amount: int | float | str | None
    lines: list[OcrLine]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OcrResult:
        """{"store_name", "total_amount", "items": [{"name", "amount"}]} 모양의 OCR 결과."""
        return cls(
            store_name=data.get("store_name"),
            total_amount=data.get("total_amount"),
            lines=[OcrLine(name=i.get("name"), amount=i.get("amount")) for i in data.get("items") or []],
        )


@dataclass
class DraftLine:
    name: str
    amount: int
    kind: str  # "ITEM" | "DISCOUNT"


@dataclass
class ReceiptDraft:
    store_name: str
    total_amount: int | None  # 합계도 품목 금액도 못 읽었으면 None
    items: list[DraftLine]
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """영수증으로 만들 수 있는가 (총액이 있고 품목 줄이 하나 이상). 아니면 직접 입력을 안내한다."""
        return self.total_amount is not None and any(i.kind == "ITEM" for i in self.items)

    def to_receipt_in(self, payer_member_id: int) -> ReceiptIn:
        """영수증 만들기 요청 모양 (POST /rooms/{room_token}/receipts). ok가 아니면 ValueError."""
        if not self.ok:
            raise ValueError("OCR 결과로 영수증을 만들 수 없습니다. 직접 입력해 주세요.")
        return ReceiptIn(
            store_name=self.store_name, payer_member_id=payer_member_id, total_amount=self.total_amount,
            items=[{"name": i.name, "amount": i.amount, "kind": i.kind} for i in self.items],
        )


def parse_amount(value: int | float | str | None) -> int | None:
    """OCR 금액 → 정수 원. 읽을 수 없으면 None."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    text = "".join(str(value).translate(_MINUS).split()).lstrip("₩\\")
    m = _AMOUNT.match(text)
    if m is None:
        return None
    number = int(re.sub(r"[,.]", "", m.group(2)))
    return -number if m.group(1) else number


def _clean(text: str | None) -> str:
    return " ".join(str(text).split()) if text is not None else ""


def _won(amount: int) -> str:
    return f"{amount:,}원"


def make_draft(result: OcrResult) -> ReceiptDraft:
    """OCR 결과를 영수증 입력 규칙에 맞는 초안으로 고친다. 고친 이유는 notes에 순서대로 남긴다."""
    notes: list[str] = []
    items: list[DraftLine] = []

    for n, line in enumerate(result.lines, start=1):
        name = _clean(line.name)
        label = f"'{name}'" if name else f"{n}번째 줄"
        amount = parse_amount(line.amount)
        if amount is None:
            notes.append(f"{label}: 금액을 읽지 못해 뺐습니다.")
            continue
        if amount == 0:
            notes.append(f"{label}: 0원이라 뺐습니다.")
            continue
        if abs(amount) > MAX_AMOUNT:
            notes.append(f"{label}: 금액({_won(amount)})이 1억 원을 넘어 잘못 읽은 것으로 보고 뺐습니다.")
            continue

        discount = amount < 0 or any(w in name for w in DISCOUNT_WORDS)
        if not name:
            name = "할인" if discount else f"품목 {n}"
            notes.append(f"{n}번째 줄: 이름을 읽지 못해 '{name}'(으)로 넣었습니다.")
        if len(name) > NAME_MAX:
            name = name[:NAME_MAX]
            notes.append(f"'{name}': 이름이 길어 앞 {NAME_MAX}자만 넣었습니다.")
        if discount and amount > 0:
            notes.append(f"'{name}': 할인으로 보고 {_won(-amount)}으로 넣었습니다.")
        items.append(DraftLine(name=name, amount=-abs(amount) if discount else amount,
                               kind="DISCOUNT" if discount else "ITEM"))

    if len(items) > ITEMS_MAX:
        notes.append(f"줄이 {len(items)}개라 앞의 {ITEMS_MAX}개만 넣었습니다.")
        items = items[:ITEMS_MAX]

    store = _clean(result.store_name)
    if not store:
        store = STORE_DEFAULT
        notes.append(f"가게 이름을 읽지 못해 '{STORE_DEFAULT}'(으)로 넣었습니다.")
    elif len(store) > NAME_MAX:
        store = store[:NAME_MAX]
        notes.append(f"가게 이름이 길어 앞 {NAME_MAX}자만 넣었습니다.")

    items_sum = sum(i.amount for i in items)
    total = parse_amount(result.total_amount)
    if total is None or not 0 < total <= MAX_AMOUNT:
        why = "합계를 읽지 못해" if total is None else f"합계({_won(total)})가 올바르지 않아"
        if items_sum > 0:
            total = items_sum
            notes.append(f"{why} 품목 합({_won(items_sum)})으로 넣었습니다.")
        else:
            total = None
            notes.append(f"{why} 총액을 정하지 못했습니다.")
    elif total != items_sum:
        notes.append(f"합계({_won(total)})와 품목 합({_won(items_sum)})이 {_won(abs(total - items_sum))} 다릅니다. "
                     "금액을 잘못 읽었을 수 있으니 확인해 주세요.")

    if not any(i.kind == "ITEM" for i in items):
        notes.append("품목을 하나도 읽지 못했습니다. 직접 입력해 주세요.")
    return ReceiptDraft(store_name=store, total_amount=total, items=items, notes=notes)
