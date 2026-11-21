"""정산 결과 버전 읽기 · '최신 아님' 표시. 여러 API(영수증 · 구성원 · 정산방 설정 · 체크 표)가 같이 쓴다.

'최신 아님'이 되는 때 (API 명세서 5절): 영수증 확정 · 확정 취소 · 체크 저장 · 구성원 추가 · 삭제 · 원 단위 변경.
확인 중인 영수증을 만들거나 고치거나 지우는 것은 계산에 들어가지 않으므로 '최신 아님'으로 만들지 않는다.
(확정 영수증을 지우려면 먼저 확정 취소를 해야 하고, 그때 이미 '최신 아님'이 된다)
"""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .models import Settlement


def mark_stale(db: Session, room_id: int) -> None:
    """이 정산방의 정산 결과를 '최신 아님'으로. 커밋은 부른 쪽에서 같이 한다."""
    db.execute(update(Settlement).where(Settlement.room_id == room_id, Settlement.is_stale.is_(False))
               .values(is_stale=True))


def latest_settlement(db: Session, room_id: int) -> Settlement | None:
    return db.scalar(select(Settlement).where(Settlement.room_id == room_id)
                     .order_by(Settlement.version.desc()).limit(1))
