"""분담 조건 — 체크 표 받기 · 저장 API (V1 요구 명세 4단계 · API 명세서 4절).

- 확정된 영수증의 품목(ITEM) 줄만 체크 표에 나온다. 할인 줄은 그 영수증 참여자끼리 똑같이 나누므로 체크하지 않는다.
- 저장할 때는 바뀐 품목만 보내도 된다. 보낸 품목의 체크는 member_ids로 통째로 바꾸고, 보내지 않은 품목은 그대로 둔다.
- 하나라도 틀리면 아무것도 바꾸지 않는다 (모두 검사한 뒤에 바꾼다).
"""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ... import nl, nl_report
from ...core.errors import AppError, validation_error
from ...models import NlLog, Receipt, ReceiptItem, ReceiptItemPayer, Room, utcnow
from ...schemas import ApplyIn, CheckItemOut, CheckMemberOut, ChecksIn, ChecksOut, InterpretIn, InterpretOut
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


def _check_lines(db, room: Room, lines) -> dict[int, ReceiptItem]:
    """체크 저장 · 변경안 적용이 같이 쓰는 검사. 하나라도 틀리면 아무것도 바꾸지 않도록 먼저 모두 검사한다."""
    empty = [line.item_id for line in lines if not line.member_ids]
    if empty:
        raise AppError(422, "CHECK_EMPTY", "아무도 체크하지 않은 품목이 있습니다. 품목마다 1명 이상 체크해 주세요.",
                       {"item_ids": empty})

    found = db.scalars(
        select(ReceiptItem).join(Receipt).where(ReceiptItem.id.in_([line.item_id for line in lines]))
        .options(selectinload(ReceiptItem.payers))
    ).all()
    items = {i.id: i for i in found}
    member_ids = {m.id for m in room.members}
    seen: set[int] = set()
    for n, line in enumerate(lines):
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

    return items


def _set_payers(item: ReceiptItem, member_ids: list[int]) -> None:
    wanted = set(member_ids)
    # 통째로 새 목록을 넣으면 같은 (품목, 구성원) 행을 지웠다가 다시 넣게 되므로, 달라진 칸만 바꾼다
    item.payers = [p for p in item.payers if p.member_id in wanted]
    have = {p.member_id for p in item.payers}
    item.payers += [ReceiptItemPayer(member_id=m) for m in sorted(wanted - have)]


def _record_manual_fixes(db, room: Room, lines) -> None:
    """AI 변경안을 반영한 품목을 사용자가 체크 표에서 다르게 고치면, 그 반영 기록에 남긴다 (AI가 틀렸다는 신호)."""
    applied = db.scalars(select(NlLog).where(NlLog.room_id == room.id, NlLog.outcome == "APPLIED")
                         .order_by(NlLog.id.desc())).all()
    for line in lines:
        for entry in applied:  # 그 품목을 가장 최근에 바꾼 반영 기록 하나
            change = next((c for c in entry.changes if c["item_id"] == line.item_id), None)
            if change is None:
                continue
            if sorted(change["after_member_ids"]) != sorted(line.member_ids):
                entry.manual_fixes = [*entry.manual_fixes, {
                    "item_id": line.item_id, "name": change["name"], "ai_member_ids": change["after_member_ids"],
                    "user_member_ids": sorted(line.member_ids), "at": utcnow().isoformat()}]
            break


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
    items = _check_lines(db, room, body.items)
    _record_manual_fixes(db, room, body.items)
    for line in body.items:
        _set_payers(items[line.item_id], line.member_ids)
    mark_stale(db, room.id)
    db.commit()
    db.expire_all()
    return _checks_out(db, room)


@router.post("/interpret", response_model=InterpretOut, summary="문장으로 체크 표 바꾸기 — 변경안 받기 (저장하지 않음)")
def interpret_checks(body: InterpretIn, room: CurrentRoom, db: DB) -> InterpretOut:
    """
    "D는 술 안 마셨어" 같은 문장을 해석해서 체크 표 변경안을 돌려준다. **저장하지 않는다.**
    화면은 변경안을 보여 주고, 사용자가 적용을 누르면 `PUT /checks`로 `after_member_ids`를 보낸다.

    - V1에서 바꿀 수 있는 것: `~끼리만`(EQUAL) · `~ 빼고`(EXCLUDE) · `~가 다 낼게`(FULL)
    - 비율 · 수량 문장, 정산과 관계없는 문장 → `UNSUPPORTED`
    - 사람 · 품목을 정할 수 없거나, 모델이 문장에 없는 사람 · 품목을 만들면 → `NEEDS_CLARIFICATION`
    - 확정된 영수증이 없으면 `409 NO_CHECK_ITEMS`, 해석기에 연결하지 못하면 `503 NL_UNAVAILABLE`
    """
    checks = _checks_out(db, room)
    if not checks.items:
        raise AppError(409, "NO_CHECK_ITEMS", "확정된 영수증이 없어서 바꿀 품목이 없습니다. 영수증을 먼저 확정해 주세요.")
    payer_of = dict(db.execute(select(Receipt.id, Receipt.payer_member_id).where(Receipt.room_id == room.id)).all())
    data = nl.RoomData(
        members=[(m.id, m.name) for m in checks.members],
        items=[nl.Item(id=i.item_id, name=i.name, amount=i.amount, receipt_id=i.receipt_id,
                       store_name=i.store_name, member_ids=list(i.member_ids), payer_id=payer_of[i.receipt_id])
               for i in checks.items],
    )
    res = nl.interpret(data, body.text, body.previous)
    trace = res.pop("trace")
    answers_id = _record_outcomes_before(db, room, answered=bool(body.previous))
    entry = NlLog(room_id=room.id, text=res["text"][:600], answers_id=answers_id, provider=res["provider"],
                  raw=trace["raw"], model_rules=trace["model_rules"], final_rules=trace["final_rules"],
                  repairs=trace["repairs"], status=res["status"], changes=res["changes"],
                  elapsed_ms=res["elapsed_ms"], manual_fixes=[])
    db.add(entry)
    db.commit()
    return InterpretOut(**res, interpretation_id=entry.id)


def _record_outcomes_before(db, room: Room, answered: bool) -> int | None:
    """새로 말하기 전에, 앞에서 결과가 정해지지 않은 기록의 사용자 반응을 남긴다.

    되물음에 답하는 말이면 가장 최근 되물음을 ANSWERED로, 아니면 반영하지 않고 넘어간 변경안을 MOVED_ON으로 둔다.
    """
    pending = db.scalars(select(NlLog).where(NlLog.room_id == room.id, NlLog.outcome.is_(None))
                         .order_by(NlLog.id.desc())).all()
    answers_id = None
    for entry in pending:
        if answered and answers_id is None and entry.status == "NEEDS_CLARIFICATION":
            entry.outcome, entry.outcome_at, answers_id = "ANSWERED", utcnow(), entry.id
        elif entry.status == "PARSED" and entry.changes:
            entry.outcome, entry.outcome_at = "MOVED_ON", utcnow()
    return answers_id


@router.post("/apply", response_model=ChecksOut, summary="말로 바꾸기 변경안 적용 (체크 + 금액 저장)")
def apply_changes(body: ApplyIn, room: CurrentRoom, db: DB) -> ChecksOut:
    """
    `interpret`가 준 변경안을 저장한다. 체크는 `PUT /checks`와 같고, `amount`가 있으면 품목 금액도 바꾼다.

    - `amount`는 이미 보낸 돈을 뺀 남은 금액(PAID)이라서 **줄이기만** 된다. 늘리면 `422 VALIDATION_ERROR`
    - 금액을 줄인 만큼 그 영수증의 총액도 같이 줄인다 (영수증은 확정 상태 그대로)
    - 저장하면 최신 정산을 '최신 아님'으로 만든다
    """
    items = _check_lines(db, room, body.changes)  # 줄마다 item_id · member_ids가 있어서 체크 저장과 같이 검사한다
    for n, c in enumerate(body.changes):
        if c.amount is not None and c.amount > items[c.item_id].amount:
            raise validation_error(f"changes.{n}.amount", "품목 금액보다 클 수 없습니다",
                                   "이미 보낸 돈을 뺀 금액은 지금 금액보다 클 수 없습니다.")
    if body.interpretation_id is not None:
        entry = db.get(NlLog, body.interpretation_id)
        if entry is not None and entry.room_id == room.id:
            entry.outcome, entry.outcome_at = "APPLIED", utcnow()
    for c in body.changes:
        item = items[c.item_id]
        if c.amount is not None and c.amount != item.amount:
            item.receipt.total_amount -= item.amount - c.amount
            item.amount = c.amount
        _set_payers(item, c.member_ids)
    mark_stale(db, room.id)
    db.commit()
    db.expire_all()
    return _checks_out(db, room)


@router.get("/ai-log", summary="AI 총무 기록 — 이 정산방의 집계와 최근 기록")
def ai_log(room: CurrentRoom, db: DB) -> dict:
    """
    이 정산방에서 AI 총무에게 한 말과 결과를 모아 보여 준다. AI가 어디서 틀리는지 찾기 위한 기록이다.

    - `summary`: 상태별 · 사용자 반응별 개수, 반영 비율, 반영 뒤 손으로 고친 비율, 서버 보정 횟수,
      규칙 표(모델이 원래 고른 규칙 × 서버가 고친 뒤 규칙), 걸린 시간
    - `entries`: 최근 기록 50개 (새것부터)
    """
    entries = db.scalars(select(NlLog).where(NlLog.room_id == room.id).order_by(NlLog.id.desc())).all()
    return {"summary": nl_report.summarize(list(entries)), "entries": [nl_report.entry_out(e) for e in entries[:50]]}
