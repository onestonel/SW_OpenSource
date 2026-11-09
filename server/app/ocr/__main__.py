"""사진 한 장 읽어 보기.

python -m app.ocr 사진.jpg                    # tesseract로 읽고 초안 출력
python -m app.ocr 사진.jpg --engine easyocr --lines   # 줄마다 어떻게 판단했는지도 출력
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .engines import ENGINES, get_engine
from .pipeline import run_ocr


def main() -> None:
    ap = argparse.ArgumentParser(description="영수증 사진 → 영수증 초안")
    ap.add_argument("image", type=Path)
    ap.add_argument("--engine", default="tesseract", choices=list(ENGINES))
    ap.add_argument("--lines", action="store_true", help="줄마다 어떤 역할로 판단했는지도 보여 준다")
    args = ap.parse_args()
    result = run_ocr(args.image.read_bytes(), get_engine(args.engine)).to_dict()
    if not args.lines:
        result.pop("lines")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
