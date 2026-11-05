"""DB 테이블. V1 요구 명세 순서대로 늘려 간다 (지금: ① 정산방 · 구성원).

로그인이 없다. 정산방은 추측하기 어려운 room_token이 든 링크로만 찾는다.
테이블을 바꾸면 Alembic 마이그레이션을 같이 만든다 (server/migrations/versions/).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

# SQLite(테스트)는 INTEGER PRIMARY KEY만 자동 증가하므로 SQLite에서는 Integer로 만든다
BigId = BigInteger().with_variant(Integer(), "sqlite")
TS = DateTime(timezone=True)

ROUNDINGS = ("WON_1", "WON_10")  # 1원 단위(기본) / 10원 단위 올림


def utcnow() -> datetime:
    return datetime.now(UTC)


class Room(Base):
    """정산방."""

    __tablename__ = "rooms"
    __table_args__ = (
        UniqueConstraint("room_token", name="uq_rooms_room_token"),
        CheckConstraint("rounding IN ('WON_1', 'WON_10')", name="ck_rooms_rounding"),
    )

    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    room_token: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(50))
    rounding: Mapped[str] = mapped_column(String(8), default="WON_1", server_default="WON_1")
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)

    members: Mapped[list[Member]] = relationship(
        back_populates="room", order_by="(Member.display_order, Member.id)",
        cascade="all, delete-orphan", passive_deletes=True,
    )


class Member(Base):
    """정산방 구성원. display_order가 API의 order다 (남는 1원을 내는 순서, 송금 목록 정렬 기준)."""

    __tablename__ = "members"
    __table_args__ = (UniqueConstraint("room_id", "name", name="uq_members_room_name"),)

    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(20))
    display_order: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)

    room: Mapped[Room] = relationship(back_populates="members")
