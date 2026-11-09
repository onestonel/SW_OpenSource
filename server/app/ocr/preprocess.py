"""사진 전처리: OCR이 읽기 좋게 사진을 다듬는다.

값을 바꿔 가며 `python -m app.ocr.bench`로 점수를 비교하는 곳. 기울기 보정 · 영수증 영역 잘라내기 같은
단계도 여기에 함수로 더하면 된다.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .engines import EngineUnavailable

if TYPE_CHECKING:
    from PIL.Image import Image


class ImageUnreadable(ValueError):
    """사진 파일을 열 수 없음 (깨진 파일 등)."""


@dataclass(frozen=True)
class PreprocessOptions:
    grayscale: bool = True
    min_width: int = 1400  # 이보다 작으면 키운다 (글자가 작으면 잘 못 읽는다. dev 샘플 비교로 정함)
    max_width: int = 2000  # 이보다 크면 줄인다 (폰 사진은 커서 느리다)
    autocontrast: bool = True  # 흐린 영수증의 명암을 늘린다
    sharpen: bool = False
    threshold: int | None = None  # 0~255. 정하면 흑백 두 색으로 바꾼다 (그림자가 많은 사진엔 역효과일 수 있다)


def preprocess(data: bytes, opts: PreprocessOptions | None = None) -> Image:
    opts = opts or PreprocessOptions()
    try:
        from PIL import Image, ImageFilter, ImageOps, UnidentifiedImageError
    except ImportError as e:
        raise EngineUnavailable("Pillow가 설치돼 있지 않습니다 (pip install -r requirements-ocr.txt)") from e
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError) as e:
        raise ImageUnreadable(str(e)) from e
    img = ImageOps.exif_transpose(img)  # 폰으로 찍은 사진의 회전 정보를 반영
    img = img.convert("L" if opts.grayscale else "RGB")
    if not opts.min_width <= img.width <= opts.max_width:
        width = min(max(img.width, opts.min_width), opts.max_width)
        img = img.resize((width, round(img.height * width / img.width)), Image.Resampling.LANCZOS)
    if opts.autocontrast:
        img = ImageOps.autocontrast(img, cutoff=1)
    if opts.sharpen:
        img = img.filter(ImageFilter.SHARPEN)
    if opts.threshold is not None:
        img = img.point(lambda p: 255 if p > opts.threshold else 0)
    return img
