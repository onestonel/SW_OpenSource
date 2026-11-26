"""전처리 단계 Ablation: 단계를 하나씩 더하고(+), 모두 켠 것에서 하나씩 빼서(−) 점수를 비교한다.

    python -m app.ocr.ablation                      # dev 샘플로 (단계를 고를 때)
    python -m app.ocr.ablation --grid               # ②④⑤⑥ 켜고 끄기 16가지 조합 (단계끼리 서로 영향을 줄 때)
    python -m app.ocr.ablation --split test --only 기준   # 고른 설정을 test로 한 번만 확인
    python -m app.ocr.ablation --engine easyocr:width_ths=0.1 --grid --only 기준 ②⑥   # 다른 엔진으로
    python -m app.ocr.ablation --base grayscale=false min_width=1 autocontrast=false --only 기준   # 기준 설정 바꾸기

가짜 영수증과 진짜 사진은 따로 요약한다. 가짜는 이미 거의 만점이라 진짜 사진 점수가 더 중요하다.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from itertools import product
from pathlib import Path

from .bench import SAMPLES, _summary, evaluate, load_samples
from .engines import make_engine, parse_settings
from .preprocess import PreprocessOptions

# 단계 이름 → 켜는 값. "T"는 전처리가 아니라 Tesseract 안의 흑백 나누기를 Sauvola로 바꾸는 것
STEPS: dict[str, dict] = {
    "②자르기": {"crop": True},
    "③폭고정": {"target_width": 1400},
    "④조명": {"flatten": True},
    "⑤기울기": {"deskew": True},
    "⑥적응이진화": {"adaptive_threshold": True},
    "T:Sauvola": {"thresholding": 2},
}


def variants(base: PreprocessOptions) -> list[tuple[str, dict]]:
    """(이름, 켤 단계들). 기준 · 하나씩 더하기 · 모두 · 모두에서 하나씩 빼기."""
    out = [("기준", {})]
    out += [(f"+{name}", {name: on}) for name, on in STEPS.items()]
    out.append(("모두", dict(STEPS)))
    out += [(f"모두 −{name}", {k: v for k, v in STEPS.items() if k != name}) for name in STEPS]
    return out


GRID_STEPS = ("②자르기", "④조명", "⑤기울기", "⑥적응이진화")


def grid() -> list[tuple[str, dict]]:
    """GRID_STEPS를 켜고 끄는 모든 조합. 이름은 켠 단계 번호만 ('②⑥')."""
    out = []
    for flags in product((False, True), repeat=len(GRID_STEPS)):
        on = [name for name, flag in zip(GRID_STEPS, flags, strict=True) if flag]
        out.append(("".join(name[0] for name in on) or "기준", {name: STEPS[name] for name in on}))
    return out


def _setup(base: PreprocessOptions, steps: dict[str, dict]) -> tuple[PreprocessOptions, int]:
    fields = {k: v for on in steps.values() for k, v in on.items()}
    thresholding = fields.pop("thresholding", 0)
    return replace(base, **fields), thresholding


def main() -> None:
    ap = argparse.ArgumentParser(description="전처리 단계 Ablation")
    ap.add_argument("--split", default="dev", choices=["all", "dev", "test"])
    ap.add_argument("--samples", type=Path, default=SAMPLES)
    ap.add_argument("--grid", action="store_true", help="하나씩 더하고 빼는 대신 ②④⑤⑥의 모든 조합을 돌린다")
    ap.add_argument("--only", nargs="+", help="이 이름의 설정만 돌린다 (예: 기준 모두 ②⑥)")
    ap.add_argument("--engine", default="tesseract", help="엔진 (설정은 콜론 뒤에: easyocr:width_ths=0.1)")
    ap.add_argument("--base", nargs="*", default=[], help="모든 설정에 깔 전처리 값 (grayscale=false min_width=1 등)")
    ap.add_argument("--out", type=Path, help="결과 표를 저장할 .md 파일")
    args = ap.parse_args()

    samples = load_samples(args.samples, args.split)
    if not samples:
        raise SystemExit(f"샘플이 없습니다: {args.samples}")
    base = PreprocessOptions(**parse_settings(args.base))
    engines: dict[int, object] = {}  # Tesseract 흑백 나누기 방식(T:Sauvola)마다 엔진 하나
    real_names = [s for s, _, _ in samples if "_real_" in s]
    md = [
        f"샘플 {len(samples)}장 ({args.split}): 가짜 {len(samples) - len(real_names)}장 · 진짜 {len(real_names)}장",
        "",
        "| 설정 | 가짜 합계 | 가짜 F1 | 진짜 합계 | 진짜 F1 | 진짜 금액 인식 | 진짜 이름 인식 | "
        + " | ".join(real_names)
        + " | 평균 시간 |",
        "| --- | --- | --- | --- | --- | --- | --- | " + " | ".join("---" for _ in real_names) + " | --- |",
    ]
    for name, steps in grid() if args.grid else variants(base):
        if args.only and name not in args.only:
            continue
        prep, thresholding = _setup(base, steps)
        if thresholding and not args.engine.startswith("tesseract"):
            continue  # Sauvola는 Tesseract 안의 설정
        if thresholding not in engines:
            sep = "," if ":" in args.engine else ":"
            engines[thresholding] = make_engine(
                f"{args.engine}{sep}thresholding={thresholding}" if thresholding else args.engine
            )
        rows = evaluate(engines[thresholding], samples, prep)
        fake = [r for r in rows if "_real_" not in r["sample"]]
        real = [r for r in rows if "_real_" in r["sample"]]
        f, r = (_summary(part) if part else None for part in (fake, real))
        per = [f"{'O' if x['total'] else 'X'} {x['hit']}/{x['expected']} (+{len(x['extra'])})" for x in real]
        cell = lambda s, k, fmt: format(s[k], fmt) if s else "-"  # noqa: E731
        md.append(
            f"| {name} | {cell(f, 'total', '.0f')}% | {cell(f, 'f1', '.2f')} | {cell(r, 'total', '.0f')}% | "
            f"{cell(r, 'f1', '.2f')} | {cell(r, 'amount', '.2f')} | {cell(r, 'name', '.2f')} | "
            + " | ".join(per)
            + f" | {_summary(rows)['sec']:.1f}초 |"
        )
        print(md[-1], flush=True)
    md += ["", f"엔진: {args.engine}. 진짜 사진 칸: 합계 O/X · 맞힌 품목/정답 품목 (+엉뚱한 품목)"]
    text = "\n".join(md)
    print("\n" + text)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
