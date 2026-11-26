"""전체 흐름: 사진 → 전처리 → 엔진(글자 읽기) → 줄 묶기 → 규칙 파서 → 영수증 초안.

V2에서 RabbitMQ Worker가 생기면 Worker는 저장된 사진을 읽어 run_ocr 한 번만 부르면 된다.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from ..core.config import settings
from .engines import OcrEngine, TextBox, get_engine
from .parser import Line, ParsedReceipt, ParseRules, parse_receipt
from .preprocess import PreprocessOptions, preprocess


@dataclass
class OcrResult:
    engine: str
    elapsed_ms: int
    receipt: ParsedReceipt
    # 파서를 거치기 전 엔진이 읽은 줄 글자. 엔진의 인식 실력만 따로 잴 때 쓴다 (API 응답에는 넣지 않는다)
    raw_lines: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        r = self.receipt
        return {
            "draft": r.draft(),
            "check": r.check(),
            "warnings": r.warnings,
            "lines": [{"text": ln.text, "confidence": round(ln.conf, 2), "role": ln.role} for ln in r.lines],
            "engine": self.engine,
            "elapsed_ms": self.elapsed_ms,
        }


def group_lines(boxes: list[TextBox], tolerance: float = 0.6) -> list[Line]:
    """글자 상자를 위에서 아래로 줄 단위로 묶는다.

    세로 가운데가 '글자 높이(중앙값) × tolerance' 안에 있으면 같은 줄로 본다.
    영수증이 많이 기울어 한 줄이 둘로 쪼개지면 tolerance를 올린다.
    """
    if not boxes:
        return []
    heights = sorted(b.height for b in boxes)
    limit = max(heights[len(heights) // 2], 1) * tolerance
    rows: list[list[TextBox]] = []
    for box in sorted(boxes, key=lambda b: b.top + b.height / 2):
        center = box.top + box.height / 2
        if rows and abs(center - sum(b.top + b.height / 2 for b in rows[-1]) / len(rows[-1])) <= limit:
            rows[-1].append(box)
        else:
            rows.append([box])
    lines = []
    for row in rows:
        row.sort(key=lambda b: b.left)
        # 낱말 위치(엔진이 주면 낱말, 아니면 상자 자체)도 넘긴다. parser가 표의 열을 나누는 데 쓴다
        words = tuple(w for b in row for w in (b.words or (b,)))
        lines.append(Line(" ".join(b.text for b in row), sum(b.conf for b in row) / len(row), words))
    return lines


def _column_boxes(boxes: list[TextBox]) -> bool:
    """세로로 긴 글자 상자(높이 > 폭 × 2, 3글자 이상)가 있는지. 줄 간격이 좁으면 엔진이 이름 열을 '양양된도공'처럼 세로로 읽는다."""
    return any(b.height > 2 * b.width and len(b.text.replace(" ", "")) >= 3 for b in boxes)


def run_ocr(
    data: bytes,
    engine: OcrEngine | None = None,
    rules: ParseRules | None = None,
    prep: PreprocessOptions | None = None,
    line_tolerance: float = 0.6,
) -> OcrResult:
    """사진 바이트 → OcrResult. 엔진을 정하지 않으면 OCR_ENGINE 설정을 쓴다."""
    start = time.perf_counter()
    engine = engine or get_engine(settings.ocr_engine)
    image, notes = preprocess(data, prep) if engine.needs_image else (None, [])
    boxes = engine.read(image)
    if getattr(engine, "rereads_dense", False) and _column_boxes(boxes):
        boxes = engine.read(image, dense=True)
        notes.append("글자가 세로로 이어 읽혀서, 줄 간격을 벌려 다시 읽었습니다")
    lines = group_lines(boxes, line_tolerance)
    receipt = parse_receipt(lines, rules)
    receipt.warnings += notes
    elapsed = round((time.perf_counter() - start) * 1000)
    return OcrResult(engine.name, elapsed, receipt, [ln.text for ln in lines])
