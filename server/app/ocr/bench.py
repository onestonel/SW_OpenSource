"""평가 데이터로 OCR 점수 매기기 (llm/bench.py와 같은 방식).

    python -m app.ocr.bench                                     # tesseract로 모든 샘플
    python -m app.ocr.bench --engine tesseract easyocr --out results.md
    python -m app.ocr.bench --split dev --show-errors           # 규칙을 고칠 때: 틀린 샘플의 줄 판단까지 출력

샘플 = samples/이름.jpg|png + samples/이름.json(정답, API 약속서 영수증 모양).
dev_로 시작하면 규칙을 고칠 때 보는 것, test_로 시작하면 처음 보는 것(진짜 실력).
점수를 올리려고 test 샘플을 보며 규칙을 고치지 않는다.
"""

from __future__ import annotations

import argparse
import json
import re
from difflib import SequenceMatcher
from pathlib import Path

from .engines import ENGINES, TesseractEngine, get_engine
from .pipeline import run_ocr
from .preprocess import PreprocessOptions

SAMPLES = Path(__file__).parent / "samples"


def _norm(text: str | None) -> str:
    return re.sub(r"[\W_]+", "", text or "").lower()


def similar(a: str | None, b: str | None) -> float:
    a, b = _norm(a), _norm(b)
    return 1.0 if a == b else SequenceMatcher(None, a, b).ratio()


def score(expected: dict, draft: dict, name_threshold: float = 0.7) -> dict:
    """정답과 초안 비교. 품목은 금액 · 종류가 같고 이름이 name_threshold 이상 비슷하면 맞힌 것으로 본다."""
    left = list(draft["items"])
    missed = []
    for exp in expected["items"]:
        candidates = [g for g in left if g["amount"] == exp["amount"] and g["kind"] == exp["kind"]]
        best = max(candidates, key=lambda g: similar(exp["name"], g["name"]), default=None)
        if best is not None and similar(exp["name"], best["name"]) >= name_threshold:
            left.remove(best)
        else:
            missed.append(exp)
    hit = len(expected["items"]) - len(missed)
    result = {
        "store": similar(expected["store_name"], draft["store_name"]) >= 0.8,
        "total": expected["total_amount"] == draft["total_amount"],
        "hit": hit,
        "expected": len(expected["items"]),
        "predicted": len(draft["items"]),
        "missed": missed,
        "extra": left,
    }
    result["perfect"] = result["store"] and result["total"] and not missed and not left
    return result


def load_samples(folder: Path, split: str) -> list[tuple[str, Path, dict]]:
    out = []
    for answer in sorted(folder.glob("*.json")):
        if split != "all" and not answer.stem.startswith(f"{split}_"):
            continue
        image = next(
            (answer.with_suffix(ext) for ext in (".jpg", ".jpeg", ".png") if answer.with_suffix(ext).exists()), None
        )
        if image:
            out.append((answer.stem, image, json.loads(answer.read_text(encoding="utf-8"))))
    return out


def _summary(rows: list[dict]) -> dict:
    hit, exp, pred = (sum(r[k] for r in rows) for k in ("hit", "expected", "predicted"))
    p, r = (hit / pred if pred else 0), (hit / exp if exp else 0)
    pct = lambda key: 100 * sum(row[key] for row in rows) / len(rows)  # noqa: E731
    return {
        "n": len(rows),
        "store": pct("store"),
        "total": pct("total"),
        "perfect": pct("perfect"),
        "f1": 2 * p * r / (p + r) if p + r else 0,
        "sec": sum(row["ms"] for row in rows) / len(rows) / 1000,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="OCR 평가")
    ap.add_argument("--engine", nargs="+", default=["tesseract"], choices=[e for e in ENGINES if e != "stub"])
    ap.add_argument("--split", default="all", choices=["all", "dev", "test"])
    ap.add_argument("--samples", type=Path, default=SAMPLES)
    ap.add_argument("--psm", type=int, default=6, help="tesseract 쪽 나누기 방식")
    ap.add_argument("--lang", default="kor", help="tesseract 언어 (kor+eng: 영어 섞인 메뉴가 많을 때)")
    ap.add_argument(
        "--min-width", type=int, default=PreprocessOptions.min_width, help="전처리: 이보다 작은 사진은 키운다"
    )
    ap.add_argument("--out", type=Path, help="결과 표를 저장할 .md 파일")
    ap.add_argument("--show-errors", action="store_true", help="틀린 샘플의 줄 판단을 출력")
    args = ap.parse_args()

    samples = load_samples(args.samples, args.split)
    if not samples:
        raise SystemExit(f"샘플이 없습니다: {args.samples} (python -m app.ocr.synth 로 가짜 영수증을 먼저 그리세요)")
    rows = []
    prep = PreprocessOptions(min_width=args.min_width, max_width=max(args.min_width, PreprocessOptions.max_width))
    for name in args.engine:
        engine = TesseractEngine(lang=args.lang, psm=args.psm) if name == "tesseract" else get_engine(name)
        for sample, image, expected in samples:
            result = run_ocr(image.read_bytes(), engine, prep=prep).to_dict()
            row = score(expected, result["draft"]) | {"sample": sample, "engine": name, "ms": result["elapsed_ms"]}
            rows.append(row)
            if args.show_errors and not row["perfect"]:
                print(f"\n=== {sample} ({name}) 틀린 곳: 빠짐 {row['missed']} · 엉뚱함 {row['extra']}")
                print(f"    정답 가게 {expected['store_name']} / 합계 {expected['total_amount']:,}")
                print(f"    읽은 가게 {result['draft']['store_name']} / 합계 {result['draft']['total_amount']}")
                for line in result["lines"]:
                    print(f"    {line['role']:9} {line['confidence']:.2f} | {line['text']}")

    md = [
        "## 엔진별 요약",
        "",
        "| 엔진 | 나눔 | 장수 | 가게 이름 | 합계 금액 | 품목 F1 | 완벽 | 평균 시간 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for name in args.engine:
        for split in ("dev", "test", "all"):
            part = [r for r in rows if r["engine"] == name and (split == "all" or r["sample"].startswith(f"{split}_"))]
            if part:
                s = _summary(part)
                md.append(
                    f"| {name} | {split} | {s['n']} | {s['store']:.0f}% | {s['total']:.0f}% | {s['f1']:.2f} | {s['perfect']:.0f}% | {s['sec']:.1f}초 |"
                )
    md += ["", "## 샘플별", "", "| 샘플 | 엔진 | 가게 | 합계 | 품목 | 시간 |", "| --- | --- | --- | --- | --- | --- |"]
    for r in rows:
        ok = lambda b: "O" if b else "X"  # noqa: E731
        md.append(
            f"| {r['sample']} | {r['engine']} | {ok(r['store'])} | {ok(r['total'])} | {r['hit']}/{r['expected']} (+{len(r['extra'])}) | {r['ms'] / 1000:.1f}초 |"
        )
    text = "\n".join(md)
    print("\n" + text)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
