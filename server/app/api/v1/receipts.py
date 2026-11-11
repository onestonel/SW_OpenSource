"""영수증 입력 · 확인 · 확정 API (V1 요구 명세 2 · 3단계 · API 명세서 3절). 사진은 따로 (photos).

- 만들면 '확인 중'(CHECKING). 확인 중일 때만 고치기 · 지우기 · 확정을 할 수 있다.
- 확정(CONFIRMED)된 영수증만 정산에 들어간다. 고치려면 먼저 '확정 취소'.
- 품목 합 ≠ 총액이어도 막지 않는다. 답장의 check로 알려 주고, 정산은 총액 기준으로 차액까지 나눈다.
- 품목(ITEM) 줄은 만들 때 모든 구성원이 체크된 채로 시작한다 (체크 표에서 바꾼다). 할인 줄은 체크하지 않는다.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Response
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ...core.errors import AppError, validation_error
from ...models import Member, Receipt, ReceiptItem, ReceiptItemPayer, Room
from ...schemas import PayerOut, ReceiptCheckOut, ReceiptIn, ReceiptItemOut, ReceiptOut
from ..deps import DB, CurrentRoom

router = APIRouter(prefix="/rooms/{room_token}/receipts", tags=["receipts"])


def receipt_out(room: Room, r: Receipt) -> ReceiptOut:
    items_sum = sum(i.amount for i in r.items)
    photo = f"/api/v1/rooms/{room.room_token}/receipts/{r.id}/photo" if r.photo_path else None
    return ReceiptOut(
        id=r.id, store_name=r.store_name, payer=PayerOut(id=r.payer.id, name=r.payer.name), status=r.status,
        total_amount=r.total_amount,
        items=[ReceiptItemOut(id=i.id, name=i.name, amount=i.amount, kind=i.kind) for i in r.items],
        check=ReceiptCheckOut(items_sum=items_sum, difference=r.total_amount - items_sum,
                              is_matched=items_sum == r.total_amount),
        photo_url=photo, created_at=r.created_at,
    )


def receipt_of(
    db: DB, room: CurrentRoom, receipt_id: Annotated[int, Path(description="영수증 id")],
) -> Receipt:
    """주소의 영수증 찾기. 다른 정산방의 영수증이면 없는 것과 같이 404."""
    receipt = db.get(Receipt, receipt_id)
    if receipt is None or receipt.room_id != room.id:
        raise AppError(404, "NOT_FOUND", "영수증을 찾을 수 없습니다.")
    return receipt


CurrentReceipt = Annotated[Receipt, Depends(receipt_of)]


def _confirmed_error() -> AppError:
    return AppError(409, "RECEIPT_CONFIRMED", "확정된 영수증은 고치거나 지울 수 없습니다. 먼저 '확정 취소'를 눌러 주세요.")


def _check_payer(db, room: Room, payer_id: int) -> None:
    payer = db.get(Member, payer_id)
    if payer is None or payer.room_id != room.id:
        raise validation_error("payer_member_id", "이 정산방 구성원이 아닙니다", "결제자를 골라주세요.")


def _all_checked(room: Room) -> list[ReceiptItemPayer]:
    return [ReceiptItemPayer(member_id=m.id) for m in room.members]


def _new_item(room: Room, line, position: int) -> ReceiptItem:
    item = ReceiptItem(name=line.name, amount=line.amount, kind=line.kind, position=position)
    if line.kind == "ITEM":
        item.payers = _all_checked(room)
    return item


# ------------------------------------------------------------------ 목록 · 만들기 · 보기

@router.get("", response_model=list[ReceiptOut], summary="영수증 목록")
def list_receipts(room: CurrentRoom, db: DB) -> list[ReceiptOut]:
    """만든 순서대로. 확인 중 · 확정 영수증을 모두 돌려준다."""
    receipts = db.scalars(
        select(Receipt).where(Receipt.room_id == room.id).order_by(Receipt.id)
        .options(selectinload(Receipt.items), selectinload(Receipt.payer))
    ).all()
    return [receipt_out(room, r) for r in receipts]


@router.post("", response_model=ReceiptOut, status_code=201, summary="영수증 만들기 (상태: 확인 중)")
def create_receipt(body: ReceiptIn, room: CurrentRoom, db: DB) -> ReceiptOut:
    _check_payer(db, room, body.payer_member_id)
    for n, line in enumerate(body.items):
        if line.id is not None:
            raise validation_error(f"items.{n}.id", "새 영수증에는 줄 id를 보낼 수 없습니다")
    receipt = Receipt(room_id=room.id, store_name=body.store_name, payer_member_id=body.payer_member_id,
                      total_amount=body.total_amount, status="CHECKING")
    receipt.items = [_new_item(room, line, n) for n, line in enumerate(body.items, start=1)]
    db.add(receipt)
    db.commit()
    db.refresh(receipt)
    return receipt_out(room, receipt)


@router.get("/{receipt_id}", response_model=ReceiptOut, summary="영수증 하나 보기")
def get_receipt(room: CurrentRoom, receipt: CurrentReceipt) -> ReceiptOut:
    return receipt_out(room, receipt)


# ------------------------------------------------------------------ 고치기 · 지우기 (확인 중일 때만)

@router.put("/{receipt_id}", response_model=ReceiptOut, summary="영수증 통째로 고치기 (확인 중일 때만)")
def update_receipt(body: ReceiptIn, room: CurrentRoom, receipt: CurrentReceipt, db: DB) -> ReceiptOut:
    """
    - `id`가 있는 줄 → 고침 (체크 그대로 유지)
    - `id`가 없는 줄 → 새 줄 (모든 구성원 체크로 시작)
    - 보내지 않은 기존 줄 → 지움 (그 줄의 체크도 지움)

    할인 줄을 품목으로 바꾸면 새 줄처럼 모든 구성원 체크로 시작하고, 품목을 할인으로 바꾸면 체크를 지운다.
    """
    if receipt.status == "CONFIRMED":
        raise _confirmed_error()
    _check_payer(db, room, body.payer_member_id)
    existing = {i.id: i for i in receipt.items}
    for n, line in enumerate(body.items):
        if line.id is not None and line.id not in existing:
            raise validation_error(f"items.{n}.id", "이 영수증에 없는 줄입니다")

    items: list[ReceiptItem] = []
    for position, line in enumerate(body.items, start=1):
        if line.id is None:
            items.append(_new_item(room, line, position))
            continue
        item = existing[line.id]
        if item.kind != line.kind:
            item.payers = _all_checked(room) if line.kind == "ITEM" else []
        item.name, item.amount, item.kind, item.position = line.name, line.amount, line.kind, position
        items.append(item)

    receipt.store_name = body.store_name
    receipt.payer_member_id = body.payer_member_id
    receipt.total_amount = body.total_amount
    receipt.items = items  # 빠진 줄은 delete-orphan으로 지워지고, 체크는 ON DELETE CASCADE로 같이 지워진다
    db.commit()
    db.refresh(receipt)
    return receipt_out(room, receipt)


@router.delete("/{receipt_id}", status_code=204, summary="영수증 지우기 (확인 중일 때만)")
def delete_receipt(receipt: CurrentReceipt, db: DB) -> Response:
    if receipt.status == "CONFIRMED":
        raise _confirmed_error()
    # 사진 파일 지우기는 사진 PR(#21)이 영수증 주소로 옮겨 올 때 같이 붙인다
    db.delete(receipt)
    db.commit()
    return Response(status_code=204)


# ------------------------------------------------------------------ 확정 · 확정 취소

@router.post("/{receipt_id}/confirm", response_model=ReceiptOut, summary="확정")
def confirm_receipt(room: CurrentRoom, receipt: CurrentReceipt, db: DB) -> ReceiptOut:
    """품목 합 ≠ 총액이어도 확정된다. 이미 확정된 영수증이면 그대로 돌려준다."""
    if receipt.status != "CONFIRMED":
        receipt.status = "CONFIRMED"  # 정산 결과 PR에서: 최신 정산을 '최신 아님'으로
        db.commit()
        db.refresh(receipt)
    return receipt_out(room, receipt)


@router.post("/{receipt_id}/unconfirm", response_model=ReceiptOut, summary="확정 취소 (확인 중으로 되돌림)")
def unconfirm_receipt(room: CurrentRoom, receipt: CurrentReceipt, db: DB) -> ReceiptOut:
    if receipt.status != "CONFIRMED":
        raise AppError(409, "RECEIPT_NOT_CONFIRMED", "확정된 영수증만 확정 취소할 수 있습니다.")
    receipt.status = "CHECKING"  # 정산 결과 PR에서: 최신 정산을 '최신 아님'으로
    db.commit()
    db.refresh(receipt)
    return receipt_out(room, receipt)
