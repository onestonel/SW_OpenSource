"""정산 결과 API (V1 요구 명세 5단계 · API 명세서 5절).

- 총무가 '다시 계산'을 누를 때만 계산한다 (자동 계산 없음). 확정된 영수증과 체크만 쓴다.
- 품목 금액은 체크된 사람 수로, 차액 · 할인은 그 영수증 참여자 수로 나눈다. 원 단위는 정산방 설정을 따른다.
  (계산 규칙은 app/engine — 노션 예시 1 · 2와 같은 답을 낸다)
- 영수증마다 '누가 → 결제자에게 얼마'를 만들고, 같은 두 사람 사이는 하나로 합친다.
- 결과는 새 버전 번호와 계산 시각을 붙여 저장하고, 최신 버전만 보여 준다.
"""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from ... import engine
from ...core.errors import AppError
from ...models import Receipt, ReceiptItem, Room, Settlement
from ...schemas import SettlementOut
from ...settlement_store import latest_settlement
from ..deps import DB, CurrentRoom

router = APIRouter(prefix="/rooms/{room_token}/settlements", tags=["settlements"])

ROUNDING_UNIT = {"WON_1": 1, "WON_10": 10}
VERSION_RETRIES = 3  # 두 사람이 동시에 '다시 계산'을 눌러 같은 버전 번호가 나오면 다시 시도한다


def _engine_receipt(r: Receipt) -> engine.Receipt:
    items = tuple(
        engine.Item(i.id, i.name, i.amount, i.kind,
                    tuple(sorted(p.member_id for p in i.payers)) if i.kind == engine.ITEM else ())
        for i in r.items
    )
    return engine.Receipt(r.id, r.store_name, r.payer_member_id, r.total_amount, items)


def copy_text(room_name: str, version: int, transfers: list[dict]) -> str:
    lines = [f"[같이정산 · {room_name} · 버전 {version}]"]
    lines += [f"{t['from']['name']} → {t['to']['name']} {t['amount']:,}원" for t in transfers]
    if not transfers:
        lines.append("주고받을 돈이 없습니다.")
    return "\n".join(lines)


def calculate(room: Room, receipts: list[Receipt], version: int) -> dict:
    """확정 영수증으로 계산해서 저장할 결과(답장에서 version · created_at · rounding · is_stale을 뺀 것)를 만든다."""
    confirmed = [r for r in receipts if r.status == "CONFIRMED"]
    if not confirmed:
        raise AppError(422, "NO_CONFIRMED_RECEIPTS", "확정된 영수증이 없습니다. 영수증을 먼저 확정해 주세요.")

    members = [engine.Member(m.id, m.name, m.display_order) for m in room.members]
    try:
        result = engine.compute(members, [_engine_receipt(r) for r in confirmed], ROUNDING_UNIT[room.rounding])
    except engine.SettlementInputError as e:
        code = "CHECK_EMPTY" if e.code == "CHECK_EMPTY" else "VALIDATION_ERROR"
        raise AppError(422, code, e.message, e.details) from e

    names = {m.id: m.name for m in room.members}
    transfers = [{"from": {"id": t.from_id, "name": names[t.from_id]}, "to": {"id": t.to_id, "name": names[t.to_id]},
                  "amount": t.amount} for t in result.transfers]
    return {
        "members": [{"member_id": b.member_id, "name": names[b.member_id], "paid": b.paid, "owed": b.owed,
                     "net": b.net} for b in result.balances],
        "transfers": transfers,
        "excluded_receipts": [{"id": r.id, "store_name": r.store_name} for r in receipts if r.status != "CONFIRMED"],
        "copy_text": copy_text(room.name, version, transfers),
    }


def settlement_out(s: Settlement) -> SettlementOut:
    return SettlementOut.model_validate({**s.result, "version": s.version, "created_at": s.created_at,
                                         "rounding": s.rounding, "is_stale": s.is_stale})


@router.post("", response_model=SettlementOut, status_code=201, summary="다시 계산 → 새 버전 저장")
def recalculate(room: CurrentRoom, db: DB) -> SettlementOut:
    """확정된 영수증과 체크로 계산하고 새 버전으로 저장한다. 확정된 영수증이 없으면 `422 NO_CONFIRMED_RECEIPTS`."""
    receipts = list(db.scalars(
        select(Receipt).where(Receipt.room_id == room.id).order_by(Receipt.id)
        .options(selectinload(Receipt.items).selectinload(ReceiptItem.payers))
    ).all())
    for attempt in range(VERSION_RETRIES):
        version = (db.scalar(select(func.max(Settlement.version)).where(Settlement.room_id == room.id)) or 0) + 1
        row = Settlement(room_id=room.id, version=version, rounding=room.rounding,
                         result=calculate(room, receipts, version))
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            if attempt == VERSION_RETRIES - 1:
                raise
            continue
        db.refresh(row)
        return settlement_out(row)
    raise AssertionError("unreachable")


@router.get("/latest", response_model=SettlementOut, summary="최신 결과 보기")
def get_latest(room: CurrentRoom, db: DB) -> SettlementOut:
    """`is_stale`이 true면 화면 위에 '최신 결과가 아닙니다. 다시 계산을 눌러주세요'. 한 번도 계산하지 않았으면 404."""
    s = latest_settlement(db, room.id)
    if s is None:
        raise AppError(404, "NOT_FOUND", "아직 계산한 정산 결과가 없습니다. '다시 계산'을 눌러 주세요.")
    return settlement_out(s)
