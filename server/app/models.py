"""DB 테이블. V1 요구 명세 순서대로 늘려 간다 (지금: ① 정산방 · 구성원, ②~④ 영수증 · 품목 · 품목별 내는 사람).

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
RECEIPT_STATUSES = ("CHECKING", "CONFIRMED")  # 확인 중 / 확정 (확정된 영수증만 정산에 들어간다)
ITEM_KINDS = ("ITEM", "DISCOUNT")  # 품목 / 할인 줄 (할인은 금액이 음수)


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
    receipts: Mapped[list[Receipt]] = relationship(
        back_populates="room", order_by="Receipt.id", cascade="all, delete-orphan", passive_deletes=True,
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


class Receipt(Base):
    """영수증 한 장. 결제자 한 명이 총액을 냈다. 정산은 품목 합이 아니라 총액 기준이다.

    결제자로 쓰인 구성원은 지울 수 없다 (API: 409 MEMBER_IN_USE, DB: ON DELETE RESTRICT).
    """

    __tablename__ = "receipts"
    __table_args__ = (
        CheckConstraint("status IN ('CHECKING', 'CONFIRMED')", name="ck_receipts_status"),
        CheckConstraint("total_amount > 0", name="ck_receipts_total_positive"),
    )

    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id", ondelete="CASCADE"), index=True)
    store_name: Mapped[str] = mapped_column(String(50))
    payer_member_id: Mapped[int] = mapped_column(ForeignKey("members.id", ondelete="RESTRICT"), index=True)
    total_amount: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(10), default="CHECKING", server_default="CHECKING")
    photo_path: Mapped[str | None] = mapped_column(String(255))  # RECEIPT_STORAGE_PATH 안의 파일 이름 (사진은 선택)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TS, default=utcnow, onupdate=utcnow)

    room: Mapped[Room] = relationship(back_populates="receipts")
    payer: Mapped[Member] = relationship()
    items: Mapped[list[ReceiptItem]] = relationship(
        back_populates="receipt", order_by="(ReceiptItem.position, ReceiptItem.id)",
        cascade="all, delete-orphan", passive_deletes=True,
    )


class ReceiptItem(Base):
    """영수증의 한 줄. kind=ITEM이면 품목(금액 > 0), DISCOUNT면 할인(금액 < 0).

    position은 영수증 안에서 보여 주는 순서다 (입력한 순서대로 1, 2, 3…).
    """

    __tablename__ = "receipt_items"
    __table_args__ = (
        CheckConstraint("kind IN ('ITEM', 'DISCOUNT')", name="ck_receipt_items_kind"),
        CheckConstraint("(kind = 'ITEM' AND amount > 0) OR (kind = 'DISCOUNT' AND amount < 0)",
                        name="ck_receipt_items_amount_sign"),
    )

    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    receipt_id: Mapped[int] = mapped_column(ForeignKey("receipts.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(50))
    amount: Mapped[int] = mapped_column(BigInteger)
    kind: Mapped[str] = mapped_column(String(10), default="ITEM", server_default="ITEM")
    position: Mapped[int] = mapped_column(Integer)

    receipt: Mapped[Receipt] = relationship(back_populates="items")
    payers: Mapped[list[ReceiptItemPayer]] = relationship(
        back_populates="item", cascade="all, delete-orphan", passive_deletes=True,
    )


class ReceiptItemPayer(Base):
    """품목별 내는 사람 (체크 표의 체크 한 칸). 행이 있으면 그 구성원이 그 품목을 나눠 낸다.

    품목이나 구성원이 지워지면 체크도 같이 지워진다 (ON DELETE CASCADE).
    V1에서 할인 줄에는 행을 만들지 않는다 (그 영수증 참여자끼리 나눈다).
    """

    __tablename__ = "receipt_item_payers"

    receipt_item_id: Mapped[int] = mapped_column(ForeignKey("receipt_items.id", ondelete="CASCADE"),
                                                 primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"), primary_key=True,
                                           index=True)

    item: Mapped[ReceiptItem] = relationship(back_populates="payers")
