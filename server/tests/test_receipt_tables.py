"""영수증 · 품목 · 품목별 내는 사람 테이블 (마이그레이션 0002). DB 제약이 명세와 같은지 확인한다."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import Base, make_engine
from app.models import Member, Receipt, ReceiptItem, ReceiptItemPayer, Room


@pytest.fixture
def db():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def make_room(db) -> tuple[Room, list[Member]]:
    room = Room(room_token="t", name="제주 여행")
    room.members = [Member(name=n, display_order=i) for i, n in enumerate("ABC", start=1)]
    db.add(room)
    db.flush()
    return room, room.members


def make_receipt(db, room, payer, members) -> Receipt:
    receipt = Receipt(room_id=room.id, store_name="1차 식당", payer_member_id=payer.id, total_amount=15000)
    receipt.items = [
        ReceiptItem(name="김치찌개", amount=10000, kind="ITEM", position=1),
        ReceiptItem(name="할인", amount=-1000, kind="DISCOUNT", position=2),
    ]
    db.add(receipt)
    db.flush()
    receipt.items[0].payers = [ReceiptItemPayer(member_id=m.id) for m in members]
    db.commit()
    return receipt


def test_defaults_and_order(db):
    room, (a, b, c) = make_room(db)
    receipt = make_receipt(db, room, a, [a, b, c])
    db.refresh(receipt)
    assert receipt.status == "CHECKING" and receipt.photo_path is None
    assert [i.name for i in receipt.items] == ["김치찌개", "할인"]
    assert {p.member_id for p in receipt.items[0].payers} == {a.id, b.id, c.id}
    assert receipt.payer.name == "A"


def test_payer_cannot_be_deleted(db):
    room, (a, b, c) = make_room(db)
    make_receipt(db, room, a, [a, b])
    db.delete(a)
    with pytest.raises(IntegrityError):
        db.commit()


def test_deleting_member_removes_checks(db):
    room, (a, b, c) = make_room(db)
    receipt = make_receipt(db, room, a, [a, b, c])
    db.delete(c)
    db.commit()
    assert db.scalar(select(func.count()).select_from(ReceiptItemPayer)) == 2
    db.refresh(receipt.items[0])
    assert {p.member_id for p in receipt.items[0].payers} == {a.id, b.id}


def test_deleting_receipt_removes_items_and_checks(db):
    room, (a, b, c) = make_room(db)
    receipt = make_receipt(db, room, a, [a, b, c])
    db.delete(receipt)
    db.commit()
    assert db.scalar(select(func.count()).select_from(ReceiptItem)) == 0
    assert db.scalar(select(func.count()).select_from(ReceiptItemPayer)) == 0


@pytest.mark.parametrize(("kind", "amount"), [("ITEM", 0), ("ITEM", -100), ("DISCOUNT", 100), ("TAX", 100)])
def test_item_kind_and_sign(db, kind, amount):
    room, (a, b, c) = make_room(db)
    receipt = make_receipt(db, room, a, [a])
    db.add(ReceiptItem(receipt_id=receipt.id, name="x", amount=amount, kind=kind, position=3))
    with pytest.raises(IntegrityError):
        db.commit()


@pytest.mark.parametrize(("field", "value"), [("status", "DONE"), ("total_amount", 0)])
def test_receipt_status_and_total(db, field, value):
    room, (a, b, c) = make_room(db)
    receipt = make_receipt(db, room, a, [a])
    setattr(receipt, field, value)
    with pytest.raises(IntegrityError):
        db.commit()
