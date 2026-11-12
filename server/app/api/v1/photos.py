"""영수증 사진 올리기 · 보기 API (API 명세서 3절 「사진」).

- 주소: /rooms/{room_token}/receipts/{receipt_id}/photo
- 사진 파일은 RECEIPT_STORAGE_PATH 폴더에 무작위 이름으로 저장하고, 그 이름을 영수증(photo_path)에 적어 둔다.
- 다시 올리면 이전 사진 파일을 지운다.
"""

from __future__ import annotations

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ... import storage
from ...core.errors import AppError
from ..deps import DB, CurrentRoom
from .receipts import CurrentReceipt

router = APIRouter(prefix="/rooms/{room_token}/receipts/{receipt_id}/photo", tags=["receipt-photos"])


class PhotoOut(BaseModel):
    photo_url: str


@router.post("", response_model=PhotoOut, summary="영수증 사진 올리기 (jpg · png, 10MB 이하)")
async def upload_photo(room: CurrentRoom, receipt: CurrentReceipt, db: DB,
                       file: UploadFile = File(...)) -> PhotoOut:
    if receipt.status == "CONFIRMED":
        raise AppError(409, "RECEIPT_CONFIRMED", "확정된 영수증은 고칠 수 없습니다. 먼저 '확정 취소'를 눌러 주세요.")
    data = await file.read(storage.MAX_BYTES + 1)
    if len(data) > storage.MAX_BYTES:
        raise AppError(413, "FILE_TOO_LARGE", "사진은 10MB 이하만 올릴 수 있습니다.")
    ext = storage.detect_ext(data)
    if ext is None:
        raise AppError(415, "UNSUPPORTED_MEDIA_TYPE", "jpg 또는 png 사진만 올릴 수 있습니다.")

    old_name = receipt.photo_path
    receipt.photo_path = storage.save_photo(data, ext)
    db.commit()
    storage.delete_photo(old_name)  # 새 사진이 저장된 뒤에 이전 사진을 지운다
    return PhotoOut(photo_url=f"/api/v1/rooms/{room.room_token}/receipts/{receipt.id}/photo")


@router.get("", summary="영수증 사진 보기", response_class=FileResponse)
def get_photo(receipt: CurrentReceipt) -> FileResponse:
    path = storage.photo_path(receipt.photo_path) if receipt.photo_path else None
    if path is None:
        raise AppError(404, "NOT_FOUND", "사진을 찾을 수 없습니다.")
    return FileResponse(path)