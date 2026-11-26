"""영수증 자동 인식 API (V2 프로토타입).

영수증에 올린 사진으로 OCR을 돌려 '영수증 만들기'에 넣을 초안을 돌려준다.
V2에서는 사진을 올리면 RabbitMQ에 작업이 들어가고 Worker가 같은 run_ocr를 부르게 된다.
지금은 바로 확인할 수 있게 요청 안에서 기다렸다가 답한다.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel

from ... import storage
from ...core.config import settings
from ...core.errors import AppError
from ...ocr import run_ocr
from ...ocr.engines import EngineUnavailable, get_engine
from ...ocr.preprocess import ImageUnreadable
from .receipts import CurrentReceipt

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


@router.post(
    "",
    response_model=OcrOut,
    summary="영수증 사진 자동 인식 (V2 프로토타입)",
    description="올린 사진을 읽어 가게 이름 · 합계 · 품목 초안을 돌려줍니다. lines는 줄마다 어떻게 판단했는지 보여 줍니다.",
)
def recognize_photo(
    receipt: CurrentReceipt,
    engine: Literal["stub", "tesseract", "easyocr"] | None = Query(None, description="비우면 OCR_ENGINE 설정을 씁니다"),
) -> OcrOut:
    path = storage.photo_path(receipt.photo_path) if receipt.photo_path else None
    if path is None:
        raise AppError(404, "NOT_FOUND", "사진을 찾을 수 없습니다.")
    try:
        result = run_ocr(path.read_bytes(), get_engine(engine or settings.ocr_engine))
    except EngineUnavailable as e:
        raise AppError(503, "OCR_UNAVAILABLE", f"OCR 엔진을 쓸 수 없습니다: {e}") from e
    except ImageUnreadable as e:
        raise AppError(422, "IMAGE_UNREADABLE", "사진 파일을 열 수 없습니다.") from e
    return OcrOut(**result.to_dict())
