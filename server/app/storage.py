"""영수증 사진 저장. 파일 이름은 사용자가 보낸 이름 대신 무작위 이름을 쓴다."""

from __future__ import annotations

import re
import secrets
from pathlib import Path

from .core.config import settings

MAX_BYTES = 10 * 1024 * 1024  # 10MB
_SIGNATURES = {b"\xff\xd8\xff": ".jpg", b"\x89PNG\r\n\x1a\n": ".png"}
_NAME_RE = re.compile(r"[0-9a-f]{32}\.(jpg|png)")


def storage_dir() -> Path:
    return Path(settings.receipt_storage_path)


def detect_ext(data: bytes) -> str | None:
    """Content-Type은 속일 수 있으니 파일 첫 바이트로 jpg · png를 판별한다."""
    return next((ext for sig, ext in _SIGNATURES.items() if data.startswith(sig)), None)


def save_photo(data: bytes, ext: str) -> str:
    """사진을 저장하고 무작위 파일 이름을 돌려준다."""
    d = storage_dir()
    d.mkdir(parents=True, exist_ok=True)
    name = secrets.token_hex(16) + ext
    (d / name).write_bytes(data)
    return name


def photo_path(name: str) -> Path | None:
    """저장된 사진 경로. 형식이 맞는 이름만 받아서 ../ 같은 경로 공격을 막는다."""
    if not _NAME_RE.fullmatch(name):
        return None
    path = storage_dir() / name
    return path if path.is_file() else None
