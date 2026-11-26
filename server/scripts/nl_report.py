"""AI 총무 기록 전체 집계를 표로 출력한다 (모든 정산방).

    docker compose exec server python scripts/nl_report.py          집계
    docker compose exec server python scripts/nl_report.py --list   기록 하나하나까지
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.db import make_engine  # noqa: E402
from app.models import NlLog  # noqa: E402
from app.nl_report import summarize  # noqa: E402

LABEL = {"NEEDS_CLARIFICATION": "ASK"}  # 나머지는 영어 코드 그대로 (EQUAL · EXCLUDE · FULL · PAID …)


def pct(x: float | None) -> str:
    return "-" if x is None else f"{x * 100:.0f}%"


def main() -> None:
    with Session(make_engine(settings.database_url)) as db:
        entries = list(db.scalars(select(NlLog).order_by(NlLog.id)).all())
    s = summarize(entries)
    print(f"AI 총무 기록 {s['total']}건\n")
    print("AI 답:     " + ", ".join(f"{k} {v}" for k, v in s["by_status"].items()))
    print("사용자:    " + ", ".join(f"{k} {v}" for k, v in s["by_outcome"].items()))
    print(f"반영 비율: {s['applied']}/{s['proposals']} ({pct(s['apply_rate'])})"
          f"   반영 뒤 손으로 고침: {s['fixed_after_apply']}/{s['applied']} ({pct(s['fix_rate'])})")
    print(f"서버 보정: {s['repaired_entries']}건 — " + (", ".join(f"{k} {v}" for k, v in s["repairs"].items()) or "없음"))
    print("해석기:    " + ", ".join(f"{k} {v}" for k, v in s["by_provider"].items())
          + f"   (큰 모델로 넘김 {s['escalated']}건)")
    t = s["elapsed_ms"]
    print(f"걸린 시간: 평균 {t['avg'] or '-'}ms, 최대 {t['max'] or '-'}ms (stub 제외)\n")
    m = s["rule_matrix"]
    w = 10
    print("규칙 표 (행: 모델이 고른 규칙, 열: 서버가 고친 뒤 규칙)")
    print(" " * w + "".join(f"{LABEL.get(c, c):>{w}}" for c in m["cols"]))
    for r, row in zip(m["rows"], m["cells"], strict=True):
        print(f"{LABEL.get(r, r):<{w}}" + "".join(f"{v:>{w}}" for v in row))
    if "--list" in sys.argv:
        print("\n기록")
        for e in entries:
            fix = f"  손으로 고침 {len(e.manual_fixes)}" if e.manual_fixes else ""
            rep = f"  보정 {e.repairs}" if e.repairs else ""
            print(f"#{e.id:<4} {e.status:<20} {str(e.outcome or '-'):<9} {e.elapsed_ms:>6}ms  {e.text}{rep}{fix}")


if __name__ == "__main__":
    main()
