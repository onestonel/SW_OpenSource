"""API 함수가 공통으로 받는 값."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Path
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.errors import AppError
from ..db import get_db
from ..models import Room

DB = Annotated[Session, Depends(get_db)]


def room_of(
    db: DB,
    room_token: Annotated[str, Path(description="정산방 링크 키 (정산방 만들기 답장의 room_token)")],
) -> Room:
    """모든 /rooms/{room_token}/... API의 정산방 찾기. 키가 틀리면 404 (있는지 없는지 알려 주지 않는다)."""
    room = db.scalar(select(Room).where(Room.room_token == room_token))
    if room is None:
        raise AppError(404, "NOT_FOUND", "정산방을 찾을 수 없습니다. 링크를 확인해 주세요.")
    return room


CurrentRoom = Annotated[Room, Depends(room_of)]
