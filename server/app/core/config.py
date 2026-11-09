"""환경 변수 → Settings. DB 주소 등은 해당 기능을 넣는 PR에서 더한다."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _list(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


@dataclass(frozen=True)
class Settings:
    cors_origins: list[str] = field(default_factory=lambda: ["http://localhost:3000"])


def load_settings() -> Settings:
    return Settings(
        cors_origins=_list(os.getenv("CORS_ORIGINS", "http://localhost:3000")),
    )


settings = load_settings()
