"""정산방 · 구성원 API (V1 요구 명세 1단계 · API 약속서 2장).

- 로그인이 없다. 정산방을 만들면 room_token이 나오고, 총무는 이 키가 든 링크로 다시 들어온다.
- 정산방을 만들 때 구성원 이름을 함께 받는다. 서버 검사: 2명 이상, 빈 이름 없음 (같은 이름도 불가).
- 원 단위 rounding: WON_1 = 1원 단위(기본), WON_10 = 10원 단위 올림.
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from ...core.errors import AppError
from ...models import Member, Room
from ...schemas import MemberCreateIn, MemberOut, RoomCreateIn, RoomDetailOut, RoomOut, RoomUpdateIn
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


def _detail(room: Room) -> RoomDetailOut:
    # 정산 버전은 정산 결과 PR에서 채운다. 그 전까지는 항상 '아직 계산 안 함'
    return RoomDetailOut(**_room(room).model_dump(), latest_settlement=None)


# ------------------------------------------------------------------ 정산방

@router.post("", response_model=RoomOut, status_code=201, summary="정산방 만들기")
def create_room(body: RoomCreateIn, db: DB) -> RoomOut:
    room = Room(room_token=_new_token(db), name=body.name, rounding=body.rounding)
    room.members = [Member(name=n, display_order=i) for i, n in enumerate(body.members, start=1)]
    db.add(room)
    db.commit()
    db.refresh(room)
    return _room(room)


@router.get("/{room_token}", response_model=RoomDetailOut, summary="정산방 정보 보기")
def get_room(room: CurrentRoom) -> RoomDetailOut:
    return _detail(room)


@router.patch("/{room_token}", response_model=RoomDetailOut, summary="이름 · 원 단위 바꾸기")
def update_room(body: RoomUpdateIn, room: CurrentRoom, db: DB) -> RoomDetailOut:
    if body.name is not None:
        room.name = body.name
    if body.rounding is not None:
        room.rounding = body.rounding  # 정산 결과 PR에서: 바뀌면 최신 정산을 '최신 아님'으로
    db.commit()
    db.refresh(room)
    return _detail(room)


# ------------------------------------------------------------------ 구성원

@router.post("/{room_token}/members", response_model=MemberOut, status_code=201, summary="구성원 추가")
def add_member(body: MemberCreateIn, room: CurrentRoom, db: DB) -> MemberOut:
    """새 구성원은 맨 뒤 순서. 이미 있는 품목 체크에는 들어가지 않는다 (체크 표에서 켠다)."""
    duplicate = AppError(409, "MEMBER_NAME_DUPLICATE", "같은 이름의 구성원이 이미 있습니다.")
    if db.scalar(select(Member.id).where(Member.room_id == room.id, Member.name == body.name)) is not None:
        raise duplicate
    last = db.scalar(select(func.max(Member.display_order)).where(Member.room_id == room.id)) or 0
    member = Member(room_id=room.id, name=body.name, display_order=last + 1)
    db.add(member)
    try:
        db.commit()
    except IntegrityError as e:  # 동시에 같은 이름을 추가한 경우
        db.rollback()
        raise duplicate from e
    return _member(member)


@router.delete("/{room_token}/members/{member_id}", status_code=204, summary="구성원 삭제")
def delete_member(member_id: int, room: CurrentRoom, db: DB) -> Response:
    member = db.get(Member, member_id)
    if member is None or member.room_id != room.id:
        raise AppError(404, "NOT_FOUND", "구성원을 찾을 수 없습니다.")
    count = db.scalar(select(func.count(Member.id)).where(Member.room_id == room.id))
    if count <= MIN_MEMBERS:
        raise AppError(409, "MEMBERS_TOO_FEW", f"정산방에는 구성원이 {MIN_MEMBERS}명 이상 있어야 합니다.")
    # 결제자로 쓰인 구성원 삭제 금지(409 MEMBER_IN_USE)는 영수증 PR에서 더한다
    db.delete(member)
    db.commit()
    return Response(status_code=204)
