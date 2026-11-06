"""정산 계산 (V1 요구 명세 5단계). 확정 영수증만 입력으로 받는다고 본다.

영수증마다
1. 참여자 = 그 영수증 품목에 한 번이라도 체크된 사람
2. 품목 금액은 체크된 사람끼리 똑같이 (남는 1원은 구성원 순서대로)
3. 할인 줄은 참여자끼리 똑같이 (할인 줄에 내는 사람이 지정돼 있으면 그 사람들끼리 — V3용)
4. 차액(총액 − 모든 줄의 합)도 참여자끼리 똑같이. 정산은 총액 기준이다
5. 원 단위: 1이면 그대로. 10이면 결제자가 아닌 사람의 몫을 10원 단위로 올리고, 남는 돈은 결제자가 낸다
6. 결제자가 아닌 사람마다 '→ 결제자' 송금을 만든다
마지막에 같은 두 사람 사이 송금을 하나로 합친다.

불변식 (어기면 RuntimeError — 엔진 버그)
- 줄마다 몫의 합 = 줄 금액, 영수증마다 몫의 합 = 총액
- 부담액 합 = 결제액 합 = 총액 합, 순잔액 합 = 0
- 송금 목록을 모두 실행하면 모든 순잔액이 0
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from .allocation import round_up, split_equal
from .transfers import Transfer, merge_transfers
from .types import DISCOUNT, ITEM, Member, Receipt

ROUNDING_UNITS = (1, 10)


class SettlementInputError(ValueError):
    """입력이 계산할 수 없는 모양. code는 API 오류 코드와 같다."""

    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


@dataclass(frozen=True)
class Share:
    item_id: int
    member_id: int
    amount: int


@dataclass(frozen=True)
class Balance:
    member_id: int
    paid: int
    owed: int

    @property
    def net(self) -> int:
        return self.paid - self.owed


@dataclass(frozen=True)
class ReceiptResult:
    """영수증 한 장의 계산 근거."""

    receipt_id: int
    payer_id: int
    total: int
    lines_sum: int  # 품목 + 할인 합
    difference: int  # 총액 − lines_sum
    participant_ids: list[int]
    difference_shares: dict[int, int]  # 차액을 누가 얼마씩
    subtotal: dict[int, int]  # 1원 단위로 나눈 몫 (줄 몫 + 차액 몫)
    owed: dict[int, int]  # 원 단위를 적용한 최종 부담액
    transfers: list[Transfer] = field(default_factory=list)  # 합치기 전 '→ 결제자'

    @property
    def rounding(self) -> dict[int, int]:
        """원 단위 조정액 (owed − subtotal). 1원 단위면 모두 0."""
        return {m: self.owed[m] - self.subtotal.get(m, 0) for m in self.owed}


@dataclass(frozen=True)
class SettlementResult:
    total: int
    balances: list[Balance]  # 구성원 순서(display_order, id)
    transfers: list[Transfer]  # 합친 뒤
    shares: list[Share]  # 줄별 몫 (1원 단위)
    receipts: list[ReceiptResult]


def _receipt(receipt: Receipt, by_id: dict[int, Member], unit: int) -> tuple[ReceiptResult, list[Share]]:
    def members(ids: Iterable[int]) -> list[Member]:
        ids = set(ids)
        unknown = sorted(i for i in ids if i not in by_id)
        if unknown:
            raise SettlementInputError("ITEM_PAYER_INVALID", "정산방에 없는 구성원이 체크되어 있습니다.",
                                       {"receipt_id": receipt.id, "member_ids": unknown})
        return sorted((by_id[i] for i in ids), key=lambda m: (m.order, m.id))

    if receipt.payer_id not in by_id:
        raise SettlementInputError("RECEIPT_PAYER_REQUIRED", "결제자가 정산방 구성원이 아닙니다.", {"receipt_id": receipt.id})
    products = [i for i in receipt.items if i.kind == ITEM]
    if not products:
        raise SettlementInputError("RECEIPT_EMPTY", "품목이 없는 영수증입니다.", {"receipt_id": receipt.id})
    for i in products:
        if not i.payer_ids:
            raise SettlementInputError("CHECK_EMPTY", f"'{i.name}' 품목에 체크된 사람이 없습니다.",
                                       {"receipt_id": receipt.id, "receipt_item_id": i.id})

    participants = members(p for i in products for p in i.payer_ids)
    subtotal = dict.fromkeys((m.id for m in participants), 0)
    shares: list[Share] = []

    for item in receipt.items:
        if item.kind == DISCOUNT:
            who = members(item.payer_ids) if item.payer_ids else participants
        elif item.kind == ITEM:
            who = members(item.payer_ids)
        else:
            raise ValueError(f"unknown item kind: {item.kind}")
        split = split_equal(item.amount, who)
        if sum(split.values()) != item.amount:
            raise RuntimeError(f"item {item.id}: shares do not sum to amount")
        for m in who:
            subtotal[m.id] = subtotal.get(m.id, 0) + split[m.id]
            shares.append(Share(item.id, m.id, split[m.id]))

    lines_sum = sum(i.amount for i in receipt.items)
    difference = receipt.total - lines_sum
    diff_split = split_equal(difference, participants) if difference else {}
    for mid, v in diff_split.items():
        subtotal[mid] += v
    if sum(subtotal.values()) != receipt.total:
        raise RuntimeError(f"receipt {receipt.id}: shares do not sum to total")

    payer = receipt.payer_id
    if unit == 1:
        owed = {**subtotal, payer: subtotal.get(payer, 0)}  # 결제자가 참여하지 않았어도 0으로 둔다
    else:
        owed = {mid: round_up(v, unit) for mid, v in subtotal.items() if mid != payer}
        owed[payer] = receipt.total - sum(owed.values())  # 올림으로 더 걷힌 돈만큼 결제자 몫이 준다

    transfers = []
    for mid, v in owed.items():
        if mid == payer or v == 0:
            continue
        transfers.append(Transfer(mid, payer, v) if v > 0 else Transfer(payer, mid, -v))

    ordered_ids = sorted(owed, key=lambda m: (by_id[m].order, m))
    return ReceiptResult(
        receipt_id=receipt.id, payer_id=payer, total=receipt.total, lines_sum=lines_sum, difference=difference,
        participant_ids=[m.id for m in participants], difference_shares=diff_split,
        subtotal={m: subtotal.get(m, 0) for m in ordered_ids}, owed={m: owed[m] for m in ordered_ids},
        transfers=transfers,
    ), shares


def compute(members: Sequence[Member], receipts: Sequence[Receipt], rounding_unit: int = 1) -> SettlementResult:
    if not members:
        raise ValueError("at least one member is required")
    if rounding_unit not in ROUNDING_UNITS:
        raise ValueError(f"rounding_unit must be one of {ROUNDING_UNITS}")
    ordered = sorted(members, key=lambda m: (m.order, m.id))
    by_id = {m.id: m for m in ordered}
    member_ids = [m.id for m in ordered]

    paid = dict.fromkeys(member_ids, 0)
    owed = dict.fromkeys(member_ids, 0)
    shares: list[Share] = []
    results: list[ReceiptResult] = []
    raw: list[Transfer] = []
    total = 0

    for receipt in receipts:
        result, receipt_shares = _receipt(receipt, by_id, rounding_unit)
        results.append(result)
        shares.extend(receipt_shares)
        raw.extend(result.transfers)
        paid[receipt.payer_id] += receipt.total
        total += receipt.total
        for mid, v in result.owed.items():
            owed[mid] += v

    balances = [Balance(mid, paid[mid], owed[mid]) for mid in member_ids]
    if sum(b.owed for b in balances) != total or sum(b.net for b in balances) != 0:
        raise RuntimeError("settlement invariants violated")

    transfers = merge_transfers(raw, by_id)
    after = {b.member_id: b.net for b in balances}
    for t in transfers:
        after[t.from_id] += t.amount
        after[t.to_id] -= t.amount
    if any(after.values()):
        raise RuntimeError("transfers do not settle all balances")

    return SettlementResult(total=total, balances=balances, transfers=transfers, shares=shares, receipts=results)
