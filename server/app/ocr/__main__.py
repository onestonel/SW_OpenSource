"""사진 한 장 읽어 보기.

python -m app.ocr 사진.jpg                    # tesseract로 읽고 초안 출력
python -m app.ocr 사진.jpg --engine easyocr --lines   # 줄마다 어떻게 판단했는지도 출력
python -m app.ocr 사진.jpg --engine easyocr:width_ths=0.1   # 엔진 설정은 콜론 뒤에
python -m app.ocr 사진.jpg --prep crop flatten --save-steps out/   # 전처리 단계를 켜고 단계별 사진 저장
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .engines import make_engine, parse_settings
from .pipeline import run_ocr
from .preprocess import PreprocessOptions, preprocess


def main() -> None:
    ap = argparse.ArgumentParser(description="영수증 사진 → 영수증 초안")
    ap.add_argument("image", type=Path)
    ap.add_argument("--engine", default="tesseract", help="엔진 이름 (설정은 콜론 뒤에: tesseract:lang=kor_best)")
    ap.add_argument("--lines", action="store_true", help="줄마다 어떤 역할로 판단했는지도 보여 준다")
    ap.add_argument(
        "--prep",
        nargs="*",
        default=[],
        help="켤 전처리 단계 (crop flatten deskew adaptive_threshold, target_width=1400 처럼 값도 가능)",
    )
    ap.add_argument("--save-steps", type=Path, help="단계별 중간 사진을 저장할 폴더 (어느 단계에서 망가졌는지 보기)")
    args = ap.parse_args()
    prep = PreprocessOptions(**parse_settings(args.prep))
    data = args.image.read_bytes()
    if args.save_steps:
        steps: list = []
        preprocess(data, prep, steps)
        args.save_steps.mkdir(parents=True, exist_ok=True)
        for i, (name, image) in enumerate(steps):
            image.save(args.save_steps / f"{i}_{name}.png")
    result = run_ocr(data, make_engine(args.engine), prep=prep).to_dict()
    if not args.lines:
        result.pop("lines")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
