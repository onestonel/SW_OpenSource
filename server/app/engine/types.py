"""엔진 입력 타입. DB 모델과 분리해 두어 엔진만 따로 테스트할 수 있다."""

from __future__ import annotations

from dataclasses import dataclass, field

ITEM = "ITEM"
DISCOUNT = "DISCOUNT"


@dataclass(frozen=True)
class Member:
    id: int
    name: str
    order: int  # display_order. 남는 1원을 내는 순서, 송금 목록 정렬 기준


@dataclass(frozen=True)
class Item:
    id: int
    name: str
    amount: int  # 정수 원. 할인 줄은 음수
    kind: str = ITEM
    payer_ids: tuple[int, ...] = ()  # 품목: 체크된 사람. 할인: 비어 있으면 그 영수증 참여자 (V3에서 규칙을 붙일 자리)


@dataclass(frozen=True)
class Receipt:
    id: int
    title: str
    payer_id: int
    total: int  # 정산은 총액 기준이다
    items: tuple[Item, ...] = field(default_factory=tuple)
