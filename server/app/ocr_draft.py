"""OCR 초안 → 영수증 입력 규칙에 맞는 값 정리 (V2 OCR).

OCR(app/ocr)이 돌려준 초안(가게 이름 · 합계 · 줄)을 영수증 입력 규칙(schemas.ReceiptIn)에 맞게 고친다.
결과는 '확인 중'(CHECKING) 영수증으로 저장할 값이고, 사용자가 확인 화면에서 고친 뒤 확정한다.

- OCR 초안은 store_name · total_amount가 null일 수 있고, ITEM이 0개이거나 이름이 50자를 넘을 수 있다.
- 값을 버리거나 고칠 때마다 notes에 이유를 남긴다. '못 찾았다'는 경고는 OCR이 이미 주므로(warnings)
  여기서는 '어떻게 고쳤는지'만 남긴다. 합계 ≠ 품목 합도 OCR 경고와 영수증 답장의 check로 보이니 맞추지 않는다.
- 결제자는 OCR이 알 수 없으므로 여기서 정하지 않는다 (to_receipt_in에 넘긴다).
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
class RawLine:
    """OCR이 읽은 영수증 한 줄. 이름이나 금액을 못 읽었으면 None. kind는 OCR이 정했으면 ITEM · DISCOUNT."""

    name: str | None
    amount: int | float | str | None
    kind: str | None = None


@dataclass
class RawDraft:
    """OCR이 돌려준 초안 그대로 (app/ocr의 OcrResult와 헷갈리지 않게 이름을 다르게 했다)."""

    store_name: str | None
    total_amount: int | float | str | None
    lines: list[RawLine]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RawDraft:
        """OCR API 답장의 draft 모양: {"store_name", "total_amount", "items": [{"name", "amount", "kind"}]}."""
        return cls(
            store_name=data.get("store_name"),
            total_amount=data.get("total_amount"),
            lines=[RawLine(name=i.get("name"), amount=i.get("amount"), kind=i.get("kind"))
                   for i in data.get("items") or []],
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
    def problem(self) -> str | None:
        """영수증으로 만들 수 없는 이유. 만들 수 있으면 None."""
        if not any(i.kind == "ITEM" for i in self.items):
            return "품목을 하나도 읽지 못해"
        if self.total_amount is None:
            return "총액을 정하지 못해"
        return None

    @property
    def ok(self) -> bool:
        """영수증으로 만들 수 있는가 (총액이 있고 품목 줄이 하나 이상). 아니면 직접 입력을 안내한다."""
        return self.problem is None

    def to_receipt_in(self, payer_member_id: int) -> ReceiptIn:
        """영수증 만들기 요청 모양 (POST /rooms/{room_token}/receipts). ok가 아니면 ValueError."""
        if not self.ok:
            raise ValueError(f"{self.problem} 영수증을 만들 수 없습니다. 직접 입력해 주세요.")
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


def make_draft(result: RawDraft, store_name: str | None = None) -> ReceiptDraft:
    """OCR 초안을 영수증 입력 규칙에 맞는 초안으로 고친다. 고친 이유는 notes에 순서대로 남긴다.

    store_name: 사용자가 적은 가게 이름 (이미 있는 영수증에 저장할 때). 주면 OCR이 읽은 가게 이름은 쓰지 않는다.
    OCR은 가게 이름을 자주 틀려서, 가게 이름은 사용자가 직접 적는다 (API 명세서 3절 「새 영수증 흐름」).
    """
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

        # OCR이 줄 종류를 정했으면 따른다 ('할인상품 우유'는 품목일 수 있다). 안 정했으면 낱말로 본다
        by_word = line.kind is None and any(w in name for w in DISCOUNT_WORDS)
        discount = amount < 0 or line.kind == "DISCOUNT" or by_word
        if not name:
            name = "할인" if discount else f"품목 {n}"
            notes.append(f"{n}번째 줄: 이름을 읽지 못해 '{name}'(으)로 넣었습니다.")
        if len(name) > NAME_MAX:
            name = name[:NAME_MAX].rstrip()
            notes.append(f"'{name}': 이름이 길어 앞 {NAME_MAX}자만 넣었습니다.")
        if discount and amount > 0:
            notes.append(f"'{name}': 할인으로 보고 {_won(-amount)}으로 넣었습니다.")
        items.append(DraftLine(name=name, amount=-abs(amount) if discount else amount,
                               kind="DISCOUNT" if discount else "ITEM"))

    if len(items) > ITEMS_MAX:
        notes.append(f"줄이 {len(items)}개라 앞의 {ITEMS_MAX}개만 넣었습니다.")
        items = items[:ITEMS_MAX]

    store = _clean(result.store_name)
    if store_name is not None:
        store = store_name  # 사용자가 적은 이름을 그대로 쓴다. 고친 것이 아니라서 알림도 남기지 않는다
    elif not store:
        store = STORE_DEFAULT
        notes.append(f"가게 이름을 읽지 못해 '{STORE_DEFAULT}'(으)로 넣었습니다.")
    elif len(store) > NAME_MAX:
        store = store[:NAME_MAX].rstrip()
        notes.append(f"가게 이름이 길어 앞 {NAME_MAX}자만 넣었습니다.")

    items_sum = sum(i.amount for i in items)
    total = parse_amount(result.total_amount)
    if total is None or not 0 < total <= MAX_AMOUNT:
        why = "합계를 읽지 못해" if total is None else f"합계({_won(total)})가 올바르지 않아"
        if items_sum > 0:
            total = items_sum
            notes.append(f"{why} 품목 합({_won(items_sum)})으로 넣었습니다.")
        else:
            total = None  # 영수증으로 만들 수 없다 (problem). 이유는 부르는 쪽이 한 번만 알린다
    return ReceiptDraft(store_name=store, total_amount=total, items=items, notes=notes)
