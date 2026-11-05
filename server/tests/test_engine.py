"""정산 계산 함수 테스트 (#8). 노션 「V1 요구 명세」의 예시 1 · 2 표와 같은지 확인한다. DB 없이 돈다."""

from __future__ import annotations

import random

import pytest

from app.engine import (
    DISCOUNT,
    Item,
    Member,
    Receipt,
    SettlementInputError,
    Transfer,
    compute,
    merge_transfers,
    round_up,
    split_equal,
)

A, B, C, D = (Member(i, n, i) for i, n in enumerate("ABCD", start=1))
MEMBERS = [A, B, C, D]
BY_ID = {m.id: m for m in MEMBERS}
NAME = {m.id: m.name for m in MEMBERS}


def who(names: str) -> tuple[int, ...]:
    return tuple(m.id for m in MEMBERS if m.name in names)


def transfers(result) -> list[tuple[str, str, int]]:
    return [(NAME[t.from_id], NAME[t.to_id], t.amount) for t in result.transfers]


# ------------------------------------------------------------------ 완성 기준 예시

def example1() -> list[Receipt]:
    """A가 항공권 400,000원(4명)과 식당 150,000원(김치찌개 10,000 · 고기 50,000은 4명, 술 90,000은 A·B·C)을 냈다."""
    return [
        Receipt(1, "항공권", A.id, 400_000, (Item(11, "항공권", 400_000, payer_ids=who("ABCD")),)),
        Receipt(2, "식당", A.id, 150_000, (
            Item(21, "김치찌개", 10_000, payer_ids=who("ABCD")),
            Item(22, "고기", 50_000, payer_ids=who("ABCD")),
            Item(23, "술", 90_000, payer_ids=who("ABC")),
        )),
    ]


def example2() -> list[Receipt]:
    """1차 식당 60,000원은 A (김치찌개 10,000은 A·B, 고기 50,000은 A·B·C). 2차 술집 100,000원은 B (술 4명)."""
    return [
        Receipt(1, "1차 식당", A.id, 60_000, (
            Item(11, "김치찌개", 10_000, payer_ids=who("AB")),
            Item(12, "고기", 50_000, payer_ids=who("ABC")),
        )),
        Receipt(2, "2차 술집", B.id, 100_000, (Item(21, "술", 100_000, payer_ids=who("ABCD")),)),
    ]


@pytest.mark.parametrize("unit", [1, 10])
def test_example1_single_payer(unit):
    """송금표: B→A 145,000 / C→A 145,000 / D→A 115,000 (1원 · 10원 같음)."""
    assert transfers(compute(MEMBERS, example1(), unit)) == [
        ("B", "A", 145_000), ("C", "A", 145_000), ("D", "A", 115_000)]


def test_example2_one_won():
    result = compute(MEMBERS, example2(), 1)
    assert transfers(result) == [("A", "B", 3_333), ("C", "A", 16_666), ("C", "B", 25_000), ("D", "B", 25_000)]
    # 고기 50,000 ÷ 3 = 16,666원, 남는 2원은 순서대로 A·B가 1원씩 더 낸다
    meat = {s.member_id: s.amount for s in result.shares if s.item_id == 12}
    assert meat == {A.id: 16_667, B.id: 16_667, C.id: 16_666}


def test_example2_ten_won_round_up():
    result = compute(MEMBERS, example2(), 10)
    assert transfers(result) == [("A", "B", 3_330), ("C", "A", 16_670), ("C", "B", 25_000), ("D", "B", 25_000)]
    first = result.receipts[0]
    # 결제자가 아닌 사람은 10원 단위로 올리고, 남는 돈은 결제자가 낸다
    assert first.subtotal == {A.id: 21_667, B.id: 21_667, C.id: 16_666}
    assert first.owed == {A.id: 21_660, B.id: 21_670, C.id: 16_670}
    assert sum(first.owed.values()) == 60_000


def test_example2_merges_pair_transfers():
    """A↔B는 B→A 21,667원과 A→B 25,000원을 합쳐 A→B 3,333원이 된다."""
    r = compute(MEMBERS, example2(), 1)
    raw = [(NAME[t.from_id], NAME[t.to_id], t.amount) for rr in r.receipts for t in rr.transfers]
    assert ("B", "A", 21_667) in raw and ("A", "B", 25_000) in raw
    assert ("A", "B", 3_333) in transfers(r)


def test_example2_balances():
    r = compute(MEMBERS, example2(), 1)
    assert [(NAME[b.member_id], b.paid, b.owed, b.net) for b in r.balances] == [
        ("A", 60_000, 46_667, 13_333), ("B", 100_000, 46_667, 53_333),
        ("C", 0, 41_666, -41_666), ("D", 0, 25_000, -25_000)]


# ------------------------------------------------------------------ 나누기 규칙

@pytest.mark.parametrize(("amount", "members", "expected"), [
    (10_000, [A, B, C], {1: 3_334, 2: 3_333, 3: 3_333}),
    (50_000, [A, B, C], {1: 16_667, 2: 16_667, 3: 16_666}),
    (-1_000, [A, B, C], {1: -333, 2: -333, 3: -334}),  # 할인도 남는 1원은 앞사람부터 더 낸다
    (1, [A, B, C, D], {1: 1, 2: 0, 3: 0, 4: 0}),
    (2, [C, A, B], {1: 1, 2: 1, 3: 0}),  # 넣은 순서가 아니라 구성원 순서
])
def test_split_equal(amount, members, expected):
    assert split_equal(amount, members) == expected


def test_split_equal_rejects_bad_input():
    with pytest.raises(ValueError):
        split_equal(100, [])
    with pytest.raises(ValueError):
        split_equal(100, [A, A])


@pytest.mark.parametrize(("amount", "expected"), [(16_666, 16_670), (16_670, 16_670), (1, 10), (0, 0), (-15, -10)])
def test_round_up(amount, expected):
    assert round_up(amount, 10) == expected


def test_merge_transfers():
    raw = [Transfer(2, 1, 21_667), Transfer(1, 2, 25_000), Transfer(3, 1, 100), Transfer(3, 1, 50), Transfer(4, 4, 9)]
    assert merge_transfers(raw, BY_ID) == [Transfer(1, 2, 3_333), Transfer(3, 1, 150)]
    assert merge_transfers([Transfer(1, 2, 500), Transfer(2, 1, 500)], BY_ID) == []


# ------------------------------------------------------------------ 할인 · 차액 · 참여자

def test_discount_is_split_among_participants():
    """할인은 그 영수증 참여자(품목에 한 번이라도 체크된 사람)끼리 똑같이. D는 참여자가 아니다."""
    r = Receipt(1, "피자", A.id, 17_000, (
        Item(1, "피자", 15_000, payer_ids=who("AB")),
        Item(2, "콜라", 5_000, payer_ids=who("C")),
        Item(3, "할인", -3_000, kind=DISCOUNT),
    ))
    result = compute(MEMBERS, [r])
    assert {s.member_id: s.amount for s in result.shares if s.item_id == 3} == {1: -1_000, 2: -1_000, 3: -1_000}
    assert result.receipts[0].owed == {A.id: 6_500, B.id: 6_500, C.id: 4_000}
    assert transfers(result) == [("B", "A", 6_500), ("C", "A", 4_000)]


def test_difference_is_split_among_participants():
    """품목 합 ≠ 총액이어도 정산은 총액 기준. 차액은 참여자끼리 똑같이 (남는 1원은 순서대로)."""
    r = Receipt(1, "카페", B.id, 10_002, (Item(1, "커피", 6_000, payer_ids=who("ABC")),))  # 4,002원 덜 적음
    result = compute(MEMBERS, [r])
    rr = result.receipts[0]
    assert rr.lines_sum == 6_000 and rr.difference == 4_002
    assert rr.difference_shares == {A.id: 1_334, B.id: 1_334, C.id: 1_334}
    assert rr.owed == {A.id: 3_334, B.id: 3_334, C.id: 3_334}
    assert result.total == 10_002


def test_negative_difference():
    r = Receipt(1, "카페", A.id, 9_000, (Item(1, "커피", 10_000, payer_ids=who("AB")),))  # 총액이 1,000원 적음
    assert compute(MEMBERS, [r]).receipts[0].owed == {A.id: 4_500, B.id: 4_500}


def test_payer_who_did_not_take_part():
    """결제자가 아무 품목에도 체크되지 않으면 결제자 몫은 0이다."""
    r = Receipt(1, "택시", D.id, 9_000, (Item(1, "택시", 9_000, payer_ids=who("ABC")),))
    result = compute(MEMBERS, [r])
    assert transfers(result) == [("A", "D", 3_000), ("B", "D", 3_000), ("C", "D", 3_000)]
    assert result.receipts[0].owed[D.id] == 0


def test_ten_won_payer_absorbs_rounding_even_if_not_participant():
    r = Receipt(1, "택시", D.id, 10_000, (Item(1, "택시", 10_000, payer_ids=who("ABC")),))
    result = compute(MEMBERS, [r], 10)
    assert result.receipts[0].owed == {A.id: 3_340, B.id: 3_340, C.id: 3_340, D.id: -20}
    assert sum(b.net for b in result.balances) == 0


def test_items_need_a_payer():
    r = Receipt(1, "x", A.id, 1_000, (Item(1, "x", 1_000, payer_ids=()),))
    with pytest.raises(SettlementInputError) as e:
        compute(MEMBERS, [r])
    assert e.value.code == "ITEM_NO_PAYER"


def test_unknown_member_in_checks():
    r = Receipt(1, "x", A.id, 1_000, (Item(1, "x", 1_000, payer_ids=(1, 99)),))
    with pytest.raises(SettlementInputError) as e:
        compute(MEMBERS, [r])
    assert e.value.code == "ITEM_PAYER_INVALID"


def test_receipt_without_products():
    r = Receipt(1, "x", A.id, 1_000, (Item(1, "할인", -1_000, kind=DISCOUNT),))
    with pytest.raises(SettlementInputError) as e:
        compute(MEMBERS, [r])
    assert e.value.code == "RECEIPT_EMPTY"


def test_rounding_unit_must_be_1_or_10():
    with pytest.raises(ValueError):
        compute(MEMBERS, example2(), 100)


# ------------------------------------------------------------------ 불변식 (무작위 1,000회)

def random_case(rng: random.Random):
    members = [Member(i, f"M{i}", order=rng.randint(1, 5)) for i in range(1, rng.randint(2, 8) + 1)]
    ids = [m.id for m in members]
    receipts, item_id = [], 0
    for rid in range(1, rng.randint(1, 5) + 1):
        items = []
        for _ in range(rng.randint(1, 6)):
            item_id += 1
            items.append(Item(item_id, "x", rng.randint(1, 300_000), payer_ids=tuple(rng.sample(ids, rng.randint(1, len(ids))))))
        lines = sum(i.amount for i in items)
        if rng.random() < 0.3:  # 할인
            item_id += 1
            items.append(Item(item_id, "할인", -rng.randint(1, lines - 1) if lines > 1 else -1, kind=DISCOUNT))
        lines = sum(i.amount for i in items)
        total = max(1, lines + (rng.randint(-500, 500) if rng.random() < 0.3 else 0))  # 차액
        receipts.append(Receipt(rid, "r", payer_id=rng.choice(ids), total=total, items=tuple(items)))
    return members, receipts


@pytest.mark.parametrize("unit", [1, 10])
def test_random_invariants(unit):
    rng = random.Random(20261103 + unit)
    for _ in range(1000):
        members, receipts = random_case(rng)
        result = compute(members, receipts, unit)
        total = sum(r.total for r in receipts)
        assert result.total == total
        assert sum(b.owed for b in result.balances) == total
        assert sum(b.paid for b in result.balances) == total
        assert sum(b.net for b in result.balances) == 0
        assert all(t.amount > 0 and t.from_id != t.to_id for t in result.transfers)
        pairs = [frozenset((t.from_id, t.to_id)) for t in result.transfers]
        assert len(pairs) == len(set(pairs))  # 같은 두 사람 사이는 하나로 합쳐졌다
        for r, rr in zip(receipts, result.receipts, strict=True):
            assert sum(rr.owed.values()) == r.total
            for item in r.items:
                assert sum(s.amount for s in result.shares if s.item_id == item.id) == item.amount
            if unit == 10:
                assert all(v % 10 == 0 for m, v in rr.owed.items() if m != r.payer_id)
        # 같은 입력이면 같은 결과
        assert compute(members, receipts, unit) == result
