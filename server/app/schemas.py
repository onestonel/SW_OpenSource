"""요청·답장 모양 (API 약속서 docs/api-v1.md). 이름은 snake_case, 시각은 한국 시간 ISO 8601."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, StringConstraints, field_validator

KST = ZoneInfo("Asia/Seoul")


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:  # SQLite는 시간대를 저장하지 않는다. 저장값은 UTC다
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(KST).isoformat(timespec="seconds")


Timestamp = Annotated[datetime, PlainSerializer(_iso, return_type=str)]
MemberName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]
Rounding = Literal["WON_1", "WON_10"]


class In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Out(BaseModel):
    pass


# ------------------------------------------------------------------ 정산방 · 구성원 (1단계)

class RoomCreateIn(In):
    name: str = Field(min_length=1, max_length=50, description="정산방 이름 (예: 제주 여행)")
    members: list[MemberName] = Field(min_length=2, max_length=50,
                                      description="구성원 이름. 2명 이상, 빈 이름·같은 이름 불가. 입력한 순서가 구성원 순서")
    rounding: Rounding = Field(default="WON_1", description="WON_1 = 1원 단위(기본), WON_10 = 10원 단위 올림")

    @field_validator("members")
    @classmethod
    def _unique(cls, members: list[str]) -> list[str]:
        dup = sorted({n for n in members if members.count(n) > 1})
        if dup:
            raise ValueError(f"같은 이름이 있습니다: {', '.join(dup)}")
        return members


class RoomUpdateIn(In):
    name: str | None = Field(default=None, min_length=1, max_length=50)
    rounding: Rounding | None = None


class MemberCreateIn(In):
    name: MemberName


class MemberOut(Out):
    id: int
    name: str
    order: int


class LatestSettlementRef(Out):
    version: int
    is_stale: bool = Field(description="true면 영수증·체크가 바뀌어 '다시 계산'이 필요하다")


class RoomOut(Out):
    room_token: str = Field(description="정산방 링크 키. 화면은 이 값으로 정산방 주소를 만든다")
    name: str
    rounding: Rounding
    members: list[MemberOut]
    created_at: Timestamp


class RoomDetailOut(RoomOut):
    latest_settlement: LatestSettlementRef | None = Field(description="아직 한 번도 계산하지 않았으면 null")
