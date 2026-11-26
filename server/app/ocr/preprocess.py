"""사진 전처리: OCR이 읽기 좋게 사진을 다듬는다.

단계마다 PreprocessOptions의 값 하나로 켜고 끈다. 켜고 끈 효과는 `python -m app.ocr.ablation`으로 비교한다.

    ① EXIF 회전 → 흑백 → ② 영수증 영역 자르기 + 원근 보정 → ③ 크기 맞추기 → ④ 조명 평탄화
    → ⑤ 기울기 보정 → 명암 늘리기 · 선명하게 → ⑥ 이진화(고정 또는 적응형)

②④⑤와 적응형 이진화는 OpenCV를 쓴다. 켜지 않으면 OpenCV 없이 Pillow만으로 동작한다.
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
    grayscale: bool = True  # OpenCV 단계를 하나라도 켜면 항상 흑백
    crop: bool = False  # ② 밝은 종이 영역을 찾아 잘라내고 비스듬히 찍힌 것을 직사각형으로 편다
    # ③ 크기. target_width를 정하면 (잘라낸) 영수증 폭을 그 값으로 맞춘다. 영수증은 폭 · 한 줄 글자 수가 거의
    # 정해져 있어서 폭을 맞추면 글자 크기가 사진마다 비슷해진다. None이면 min_width~max_width 범위로만 맞춘다
    target_width: int | None = None
    min_width: int = 1400  # 이보다 작으면 키운다 (글자가 작으면 잘 못 읽는다. dev 샘플 비교로 정함)
    max_width: int = 2000  # 이보다 크면 줄인다 (폰 사진은 커서 느리다)
    flatten: bool = False  # ④ 배경 밝기로 나눠 그림자 · 밝기 차이를 없앤다
    deskew: bool = False  # ⑤ 글자 줄이 수평이 되게 돌린다 (±8도 안)
    autocontrast: bool = True  # 흐린 영수증의 명암을 늘린다
    sharpen: bool = False
    threshold: int | None = None  # ⑥ 0~255. 정하면 흑백 두 색으로 바꾼다 (그림자가 많은 사진엔 역효과일 수 있다)
    adaptive_threshold: bool = False  # ⑥ 주변 밝기 기준으로 흑백 두 색으로 바꾼다 (그림자에 강함)

    @property
    def needs_cv(self) -> bool:
        return self.crop or self.flatten or self.deskew or self.adaptive_threshold


def _cv():
    try:
        import cv2
        import numpy as np
    except ImportError as e:
        raise EngineUnavailable("OpenCV가 설치돼 있지 않습니다 (pip install -r requirements-ocr.txt)") from e
    return cv2, np


def _crop_receipt(gray):
    """가장 큰 밝은 영역(종이)을 찾아 직사각형으로 편다. (사진, 알릴 말) — 못 찾으면 사진은 그대로."""
    cv2, np = _cv()
    scale = min(1.0, 600 / max(gray.shape))  # 영역 찾기는 작은 사진으로 (빠르고, 글자 무늬에 덜 흔들림)
    small = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    _, mask = cv2.threshold(cv2.GaussianBlur(small, (5, 5), 0), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))  # 종이 안의 글자 구멍을 메운다
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return gray, "영수증 영역을 찾지 못해 사진 전체를 읽었습니다."
    paper = max(contours, key=cv2.contourArea)
    ratio = cv2.contourArea(paper) / mask.size
    if ratio > 0.9:
        return gray, None  # 영수증이 이미 사진을 가득 채움
    if ratio < 0.15:
        return gray, "영수증 영역을 찾지 못해 사진 전체를 읽었습니다."
    quad = cv2.approxPolyDP(paper, 0.02 * cv2.arcLength(paper, True), True).reshape(-1, 2)
    if len(quad) != 4:  # 사진 밖으로 잘린 영수증 · 말린 종이: 꼭짓점 대신 감싸는 기울어진 직사각형
        quad = cv2.boxPoints(cv2.minAreaRect(paper))
    pts = quad.astype("float32") / scale
    s, d = pts.sum(axis=1), (pts[:, 1] - pts[:, 0])
    tl, br, tr, bl = pts[s.argmin()], pts[s.argmax()], pts[d.argmin()], pts[d.argmax()]
    width = int(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl)))
    height = int(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr)))
    if width < 50 or height < 50:
        return gray, "영수증 영역을 찾지 못해 사진 전체를 읽었습니다."
    src = np.array([tl, tr, br, bl], dtype="float32")
    dst = np.array([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], dtype="float32")
    flat = cv2.warpPerspective(gray, cv2.getPerspectiveTransform(src, dst), (width, height))
    m = max(width, height) // 100  # 종이 가장자리의 배경 · 그림자 띠를 깎는다 (OCR이 잡글 줄로 읽음)
    return flat[m : height - m, m : width - m], None


def _flatten(gray):
    """배경 밝기(글자를 지운 사진)로 나눈다. 그림자 진 곳도 종이는 흰색, 글자는 검은색이 된다."""
    cv2, _ = _cv()
    k = max(gray.shape[1] // 40, 15) | 1  # 글자보다 큰 창 (폭 1400 → 35px)
    background = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (k, k)))
    return cv2.divide(gray, background, scale=255)


def _rotate(cv2, img, angle: float):
    h, w = img.shape
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(img, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def _deskew(gray):
    """글자 줄이 수평이면 '행마다 잉크 양'이 줄 위아래에서 급하게 바뀐다. 이웃 행끼리 차이의 제곱합이 가장 큰 각도를 고른다.

    잉크는 주변 밝기 기준으로 뽑는다. 사진 전체 기준(Otsu)으로 뽑으면 그림자 · 배경까지 잉크로 잡혀
    진짜 사진에서 엉뚱한 각도(5도)를 골랐다. 가짜 영수증 6장(−1~+2도)은 모두 정확히 되돌린다.
    """
    cv2, np = _cv()
    scale = min(1.0, 800 / gray.shape[1])
    small = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    ink = cv2.adaptiveThreshold(small, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 15)
    angles = np.arange(-8, 8.01, 0.25)
    best = max(angles, key=lambda a: (np.diff(_rotate(cv2, ink, a).sum(axis=1).astype(float)) ** 2).sum())
    return gray if abs(best) < 0.25 else _rotate(cv2, gray, float(best))


def _adaptive_threshold(gray):
    cv2, _ = _cv()
    block = max(gray.shape[1] // 40, 15) | 1
    return cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, block, 15)


def preprocess(
    data: bytes, opts: PreprocessOptions | None = None, steps: list[tuple[str, Image]] | None = None
) -> tuple[Image, list[str]]:
    """사진 바이트 → (OCR에 넣을 사진, 사람에게 알릴 말). steps를 넘기면 단계별 중간 사진을 담는다 (디버깅용)."""
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
    notes: list[str] = []

    def step(name: str, image):
        image = image if isinstance(image, Image.Image) else Image.fromarray(image)
        if steps is not None:
            steps.append((name, image))
        return image

    img = ImageOps.exif_transpose(img)  # 폰으로 찍은 사진의 회전 정보를 반영
    img = step("1_gray", img.convert("L" if opts.grayscale or opts.needs_cv else "RGB"))
    if opts.crop:
        _, np = _cv()
        cropped, note = _crop_receipt(np.array(img))
        img = step("2_crop", cropped)
        notes += [note] if note else []
    if opts.target_width:
        width = opts.target_width
    else:
        width = min(max(img.width, opts.min_width), opts.max_width)
    if width != img.width:
        img = step("3_resize", img.resize((width, round(img.height * width / img.width)), Image.Resampling.LANCZOS))
    if opts.flatten:
        img = step("4_flatten", _flatten(_cv()[1].array(img)))
    if opts.deskew:
        img = step("5_deskew", _deskew(_cv()[1].array(img)))
    if opts.autocontrast:
        img = step("autocontrast", ImageOps.autocontrast(img, cutoff=1))
    if opts.sharpen:
        img = step("sharpen", img.filter(ImageFilter.SHARPEN))
    if opts.adaptive_threshold:
        img = step("6_adaptive", _adaptive_threshold(_cv()[1].array(img)))
    elif opts.threshold is not None:
        img = step("6_threshold", img.point(lambda p: 255 if p > opts.threshold else 0))
    return img, notes
