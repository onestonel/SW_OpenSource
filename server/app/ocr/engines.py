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


_HANGUL = re.compile(r"[가-힣]")


@dataclass(frozen=True)
class TextBox:
    """엔진이 읽은 글자 한 덩어리(낱말 또는 줄)와 사진 속 위치."""

    text: str
    conf: float  # 0~1
    left: int
    top: int
    width: int
    height: int
    # 줄 단위 상자 안의 낱말 상자들. 있으면 parser가 낱말 위치로 표의 열을 나눈다
    words: tuple[TextBox, ...] = ()


def join_text(boxes: list[TextBox], space_ratio: float = 0.65) -> str:
    """같은 줄의 상자를 왼쪽부터 잇는다. 한글끼리 간격이 글자 높이 × space_ratio보다 좁으면 붙인다 ('같 이 고기' → '같이고기')."""
    boxes = sorted(boxes, key=lambda b: b.left)
    if not boxes:
        return ""
    gap_limit = sorted(b.height for b in boxes)[len(boxes) // 2] * space_ratio
    text = boxes[0].text
    for prev, cur in zip(boxes, boxes[1:], strict=False):
        gap = cur.left - (prev.left + prev.width)
        tight = gap < gap_limit and _HANGUL.match(text[-1]) and _HANGUL.match(cur.text[0])
        text += cur.text if tight else " " + cur.text
    return text


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
    # 표 머리줄(상품명 단가 수량 금액)은 넣지 않는다: 줄 전체가 상자 하나라 표 읽기가 낱말 위치를 잘못 짐작해 '맥주 5,000'이 된다
    LINES = (
        "같이고기 경기대점",
        "사업자번호 123-45-67890 대표 김정산",
        "2026-11-04 19:30 테이블 7",
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


class TesseractEngine:
    """Tesseract 5 (오픈소스, CPU, 한국어 kor 데이터 필요).

    설치: Windows https://github.com/UB-Mannheim/tesseract/wiki · Linux `apt install tesseract-ocr tesseract-ocr-kor`
    psm(쪽 나누기 방식): 6 = 글자가 고르게 찬 한 덩어리(영수증에 맞음), 4 = 한 단, 11 = 흩어진 글자.
    thresholding(Tesseract 안의 흑백 나누기): 0 = Otsu(기본), 1 = Leptonica Otsu, 2 = Sauvola(그림자에 강함). Tesseract 5 이상.
    """

    name = "tesseract"
    needs_image = True

    def __init__(self, lang: str = "kor", psm: int = 6, cmd: str | None = None, thresholding: int = 0):
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
        self._tess, self.lang, self.psm, self.thresholding = pytesseract, lang, psm, thresholding

    def read(self, image: Image | None) -> list[TextBox]:
        d = self._tess.image_to_data(
            image,
            lang=self.lang,
            config=f"--psm {self.psm} -c thresholding_method={self.thresholding}",
            output_type=self._tess.Output.DICT,
        )
        # Tesseract가 나눈 줄(block · par · line) 단위로 낱말을 모은다. 같은 높이의 줄은 pipeline이 한 번 더 합친다.
        # 낱말 단위로만 넘기면 기울어진 사진에서 줄이 엉켜서, 줄은 Tesseract에 맡기고 낱말 위치는 words로 함께 넘긴다
        lines: dict[tuple[int, int, int], list[TextBox]] = {}
        for i, text in enumerate(d["text"]):
            if text.strip() and float(d["conf"][i]) >= 0:
                word = TextBox(
                    text.strip(), float(d["conf"][i]) / 100, d["left"][i], d["top"][i], d["width"][i], d["height"][i]
                )
                lines.setdefault((d["block_num"][i], d["par_num"][i], d["line_num"][i]), []).append(word)
        boxes = []
        for words in lines.values():
            left, top = min(w.left for w in words), min(w.top for w in words)
            right, bottom = max(w.left + w.width for w in words), max(w.top + w.height for w in words)
            conf = sum(w.conf for w in words) / len(words)
            boxes.append(TextBox(join_text(words), conf, left, top, right - left, bottom - top, tuple(words)))
        return boxes


class EasyOcrEngine:
    """EasyOCR (오픈소스, 딥러닝, PyTorch). 처음 쓸 때 한국어 모델(약 100MB)을 내려받는다.

    설치: `pip install easyocr` (PyTorch 포함 약 1GB). GPU가 있으면 gpu=True로 빨라진다.
    """

    name = "easyocr"
    needs_image = True

    def __init__(self, langs: tuple[str, ...] = ("ko", "en"), gpu: bool = False, **readtext_options):
        """readtext_options: EasyOCR readtext 설정. width_ths=0.1이면 가까운 낱말을 덜 합쳐 낱말 단위 상자가 된다
        (기본 0.5는 '69, 000'처럼 한 덩어리로 합친다). 표의 열을 나누려면 낱말 단위가 유리하다."""
        try:
            import easyocr
            import numpy as np
        except ImportError as e:
            raise EngineUnavailable("easyocr가 설치돼 있지 않습니다 (pip install easyocr)") from e
        self._np = np
        self._reader = easyocr.Reader(list(langs), gpu=gpu, verbose=False)
        self._options = readtext_options

    def read(self, image: Image | None) -> list[TextBox]:
        boxes = []
        for points, text, conf in self._reader.readtext(self._np.array(image), **self._options):
            xs, ys = [p[0] for p in points], [p[1] for p in points]
            left, top = int(min(xs)), int(min(ys))
            boxes.append(TextBox(text, float(conf), left, top, int(max(xs)) - left, int(max(ys)) - top))
        return boxes


class PaddleOcrEngine:
    """PaddleOCR 3.x (오픈소스, 딥러닝, PaddlePaddle). 처음 쓸 때 검출 · 인식 모델을 내려받는다.

    설치: 기존 .venv와 numpy · OpenCV 버전이 부딪혀서 별도 가상환경에 설치한다 (app/ocr/README.md).
    lang=korean이면 PP-OCRv5 검출(server) + 한국어 인식(mobile) 모델을 쓴다 (PP-OCRv6은 한국어 미지원).
    unwarp=True면 PaddleOCR의 문서 펴기 모델로 휜 종이를 편 뒤 읽는다 (상자 위치는 편 사진 기준).
    words=True면 줄 상자 안의 낱말 위치도 넘긴다 (Tesseract의 words처럼 parser가 표의 열을 나누는 데 씀).
    options: PaddleOCR 생성 설정. 모델 이름을 직접 주면 lang은 무시되니 검출 · 인식 모델을 둘 다 준다
    (예: text_detection_model_name=PP-OCRv5_mobile_det,text_recognition_model_name=korean_PP-OCRv5_mobile_rec).
    """

    name = "paddleocr"
    needs_image = True
    rereads_dense = True  # run_ocr가 이름 열이 세로로 읽힌 것을 보면 read(dense=True)로 한 번 더 읽는다

    def __init__(self, lang: str = "korean", unwarp: bool = False, words: bool = False, **options):
        try:
            import numpy as np
            from paddleocr import PaddleOCR
        except ImportError as e:
            raise EngineUnavailable("paddleocr가 설치돼 있지 않습니다 (app/ocr/README.md의 PaddleOCR 설치 참고)") from e
        self._np, self._words = np, words
        self._ocr = PaddleOCR(
            lang=lang,
            use_doc_orientation_classify=False,  # 사진 회전은 전처리의 EXIF 회전이 맡는다
            use_doc_unwarping=unwarp,
            use_textline_orientation=False,
            return_word_box=words,
            **options,
        )

    def read(self, image: Image | None, dense: bool = False) -> list[TextBox]:
        det = {}
        if dense:
            # 줄 간격이 좁은 영수증: 세로로 늘려 줄 사이를 벌리고, 글자를 찾을 때는 사진을 줄여(긴 변 960) 큰 글자를
            # 한 덩어리로 본다. 보통 영수증에서는 이웃 글자가 붙어 나빠지므로 증상이 있을 때만 쓴다 (보고서 5회차)
            image = image.resize((image.width, round(image.height * 1.5)))
            det = {"text_det_limit_type": "max", "text_det_limit_side_len": 960}
        bgr = self._np.array(image.convert("RGB"))[:, :, ::-1]  # PaddleOCR는 BGR 3채널 사진을 받는다
        boxes = []
        for page in self._ocr.predict(bgr, **det):
            for i, (text, conf, (x1, y1, x2, y2)) in enumerate(
                zip(page["rec_texts"], page["rec_scores"], page["rec_boxes"], strict=True)
            ):
                if not text.strip():  # 글자를 못 읽은 상자 (확신도 0)
                    continue
                words = ()
                if self._words:
                    words = tuple(
                        TextBox(w, float(conf), int(b[0]), int(b[1]), int(b[2] - b[0]), int(b[3] - b[1]))
                        for w, b in zip(page["text_word"][i], page["text_word_boxes"][i], strict=True)
                        if w.strip()
                    )
                boxes.append(TextBox(text, float(conf), int(x1), int(y1), int(x2 - x1), int(y2 - y1), words))
        return boxes


# 엔진 이름 → 클래스. 새 엔진(외부 OCR API, 비전 LLM 등)은 여기에 한 줄 추가
ENGINES: dict[str, type] = {
    "stub": StubEngine,
    "tesseract": TesseractEngine,
    "easyocr": EasyOcrEngine,
    "paddleocr": PaddleOcrEngine,
}


@lru_cache
def get_engine(name: str) -> OcrEngine:
    """이름으로 엔진을 만든다. 모델을 불러오는 데 몇 초 걸리는 엔진이 있어 한 번 만든 것을 재사용한다."""
    if name not in ENGINES:
        raise EngineUnavailable(f"모르는 OCR 엔진입니다: {name} (가능: {', '.join(ENGINES)})")
    return ENGINES[name]()


def _value(raw: str):
    if raw.lower() in ("true", "false"):
        return raw.lower() == "true"
    for cast in (int, float):
        try:
            return cast(raw)
        except ValueError:
            pass
    return raw


def parse_settings(items) -> dict:
    """명령줄 설정 → dict. ['crop', 'min_width=1', 'grayscale=false', 'width_ths=0.1'] → {'crop': True, ...}"""
    out = {}
    for item in items:
        key, sep, raw = item.partition("=")
        out[key] = _value(raw) if sep else True
    return out


def make_engine(spec: str) -> OcrEngine:
    """'easyocr' 또는 'easyocr:width_ths=0.1,mag_ratio=1.5'처럼 설정을 붙인 이름으로 엔진을 만든다 (비교 실험용)."""
    name, _, options = spec.partition(":")
    if name not in ENGINES:
        raise EngineUnavailable(f"모르는 OCR 엔진입니다: {name} (가능: {', '.join(ENGINES)})")
    return ENGINES[name](**parse_settings(o for o in options.split(",") if o))
