"""영수증 사진 올리기 · 보기 API.

영수증 API가 생기기 전까지 쓰는 임시 주소다. 영수증 API가 생기면
약속서의 /rooms/{room_token}/receipts/{receipt_id}/photo 가 같은 storage 함수를 쓴다.
"""

from __future__ import annotations

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ... import storage
from ...core.errors import AppError

router = APIRouter(tags=["receipt-photos"])


class PhotoOut(BaseModel):
    photo_url: str


@router.post("/receipt-photos", response_model=PhotoOut, summary="영수증 사진 올리기 (jpg · png, 10MB 이하)")
async def upload_photo(file: UploadFile = File(...)) -> PhotoOut:
    data = await file.read(storage.MAX_BYTES + 1)
    if len(data) > storage.MAX_BYTES:
        raise AppError(413, "FILE_TOO_LARGE", "사진은 10MB 이하만 올릴 수 있습니다.")
    ext = storage.detect_ext(data)
    if ext is None:
        raise AppError(415, "UNSUPPORTED_MEDIA_TYPE", "jpg 또는 png 사진만 올릴 수 있습니다.")
    name = storage.save_photo(data, ext)
    return PhotoOut(photo_url=f"/api/v1/receipt-photos/{name}")


@router.get("/receipt-photos/{name}", summary="영수증 사진 보기", response_class=FileResponse)
def get_photo(name: str) -> FileResponse:
    path = storage.photo_path(name)
    if path is None:
        raise AppError(404, "NOT_FOUND", "사진을 찾을 수 없습니다.")
    return FileResponse(path)
