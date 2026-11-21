"""금액을 여러 명이 똑같이 나눈다 (정수 원).

몫 = floor(금액 / 인원). 남는 돈(0 ~ 인원−1원)은 구성원 순서대로 1원씩 더 낸다.
할인처럼 음수여도 같다: −1,000원 ÷ 3 → 몫 −334, 남는 2원을 앞의 두 명이 더 내서 −333 / −333 / −334.
몫의 합은 항상 금액과 같다.
"""

from __future__ import annotations

from collections.abc import Sequence

from .types import Member


def split_equal(amount: int, members: Sequence[Member]) -> dict[int, int]:
    """{member_id: 몫}. members는 나눌 사람 (순서는 이 함수가 display_order·id로 정한다)."""
    if not members:
        raise ValueError("split needs at least one member")
    if len({m.id for m in members}) != len(members):
        raise ValueError("duplicate member")
    ordered = sorted(members, key=lambda m: (m.order, m.id))
    base, remainder = divmod(amount, len(ordered))  # floor 나눗셈이라 remainder는 항상 0 이상
    return {m.id: base + (1 if n < remainder else 0) for n, m in enumerate(ordered)}


def round_up(amount: int, unit: int) -> int:
    """unit원 단위로 올린다. 음수도 올림(0 쪽)이다: −15 → −10."""
    return -(-amount // unit) * unit
