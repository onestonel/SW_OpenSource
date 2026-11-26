"""AI 총무 판단 기록(nl_logs) 집계. 정산방 하나(API) 또는 전체(scripts/nl_report.py)에 같이 쓴다.

보는 것:
- AI가 어떻게 답했나: 상태별 개수 (변경안 · 되묻기 · 지원 안 함)
- 사용자가 어떻게 했나: 반영 · 반영 안 하고 다른 말 · 되물음에 답함, 반영한 뒤 손으로 고친 비율
- 서버가 무엇을 고쳤나: 보정 종류별 횟수
- 규칙 표: 모델이 원래 고른 규칙(행) × 서버가 고친 뒤 규칙(열). 대각선 밖이 서버 보정이 바꾼 것이다
주의: '반영'은 사용자가 받아들였다는 뜻이지 정답이라는 뜻은 아니다. 틀린 것을 못 보고 반영할 수도 있어서,
반영 뒤 손으로 고친 기록(manual_fixes)과 함께 본다.
"""

from __future__ import annotations

from collections import Counter
from itertools import zip_longest
from typing import Any

from .models import NlLog

RULES = ["EQUAL", "EXCLUDE", "FULL", "PAID", "WEIGHTED", "QUANTITY", "NEEDS_CLARIFICATION", "UNSUPPORTED"]


def _rate(n: int, d: int) -> float | None:
    return round(n / d, 3) if d else None


def summarize(entries: list[NlLog]) -> dict[str, Any]:
    proposals = [e for e in entries if e.status == "PARSED" and e.changes]
    applied = [e for e in proposals if e.outcome == "APPLIED"]
    fixed = [e for e in applied if e.manual_fixes]
    pairs = Counter()
    for e in entries:
        for m, f in zip_longest(e.model_rules or ["(없음)"], e.final_rules or ["(없음)"], fillvalue="(없음)"):
            pairs[(m, f)] += 1
    rows = sorted({m for m, _ in pairs}, key=lambda r: RULES.index(r) if r in RULES else len(RULES))
    cols = sorted({f for _, f in pairs}, key=lambda r: RULES.index(r) if r in RULES else len(RULES))
    times = [e.elapsed_ms for e in entries if e.provider != "stub"]
    return {
        "total": len(entries),
        "by_status": dict(Counter(e.status for e in entries)),
        "by_outcome": dict(Counter(e.outcome or "결과 없음" for e in entries)),
        "proposals": len(proposals),
        "applied": len(applied),
        "apply_rate": _rate(len(applied), len(proposals)),
        "fixed_after_apply": len(fixed),
        "fix_rate": _rate(len(fixed), len(applied)),
        "repairs": dict(Counter(r for e in entries for r in e.repairs)),
        "repaired_entries": sum(1 for e in entries if e.repairs),
        "by_provider": dict(Counter(e.provider for e in entries)),
        "escalated": sum(1 for e in entries if "큰 모델로 넘김" in e.repairs),
        "rule_matrix": {"rows": rows, "cols": cols, "cells": [[pairs[(r, c)] for c in cols] for r in rows]},
        "elapsed_ms": {"avg": round(sum(times) / len(times)) if times else None, "max": max(times, default=None)},
    }


def entry_out(e: NlLog) -> dict[str, Any]:
    return {
        "id": e.id, "text": e.text, "status": e.status, "outcome": e.outcome, "provider": e.provider,
        "model_rules": e.model_rules, "final_rules": e.final_rules, "repairs": e.repairs,
        "changes": [{"name": c["name"], "rule": c["rule"], "after_member_ids": c["after_member_ids"]} for c in e.changes],
        "manual_fixes": e.manual_fixes, "elapsed_ms": e.elapsed_ms, "created_at": e.created_at,
    }
