"""영수증 자동 인식 API (V2 프로토타입).

영수증에 올린 사진으로 OCR을 돌려 '영수증 만들기'에 넣을 초안을 돌려준다.
V2에서는 사진을 올리면 RabbitMQ에 작업이 들어가고 Worker가 같은 run_ocr를 부르게 된다.
지금은 바로 확인할 수 있게 요청 안에서 기다렸다가 답한다.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
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
    engine: Literal["stub", "tesseract", "easyocr", "remote"] | None = Query(
        None, description="비우면 OCR_ENGINE 설정을 씁니다. remote = ocr 컨테이너의 PaddleOCR"
    ),
) -> OcrOut:
    path = storage.photo_path(receipt.photo_path) if receipt.photo_path else None
    if path is None:
        raise AppError(404, "NOT_FOUND", "사진을 찾을 수 없습니다.")
    name = engine or settings.ocr_engine
    try:
        data = path.read_bytes()
        result = _remote_ocr(data) if name == "remote" else run_ocr(data, get_engine(name)).to_dict()
    except EngineUnavailable as e:
        raise AppError(503, "OCR_UNAVAILABLE", f"OCR 엔진을 쓸 수 없습니다: {e}") from e
    except ImageUnreadable as e:
        raise AppError(422, "IMAGE_UNREADABLE", "사진 파일을 열 수 없습니다.") from e
    return OcrOut(**result)


# ocr 컨테이너의 답을 기다릴 시간. PaddleOCR 장당 평균 13초 · 가장 느린 장 27초 (보고서 6회차)
REMOTE_TIMEOUT = 120


def _remote_ocr(data: bytes) -> dict:
    """사진을 ocr 컨테이너(docker compose --profile ocr)에 보내 읽힌다. 답은 run_ocr(...).to_dict()와 같은 모양."""
    req = urllib.request.Request(
        f"{settings.ocr_url}/ocr", data=data, headers={"Content-Type": "application/octet-stream"}
    )
    try:
        with urllib.request.urlopen(req, timeout=REMOTE_TIMEOUT) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        if e.code == 422:
            raise ImageUnreadable(e.read().decode(errors="replace")) from e
        raise EngineUnavailable(f"ocr 컨테이너가 오류를 돌려줬습니다 (HTTP {e.code})") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise EngineUnavailable(
            f"ocr 컨테이너에 연결하지 못했거나 답이 없습니다 ({e}). 꺼져 있다면: docker compose --profile ocr up -d ocr"
        ) from e
