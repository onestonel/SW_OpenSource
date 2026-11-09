"""OCR 엔진: 사진 → 글자 상자 목록.

엔진을 바꾸거나 새로 붙일 때는 이 파일만 고친다.
새 엔진 = `read(image) -> list[TextBox]`를 가진 클래스 하나 + 맨 아래 ENGINES에 이름 등록.
무거운 라이브러리(pytesseract, easyocr)는 그 엔진을 실제로 쓸 때만 불러온다.
그래서 OCR을 설치하지 않은 팀원도 stub 엔진으로 서버와 화면을 개발할 수 있다.
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from PIL.Image import Image


@dataclass(frozen=True)
class TextBox:
    """엔진이 읽은 글자 한 덩어리(낱말 또는 줄)와 사진 속 위치."""

    text: str
    conf: float  # 0~1
    left: int
    top: int
    width: int
    height: int


class EngineUnavailable(RuntimeError):
    """엔진 라이브러리나 프로그램이 설치돼 있지 않거나, 모르는 엔진 이름."""


class OcrEngine(Protocol):
    name: str
    needs_image: bool  # False면 사진을 열지 않는다 (stub)

    def read(self, image: Image | None) -> list[TextBox]: ...


class StubEngine:
    """고정 답 엔진. OCR을 설치하지 않은 팀원(화면 개발 · 테스트)용. .env의 NL_PROVIDER=stub과 같은 역할."""

    name = "stub"
    needs_image = False
    LINES = (
        "같이고기 경기대점",
        "사업자번호 123-45-67890 대표 김정산",
        "2026-11-04 19:30 테이블 7",
        "상품명 단가 수량 금액",
        "삼겹살 16,000 3 48,000",
        "목살 16,000 2 32,000",
        "된장찌개 3,000 1 3,000",
        "맥주 5,000 3 15,000",
        "합계 98,000",
        "제휴할인 -5,000",
        "결제금액 93,000",
        "부가세 8,455",
        "신용카드 1234-56**-****-7890",
    )

    def read(self, image: Image | None = None) -> list[TextBox]:
        return [TextBox(text, 1.0, 0, i * 40, 600, 30) for i, text in enumerate(self.LINES)]


_WINDOWS_TESSERACT = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
_HANGUL = re.compile(r"[가-힣]")


class TesseractEngine:
    """Tesseract 5 (오픈소스, CPU, 한국어 kor 데이터 필요).

    설치: Windows https://github.com/UB-Mannheim/tesseract/wiki · Linux `apt install tesseract-ocr tesseract-ocr-kor`
    psm(쪽 나누기 방식): 6 = 글자가 고르게 찬 한 덩어리(영수증에 맞음), 4 = 한 단, 11 = 흩어진 글자.
    """

    name = "tesseract"
    needs_image = True

    def __init__(self, lang: str = "kor", psm: int = 6, cmd: str | None = None, space_ratio: float = 0.65):
        try:
            import pytesseract
        except ImportError as e:
            raise EngineUnavailable("pytesseract가 설치돼 있지 않습니다 (pip install -r requirements-ocr.txt)") from e
        cmd = cmd or os.getenv("TESSERACT_CMD") or shutil.which("tesseract")
        if not cmd and os.path.exists(_WINDOWS_TESSERACT):
            cmd = _WINDOWS_TESSERACT
        if not cmd:
            raise EngineUnavailable("tesseract 프로그램을 찾을 수 없습니다 (설치하거나 TESSERACT_CMD에 경로 지정)")
        pytesseract.pytesseract.tesseract_cmd = cmd
        missing = set(lang.split("+")) - set(pytesseract.get_languages())
        if missing:
            raise EngineUnavailable(f"tesseract 언어 데이터가 없습니다: {', '.join(sorted(missing))}")
        self._tess, self.lang, self.psm = pytesseract, lang, psm
        # 한글 낱말 사이 간격이 글자 높이 × space_ratio보다 좁으면 붙인다 ('같 이 고기' → '같이고기')
        self.space_ratio = space_ratio

    def read(self, image: Image | None) -> list[TextBox]:
        d = self._tess.image_to_data(
            image, lang=self.lang, config=f"--psm {self.psm}", output_type=self._tess.Output.DICT
        )
        # Tesseract가 나눈 줄(block · par · line) 단위로 낱말을 모은다. 같은 높이의 줄은 pipeline이 한 번 더 합친다
        lines: dict[tuple[int, int, int], list[int]] = {}
        for i, text in enumerate(d["text"]):
            if text.strip() and float(d["conf"][i]) >= 0:
                lines.setdefault((d["block_num"][i], d["par_num"][i], d["line_num"][i]), []).append(i)
        boxes = []
        for idx in lines.values():
            idx.sort(key=lambda i: d["left"][i])
            left = d["left"][idx[0]]
            top = min(d["top"][i] for i in idx)
            right = max(d["left"][i] + d["width"][i] for i in idx)
            bottom = max(d["top"][i] + d["height"][i] for i in idx)
            gap_limit = sorted(d["height"][i] for i in idx)[len(idx) // 2] * self.space_ratio
            text = d["text"][idx[0]].strip()
            for prev, cur in zip(idx, idx[1:], strict=False):
                word = d["text"][cur].strip()
                gap = d["left"][cur] - (d["left"][prev] + d["width"][prev])
                text += word if gap < gap_limit and _HANGUL.match(text[-1]) and _HANGUL.match(word[0]) else " " + word
            conf = sum(float(d["conf"][i]) for i in idx) / len(idx) / 100
            boxes.append(TextBox(text, conf, left, top, right - left, bottom - top))
        return boxes


class EasyOcrEngine:
    """EasyOCR (오픈소스, 딥러닝, PyTorch). 처음 쓸 때 한국어 모델(약 100MB)을 내려받는다.

    설치: `pip install easyocr` (PyTorch 포함 약 1GB). GPU가 있으면 gpu=True로 빨라진다.
    """

    name = "easyocr"
    needs_image = True

    def __init__(self, langs: tuple[str, ...] = ("ko", "en"), gpu: bool = False):
        try:
            import easyocr
            import numpy as np
        except ImportError as e:
            raise EngineUnavailable("easyocr가 설치돼 있지 않습니다 (pip install easyocr)") from e
        self._np = np
        self._reader = easyocr.Reader(list(langs), gpu=gpu, verbose=False)

    def read(self, image: Image | None) -> list[TextBox]:
        boxes = []
        for points, text, conf in self._reader.readtext(self._np.array(image)):
            xs, ys = [p[0] for p in points], [p[1] for p in points]
            left, top = int(min(xs)), int(min(ys))
            boxes.append(TextBox(text, float(conf), left, top, int(max(xs)) - left, int(max(ys)) - top))
        return boxes


# 엔진 이름 → 클래스. 새 엔진(PaddleOCR, 외부 OCR API, 비전 LLM 등)은 여기에 한 줄 추가
ENGINES: dict[str, type] = {"stub": StubEngine, "tesseract": TesseractEngine, "easyocr": EasyOcrEngine}


@lru_cache
def get_engine(name: str) -> OcrEngine:
    """이름으로 엔진을 만든다. 모델을 불러오는 데 몇 초 걸리는 엔진이 있어 한 번 만든 것을 재사용한다."""
    if name not in ENGINES:
        raise EngineUnavailable(f"모르는 OCR 엔진입니다: {name} (가능: {', '.join(ENGINES)})")
    return ENGINES[name]()
