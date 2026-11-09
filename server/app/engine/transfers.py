"""송금 목록 (V1 요구 명세 5단계).

영수증마다 '참여자 → 결제자에게 얼마'를 만들고, 같은 두 사람 사이는 하나로 합친다.
A→B 25,000원과 B→A 21,667원이 있으면 A→B 3,333원 한 건이 된다.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from .types import Member


@dataclass(frozen=True)
class Transfer:
    from_id: int
    to_id: int
    amount: int


def merge_transfers(raw: Iterable[Transfer], members: Mapping[int, Member]) -> list[Transfer]:
    """같은 두 사람 사이 송금을 합친다. 0원은 뺀다. 순서: 보내는 사람 → 받는 사람 (구성원 순서)."""
    def key(mid: int) -> tuple[int, int]:
        return (members[mid].order, mid)

    pair: dict[tuple[int, int], int] = {}  # (앞 사람, 뒤 사람) → 앞 사람이 보낼 돈 (음수면 받을 돈)
    for t in raw:
        if t.from_id == t.to_id or t.amount == 0:
            continue
        a, b = sorted((t.from_id, t.to_id), key=key)
        pair[(a, b)] = pair.get((a, b), 0) + (t.amount if t.from_id == a else -t.amount)

    out = [Transfer(a, b, v) if v > 0 else Transfer(b, a, -v) for (a, b), v in pair.items() if v != 0]
    return sorted(out, key=lambda t: (key(t.from_id), key(t.to_id)))
