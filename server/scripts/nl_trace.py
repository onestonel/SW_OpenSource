"""문장 하나가 AI 총무 안에서 어떻게 바뀌는지 네 단계로 출력한다 (발표 자료 캡처용). 저장하지 않는다.

    docker compose exec server python scripts/nl_trace.py <정산방 토큰> "해장국이랑 김밥" --previous "수아는 아침 안 먹었어"

① AI에게 들어가는 데이터 (이름 대신 id 번호)
② 모델이 낸 원래 답 (JSON)
③ 서버 검사 · 보정 (무엇을 고쳤는지)
④ 최종 변경안 (화면의 "이렇게 바꿀까요?")
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app import nl  # noqa: E402
from app.api.v1.checks import _checks_out  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.db import make_engine  # noqa: E402
from app.models import Receipt, Room  # noqa: E402


def show(title: str, data) -> None:
    """짧은 목록([4], ["민수", "지영"])은 한 줄로 접어서 슬라이드에 넣기 좋게 출력한다."""
    print(f"\n━━ {title} ━━")
    if isinstance(data, str):
        print(data)
        return
    out = json.dumps(data, ensure_ascii=False, indent=2)
    out = re.sub(r"\[\s+([^\[\]{}]*?)\s+\]", lambda m: "[" + ", ".join(t.strip() for t in m.group(1).split(",")) + "]", out)
    print(out)


def main() -> None:
    args = [a for a in sys.argv[1:]]
    previous = None
    if "--previous" in args:
        i = args.index("--previous")
        previous = args[i + 1]
        del args[i:i + 2]
    if len(args) != 2:
        sys.exit(__doc__)
    token, text = args
    with Session(make_engine(settings.database_url)) as db:
        room = db.scalar(select(Room).where(Room.room_token == token))
        if room is None:
            sys.exit("정산방을 찾지 못했습니다. 토큰을 확인해 주세요.")
        checks = _checks_out(db, room)
        payer_of = dict(db.execute(select(Receipt.id, Receipt.payer_member_id).where(Receipt.room_id == room.id)).all())
    data = nl.RoomData(
        members=[(m.id, m.name) for m in checks.members],
        items=[nl.Item(id=i.item_id, name=i.name, amount=i.amount, receipt_id=i.receipt_id, store_name=i.store_name,
                       member_ids=list(i.member_ids), payer_id=payer_of[i.receipt_id]) for i in checks.items],
    )
    full = f"{previous} {text}" if previous else text
    ctx = data.context()
    line = lambda x: json.dumps(x, ensure_ascii=False)  # noqa: E731  한 줄에 하나씩 (슬라이드에 넣기 좋게)
    show("① AI에게 들어가는 데이터", "{\n  \"members\": [\n"
         + ",\n".join(f"    {line(m)}" for m in ctx["members"]) + "\n  ],\n  \"items\": [\n"
         + ",\n".join(f"    {line(i)}" for i in ctx["items"]) + f"\n  ],\n  \"문장\": {line(full)}\n}}")
    res = nl.interpret(data, text, previous)
    raw = res["trace"]["raw"]
    try:
        show("② 모델이 낸 원래 답", json.loads(raw))
    except json.JSONDecodeError:
        show("② 모델이 낸 원래 답", raw)
    show("③ 서버 검사 · 보정", {"모델이 고른 규칙": res["trace"]["model_rules"], "서버가 고친 것": res["trace"]["repairs"],
                            "최종 규칙": res["trace"]["final_rules"], "해석기": res["provider"]})
    names = dict(data.members)
    show("④ 최종 변경안 (화면)", {"message": res["message"], "changes": [
        {"품목": c["name"], "규칙": c["rule"], "체크": [names[m] for m in c["after_member_ids"]],
         **({"금액": f"{c['before_amount']:,} → {c['after_amount']:,}"} if c["after_amount"] != c["before_amount"] else {})}
        for c in res["changes"]]})
    print(f"\n({res['elapsed_ms'] / 1000:.1f}초, 저장하지 않았습니다)")


if __name__ == "__main__":
    main()
