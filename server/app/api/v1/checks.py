"""분담 조건 — 체크 표 받기 · 저장 API (V1 요구 명세 4단계 · API 명세서 4절).

- 확정된 영수증의 품목(ITEM) 줄만 체크 표에 나온다. 할인 줄은 그 영수증 참여자끼리 똑같이 나누므로 체크하지 않는다.
- 저장할 때는 바뀐 품목만 보내도 된다. 보낸 품목의 체크는 member_ids로 통째로 바꾸고, 보내지 않은 품목은 그대로 둔다.
- 하나라도 틀리면 아무것도 바꾸지 않는다 (모두 검사한 뒤에 바꾼다).
"""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ...core.errors import AppError, validation_error
from ...models import Receipt, ReceiptItem, ReceiptItemPayer, Room
from ...schemas import CheckItemOut, CheckMemberOut, ChecksIn, ChecksOut
from ...settlement_store import mark_stale
from ..deps import DB, CurrentRoom

router = APIRouter(prefix="/rooms/{room_token}/checks", tags=["checks"])


def _checks_out(db, room: Room) -> ChecksOut:
    order = {m.id: m.display_order for m in room.members}
    receipts = db.scalars(
        select(Receipt).where(Receipt.room_id == room.id, Receipt.status == "CONFIRMED").order_by(Receipt.id)
        .options(selectinload(Receipt.items).selectinload(ReceiptItem.payers))
    ).all()
    items = [
        CheckItemOut(item_id=i.id, receipt_id=r.id, store_name=r.store_name, name=i.name, amount=i.amount,
                     member_ids=sorted((p.member_id for p in i.payers), key=order.__getitem__))
        for r in receipts for i in r.items if i.kind == "ITEM"
    ]
    return ChecksOut(members=[CheckMemberOut(id=m.id, name=m.name) for m in room.members], items=items)


@router.get("", response_model=ChecksOut, summary="체크 표 받기 (확정된 영수증의 품목만)")
def get_checks(room: CurrentRoom, db: DB) -> ChecksOut:
    return _checks_out(db, room)


@router.put("", response_model=ChecksOut, summary="체크 표 저장 (바뀐 품목만 보내도 된다)")
def save_checks(body: ChecksIn, room: CurrentRoom, db: DB) -> ChecksOut:
    """
    - 품목마다 1명 이상 체크 (아니면 `422 CHECK_EMPTY`)
    - 없는 품목 · 확정하지 않은 영수증의 품목 · 정산방에 없는 구성원이면 `422 VALIDATION_ERROR`
    - 저장하면 최신 정산을 '최신 아님'으로 만든다
    """
    empty = [line.item_id for line in body.items if not line.member_ids]
    if empty:
        raise AppError(422, "CHECK_EMPTY", "아무도 체크하지 않은 품목이 있습니다. 품목마다 1명 이상 체크해 주세요.",
                       {"item_ids": empty})

    found = db.scalars(
        select(ReceiptItem).join(Receipt).where(ReceiptItem.id.in_([line.item_id for line in body.items]))
        .options(selectinload(ReceiptItem.payers))
    ).all()
    items = {i.id: i for i in found}
    member_ids = {m.id for m in room.members}
    seen: set[int] = set()
    for n, line in enumerate(body.items):
        item = items.get(line.item_id)
        if item is None or item.receipt.room_id != room.id or item.kind != "ITEM":
            raise validation_error(f"items.{n}.item_id", "이 정산방에 없는 품목입니다")
        if item.receipt.status != "CONFIRMED":
            raise validation_error(f"items.{n}.item_id", "확정하지 않은 영수증의 품목입니다",
                                   "확정된 영수증의 품목만 체크할 수 있습니다.")
        if line.item_id in seen:
            raise validation_error(f"items.{n}.item_id", "같은 품목을 두 번 보냈습니다")
        seen.add(line.item_id)
        if not set(line.member_ids) <= member_ids:
            raise validation_error(f"items.{n}.member_ids", "이 정산방 구성원이 아닌 id가 있습니다")

    for line in body.items:
        item = items[line.item_id]
        wanted = set(line.member_ids)
        # 통째로 새 목록을 넣으면 같은 (품목, 구성원) 행을 지웠다가 다시 넣게 되므로, 달라진 칸만 바꾼다
        item.payers = [p for p in item.payers if p.member_id in wanted]
        have = {p.member_id for p in item.payers}
        item.payers += [ReceiptItemPayer(member_id=m) for m in sorted(wanted - have)]
    mark_stale(db, room.id)
    db.commit()
    db.expire_all()
    return _checks_out(db, room)
