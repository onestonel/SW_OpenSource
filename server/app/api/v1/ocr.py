"""영수증 자동 인식 API (V2 프로토타입).

영수증에 올린 사진으로 OCR을 돌려 '영수증 만들기'에 넣을 초안을 돌려준다.
save=true면 그 초안을 영수증 입력 규칙에 맞게 정리해(app/ocr_draft.py) 이 영수증의 총액 · 품목에 덮어쓴다.
가게 이름은 사용자가 적은 값을 그대로 둔다 (OCR이 읽은 가게 이름은 draft.store_name으로 돌려주기만 한다).
상태는 '확인 중' 그대로라, 사용자가 확인 화면에서 고친 뒤 확정해야 정산에 들어간다.
V2에서는 사진을 올리면 RabbitMQ에 작업이 들어가고 Worker가 같은 run_ocr · save_draft를 부르게 된다.
지금은 바로 확인할 수 있게 요청 안에서 기다렸다가 답한다.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel

from ... import storage
from ...core.config import settings
from ...core.errors import AppError
from ...models import Receipt, Room
from ...ocr import run_ocr
from ...ocr.engines import EngineUnavailable, get_engine
from ...ocr.preprocess import ImageUnreadable
from ...ocr_draft import RawDraft, ReceiptDraft, make_draft
from ...schemas import ReceiptOut
from ..deps import DB, CurrentRoom
from .receipts import CurrentReceipt, _confirmed_error, _new_item, receipt_out

router = APIRouter(prefix="/rooms/{room_token}/receipts/{receipt_id}/photo/ocr", tags=["receipt-ocr"])


class DraftItemOut(BaseModel):
    name: str
    amount: int
    kind: Literal["ITEM", "DISCOUNT"]


class DraftOut(BaseModel):
    """API 약속서 '영수증 만들기'에 보내는 칸과 같은 모양. payer_member_id는 사람이 고른다."""

    store_name: str | None
    total_amount: int | None
    items: list[DraftItemOut]


class CheckOut(BaseModel):
    items_sum: int
    difference: int | None
    is_matched: bool


class LineOut(BaseModel):
    text: str
    confidence: float
    role: str


class OcrOut(BaseModel):
    draft: DraftOut
    check: CheckOut
    warnings: list[str]
    lines: list[LineOut]
    engine: str
    elapsed_ms: int
    # save=true로 이 영수증에 덮어썼을 때 저장된 영수증. 저장하지 않았으면 null
    receipt: ReceiptOut | None = None


def save_draft(db, room: Room, receipt: Receipt, draft: ReceiptDraft) -> None:
    """정리한 초안으로 영수증의 총액 · 품목을 바꾼다. 가게 이름 · 결제자 · 상태('확인 중')는 그대로 둔다.

    품목은 통째로 덮어쓴다. 사진을 다시 올려 다시 읽어도 품목이 겹쳐 쌓이지 않는다.
    새 품목은 영수증 만들기와 같이 모든 구성원 체크로 시작한다 (이전 품목의 체크는 같이 지워진다).
    """
    receipt.total_amount = draft.total_amount
    receipt.items = [_new_item(room, line, n) for n, line in enumerate(draft.items, start=1)]
    db.commit()
    db.refresh(receipt)


@router.post(
    "",
    response_model=OcrOut,
    summary="영수증 사진 자동 인식 (V2 프로토타입)",
    description="올린 사진을 읽어 가게 이름 · 합계 · 품목 초안을 돌려줍니다. lines는 줄마다 어떻게 판단했는지 보여 줍니다. "
                "save=true면 초안을 정리해 이 영수증(확인 중)의 총액 · 품목을 바꿔 저장합니다. 가게 이름은 바꾸지 않습니다.",
)
def recognize_photo(
    room: CurrentRoom,
    receipt: CurrentReceipt,
    db: DB,
    engine: Literal["stub", "tesseract", "easyocr"] | None = Query(None, description="비우면 OCR_ENGINE 설정을 씁니다"),
    save: bool = Query(False, description="true면 읽은 초안으로 이 영수증의 총액 · 품목을 바꿉니다 (가게 이름 · 결제자는 그대로)"),
) -> OcrOut:
    if save and receipt.status == "CONFIRMED":
        raise _confirmed_error()
    path = storage.photo_path(receipt.photo_path) if receipt.photo_path else None
    if path is None:
        raise AppError(404, "NOT_FOUND", "사진을 찾을 수 없습니다.")
    try:
        result = run_ocr(path.read_bytes(), get_engine(engine or settings.ocr_engine))
    except EngineUnavailable as e:
        raise AppError(503, "OCR_UNAVAILABLE", f"OCR 엔진을 쓸 수 없습니다: {e}") from e
    except ImageUnreadable as e:
        raise AppError(422, "IMAGE_UNREADABLE", "사진 파일을 열 수 없습니다.") from e
    out = OcrOut(**result.to_dict())
    if not save:
        return out

    db.refresh(receipt)  # OCR은 수십 초 걸릴 수 있다. 그 사이에 확정됐으면 덮어쓰지 않는다
    if receipt.status == "CONFIRMED":
        raise _confirmed_error()
    draft = make_draft(RawDraft.from_dict(out.draft.model_dump()), store_name=receipt.store_name)
    out.warnings += draft.notes  # 경고 칸이 영수증 테이블에 없으니, 고친 이유와 함께 답장으로 돌려준다
    if draft.ok:
        save_draft(db, room, receipt, draft)
        out.receipt = receipt_out(room, receipt)
    else:
        out.warnings.append(f"{draft.problem} 영수증은 그대로 두었습니다. 직접 입력해 주세요.")
    return out
