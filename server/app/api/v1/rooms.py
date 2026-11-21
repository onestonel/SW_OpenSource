"""정산방 · 구성원 API (V1 요구 명세 1단계 · API 약속서 2장).

- 로그인이 없다. 정산방을 만들면 room_token이 나오고, 총무는 이 키가 든 링크로 다시 들어온다.
- 정산방을 만들 때 구성원 이름을 함께 받는다. 서버 검사: 2명 이상, 빈 이름 없음 (422). 같은 이름은 409.
- 원 단위 rounding: WON_1 = 1원 단위(기본), WON_10 = 10원 단위 올림.
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from ...core.errors import AppError
from ...models import Member, Receipt, ReceiptItem, ReceiptItemPayer, Room
from ...schemas import (
    LatestSettlementRef,
    MemberCreateIn,
    MemberOut,
    RoomCreateIn,
    RoomDetailOut,
    RoomOut,
    RoomUpdateIn,
)
from ...settlement_store import latest_settlement, mark_stale
from ..deps import DB, CurrentRoom

router = APIRouter(prefix="/rooms", tags=["rooms"])

MIN_MEMBERS = 2


def _new_token(db) -> str:
    """URL에 그대로 쓸 수 있는 22자 무작위 키 (128비트). 겹치면 다시 뽑는다."""
    while True:
        token = secrets.token_urlsafe(16)
        if db.scalar(select(Room.id).where(Room.room_token == token)) is None:
            return token


def _member(m: Member) -> MemberOut:
    return MemberOut(id=m.id, name=m.name, order=m.display_order)


def _room(room: Room) -> RoomOut:
    return RoomOut(room_token=room.room_token, name=room.name, rounding=room.rounding,
                   members=[_member(m) for m in room.members], created_at=room.created_at)


def _detail(db, room: Room) -> RoomDetailOut:
    s = latest_settlement(db, room.id)
    ref = LatestSettlementRef(version=s.version, is_stale=s.is_stale) if s else None
    return RoomDetailOut(**_room(room).model_dump(), latest_settlement=ref)


# ------------------------------------------------------------------ 정산방

@router.post("", response_model=RoomOut, status_code=201, summary="정산방 만들기")
def create_room(body: RoomCreateIn, db: DB) -> RoomOut:
    dup = sorted({n for n in body.members if body.members.count(n) > 1})
    if dup:  # API 명세서 2절: 구성원 추가와 같은 409
        raise AppError(409, "MEMBER_NAME_DUPLICATE", f"같은 이름의 구성원이 있습니다: {', '.join(dup)}",
                       {"names": dup})
    room = Room(room_token=_new_token(db), name=body.name, rounding=body.rounding)
    room.members = [Member(name=n, display_order=i) for i, n in enumerate(body.members, start=1)]
    db.add(room)
    db.commit()
    db.refresh(room)
    return _room(room)


@router.get("/{room_token}", response_model=RoomDetailOut, summary="정산방 정보 보기")
def get_room(room: CurrentRoom, db: DB) -> RoomDetailOut:
    return _detail(db, room)


@router.patch("/{room_token}", response_model=RoomDetailOut, summary="이름 · 원 단위 바꾸기")
def update_room(body: RoomUpdateIn, room: CurrentRoom, db: DB) -> RoomDetailOut:
    if body.name is not None:
        room.name = body.name
    if body.rounding is not None and body.rounding != room.rounding:
        room.rounding = body.rounding
        mark_stale(db, room.id)
    db.commit()
    db.refresh(room)
    return _detail(db, room)


# ------------------------------------------------------------------ 구성원

def _items_only_checked_by(db, member: Member) -> list[ReceiptItem]:
    """이 구성원 한 명만 체크된 품목(ITEM) 줄. 할인 줄은 원래 체크가 없으므로 보지 않는다."""
    items = db.scalars(
        select(ReceiptItem).join(ReceiptItemPayer)
        .where(ReceiptItemPayer.member_id == member.id, ReceiptItem.kind == "ITEM")
        .options(selectinload(ReceiptItem.payers), selectinload(ReceiptItem.receipt))
        .order_by(ReceiptItem.receipt_id, ReceiptItem.position, ReceiptItem.id)
    ).all()
    return [i for i in items if len(i.payers) == 1]


@router.post("/{room_token}/members", response_model=MemberOut, status_code=201, summary="구성원 추가")
def add_member(body: MemberCreateIn, room: CurrentRoom, db: DB) -> MemberOut:
    """새 구성원은 맨 뒤 순서. 이미 있는 품목 체크에는 들어가지 않는다 (체크 표에서 켠다)."""
    duplicate = AppError(409, "MEMBER_NAME_DUPLICATE", "같은 이름의 구성원이 이미 있습니다.")
    if db.scalar(select(Member.id).where(Member.room_id == room.id, Member.name == body.name)) is not None:
        raise duplicate
    last = db.scalar(select(func.max(Member.display_order)).where(Member.room_id == room.id)) or 0
    member = Member(room_id=room.id, name=body.name, display_order=last + 1)
    db.add(member)
    mark_stale(db, room.id)
    try:
        db.commit()
    except IntegrityError as e:  # 동시에 같은 이름을 추가한 경우
        db.rollback()
        raise duplicate from e
    return _member(member)


@router.delete("/{room_token}/members/{member_id}", status_code=204, summary="구성원 삭제")
def delete_member(member_id: int, room: CurrentRoom, db: DB) -> Response:
    """이 사람이 체크된 품목에서도 체크를 같이 지운다 (ON DELETE CASCADE).

    이 사람만 체크된 품목이 있으면 지우지 않는다 (지우면 아무도 체크하지 않은 품목이 생긴다).
    확인 중인 영수증의 품목도 본다. 나중에 확정하면 그대로 계산에 들어가기 때문이다.
    """
    member = db.get(Member, member_id)
    if member is None or member.room_id != room.id:
        raise AppError(404, "NOT_FOUND", "구성원을 찾을 수 없습니다.")
    count = db.scalar(select(func.count(Member.id)).where(Member.room_id == room.id))
    if count <= MIN_MEMBERS:
        raise AppError(409, "MEMBERS_TOO_FEW", f"정산방에는 구성원이 {MIN_MEMBERS}명 이상 있어야 합니다.")
    paid = db.scalars(select(Receipt).where(Receipt.payer_member_id == member.id).order_by(Receipt.id)).all()
    if paid:
        names = ", ".join(r.store_name for r in paid)
        raise AppError(409, "MEMBER_IN_USE",
                       f"영수증 결제자로 들어가 있어 지울 수 없습니다. 먼저 결제자를 바꿔 주세요. (영수증: {names})",
                       {"receipt_ids": [r.id for r in paid]})
    only_me = _items_only_checked_by(db, member)
    if only_me:
        names = ", ".join(f"{i.receipt.store_name} - {i.name}" for i in only_me)
        raise AppError(409, "MEMBER_IN_USE",
                       f"이 사람만 체크된 품목이 있어 지울 수 없습니다. 먼저 다른 사람도 체크해 주세요. (품목: {names})",
                       {"item_ids": [i.id for i in only_me]})
    db.delete(member)
    mark_stale(db, room.id)
    db.commit()
    return Response(status_code=204)
