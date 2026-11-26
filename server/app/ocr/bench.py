"""평가 데이터로 OCR 점수 매기기 (llm/bench.py와 같은 방식).

    python -m app.ocr.bench                                     # tesseract로 모든 샘플
    python -m app.ocr.bench --engine tesseract easyocr --out results.md
    python -m app.ocr.bench --engine tesseract:lang=kor_best easyocr:width_ths=0.1 --split dev   # 엔진 설정 바꿔 비교
    python -m app.ocr.bench --prep crop adaptive_threshold      # 전처리 단계 켜기
    python -m app.ocr.bench --split dev --show-errors           # 규칙을 고칠 때: 틀린 샘플의 줄 판단까지 출력

샘플 = samples/이름.jpg|png + samples/이름.json(정답, API 약속서 영수증 모양).
dev_로 시작하면 규칙을 고칠 때 보는 것, test_로 시작하면 처음 보는 것(진짜 실력).
점수를 올리려고 test 샘플을 보며 규칙을 고치지 않는다. 이름에 _real_이 있으면 진짜 사진, 없으면 가짜 영수증.

점수는 두 층이다.
- 초안 점수(가게 · 합계 · 품목 F1): 엔진 + 줄 묶기 + 파서를 거친 최종 결과
- 엔진 점수(금액 인식 · 이름 인식): 파서 없이 엔진이 읽은 글자만 본다. 파서 탓인지 엔진 탓인지 나눠 보기 위한 것
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

from .engines import TesseractEngine, make_engine, parse_settings
from .pipeline import run_ocr
from .preprocess import PreprocessOptions

SAMPLES = Path(__file__).parent / "samples"
# '69, 000' · '2 .590'처럼 천 단위 구분 기호 옆에 낀 띄어쓰기만 붙인다 ('1,680 1 1,680'의 띄어쓰기는 칸 구분이라 둔다)
_THOUSANDS = re.compile(r"(?<=\d)\s*[,.]\s*(?=\d{3}(?!\d))")


def _norm(text: str | None) -> str:
    return re.sub(r"[\W_]+", "", text or "").lower()


def similar(a: str | None, b: str | None) -> float:
    a, b = _norm(a), _norm(b)
    return 1.0 if a == b else SequenceMatcher(None, a, b).ratio()


def partial_similar(short: str, long: str) -> float:
    """short가 long의 어느 한 부분과 가장 비슷한 정도 (0~1). 줄 안에 품목 이름이 들어 있는지 볼 때 쓴다."""
    if not short or not long:
        return 0.0
    if len(short) >= len(long):
        return SequenceMatcher(None, short, long).ratio()
    best = 0.0
    for i, j, _ in SequenceMatcher(None, short, long, autojunk=False).get_matching_blocks():
        start = max(0, min(j - i, len(long) - len(short)))
        best = max(best, SequenceMatcher(None, short, long[start : start + len(short)]).ratio())
    return best


def engine_score(expected: dict, raw_lines: list[str], name_threshold: float = 0.7) -> dict:
    """파서 없이 엔진이 읽은 줄 글자만 본다. (정답 금액이 숫자로 나타난 수, 정답 이름이 비슷하게 나타난 수)

    금액은 같은 값이 여러 번 나오면 그만큼만 센다 (정답에 6,000이 둘이면 원문에도 둘 있어야 2개).
    단가와 금액이 같은 품목(수량 1)은 두 번 찍혀 있어서 한쪽만 맞게 읽어도 맞힌 것이 된다.
    """
    numbers = Counter(int(n) for line in raw_lines for n in re.findall(r"\d+", _THOUSANDS.sub("", line)))
    amounts = Counter(abs(item["amount"]) for item in expected["items"])
    texts = [_norm(line) for line in raw_lines]
    return {
        "amount_hit": sum(min(count, numbers[amount]) for amount, count in amounts.items()),
        "name_hit": sum(
            any(partial_similar(_norm(item["name"]), t) >= name_threshold for t in texts) for item in expected["items"]
        ),
    }


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
        "amount": sum(row["amount_hit"] for row in rows) / exp if exp else 0,
        "name": sum(row["name_hit"] for row in rows) / exp if exp else 0,
        "sec": sum(row["ms"] for row in rows) / len(rows) / 1000,
        "max_sec": max(row["ms"] for row in rows) / 1000,
    }


def evaluate(
    engine, samples: list, prep: PreprocessOptions | None = None, show_errors: bool = False, label: str | None = None
) -> list[dict]:
    """샘플마다 OCR → 채점. 행 = score() + engine_score() 결과 + sample · engine · ms.

    시간은 엔진의 첫 실행(모델 준비)을 빼고 잰다. 서버는 엔진을 한 번 만들어 계속 쓰기 때문이다 (get_engine).
    """
    if samples:
        run_ocr(samples[0][1].read_bytes(), engine, prep=prep)  # 예열: 결과는 버린다
    rows = []
    for sample, image, expected in samples:
        res = run_ocr(image.read_bytes(), engine, prep=prep)
        result = res.to_dict()
        row = score(expected, result["draft"]) | engine_score(expected, res.raw_lines)
        row |= {"sample": sample, "engine": label or engine.name, "ms": result["elapsed_ms"]}
        rows.append(row)
        if show_errors and not row["perfect"]:
            print(f"\n=== {sample} ({row['engine']}) 틀린 곳: 빠짐 {row['missed']} · 엉뚱함 {row['extra']}")
            print(f"    정답 가게 {expected['store_name']} / 합계 {expected['total_amount']:,}")
            print(f"    읽은 가게 {result['draft']['store_name']} / 합계 {result['draft']['total_amount']}")
            for line in result["lines"]:
                print(f"    {line['role']:9} {line['confidence']:.2f} | {line['text']}")
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description="OCR 평가")
    ap.add_argument(
        "--engine",
        nargs="+",
        default=["tesseract"],
        help="엔진 이름. 설정은 콜론 뒤에: tesseract:lang=kor_best easyocr:width_ths=0.1 paddleocr",
    )
    ap.add_argument("--split", default="all", choices=["all", "dev", "test"])
    ap.add_argument("--samples", type=Path, default=SAMPLES)
    ap.add_argument("--psm", type=int, default=6, help="tesseract 쪽 나누기 방식 (--engine tesseract일 때)")
    ap.add_argument("--lang", default="kor", help="tesseract 언어 (--engine tesseract일 때. kor+eng, kor_best 등)")
    ap.add_argument("--prep", nargs="*", default=[], help="전처리 설정 (crop adaptive_threshold min_width=1 등)")
    ap.add_argument("--min-width", type=int, help="전처리: 이보다 작은 사진은 키운다")
    ap.add_argument("--out", type=Path, help="결과 표를 저장할 .md 파일")
    ap.add_argument("--show-errors", action="store_true", help="틀린 샘플의 줄 판단을 출력")
    args = ap.parse_args()

    samples = load_samples(args.samples, args.split)
    if not samples:
        raise SystemExit(f"샘플이 없습니다: {args.samples} (python -m app.ocr.synth 로 가짜 영수증을 먼저 그리세요)")
    prep = PreprocessOptions(**parse_settings(args.prep))
    if args.min_width is not None:
        prep = PreprocessOptions(
            **(vars(prep) | {"min_width": args.min_width, "max_width": max(args.min_width, prep.max_width)})
        )
    rows = []
    for spec in args.engine:
        engine = TesseractEngine(lang=args.lang, psm=args.psm) if spec == "tesseract" else make_engine(spec)
        rows += evaluate(engine, samples, prep, args.show_errors, label=spec)

    md = [
        "## 엔진별 요약",
        "",
        "| 엔진 | 나눔 | 사진 | 장수 | 가게 | 합계 | 품목 F1 | 완벽 | 금액 인식 | 이름 인식 | 평균 시간 | 최대 시간 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for spec in args.engine:
        for split in ("dev", "test"):
            for kind, is_real in (("진짜", True), ("가짜", False)):
                part = [
                    r
                    for r in rows
                    if r["engine"] == spec
                    and r["sample"].startswith(f"{split}_")
                    and ("_real_" in r["sample"]) == is_real
                ]
                if part:
                    s = _summary(part)
                    md.append(
                        f"| {spec} | {split} | {kind} | {s['n']} | {s['store']:.0f}% | {s['total']:.0f}% | {s['f1']:.2f} | "
                        f"{s['perfect']:.0f}% | {s['amount']:.2f} | {s['name']:.2f} | {s['sec']:.1f}초 | {s['max_sec']:.1f}초 |"
                    )
    md += [
        "",
        "## 샘플별",
        "",
        "| 샘플 | 엔진 | 가게 | 합계 | 품목 | 금액 인식 | 이름 인식 | 시간 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        ok = lambda b: "O" if b else "X"  # noqa: E731
        md.append(
            f"| {r['sample']} | {r['engine']} | {ok(r['store'])} | {ok(r['total'])} | {r['hit']}/{r['expected']} (+{len(r['extra'])}) | "
            f"{r['amount_hit']}/{r['expected']} | {r['name_hit']}/{r['expected']} | {r['ms'] / 1000:.1f}초 |"
        )
    text = "\n".join(md)
    print("\n" + text)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
