"""전체 흐름: 사진 → 전처리 → 엔진(글자 읽기) → 줄 묶기 → 규칙 파서 → 영수증 초안.

V2에서 RabbitMQ Worker가 생기면 Worker는 저장된 사진을 읽어 run_ocr 한 번만 부르면 된다.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from ..core.config import settings
from .engines import OcrEngine, TextBox, get_engine
from .parser import Line, ParsedReceipt, ParseRules, parse_receipt
from .preprocess import PreprocessOptions, preprocess


@dataclass
class OcrResult:
    engine: str
    elapsed_ms: int
    receipt: ParsedReceipt

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
    return [
        Line(" ".join(b.text for b in sorted(row, key=lambda b: b.left)), sum(b.conf for b in row) / len(row))
        for row in rows
    ]


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
    image = preprocess(data, prep) if engine.needs_image else None
    lines = group_lines(engine.read(image), line_tolerance)
    receipt = parse_receipt(lines, rules)
    return OcrResult(engine.name, round((time.perf_counter() - start) * 1000), receipt)
