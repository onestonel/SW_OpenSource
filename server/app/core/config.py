"""환경 변수 → Settings."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

# docker compose의 db 컨테이너에 내 컴퓨터에서 붙을 때 주소. 컨테이너 안에서는 compose가 db:5432로 넣어 준다.
DEFAULT_DATABASE_URL = "postgresql+psycopg://app:app@localhost:5432/settle"


def _list(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


@dataclass(frozen=True)
class Settings:
    database_url: str = DEFAULT_DATABASE_URL
    cors_origins: list[str] = field(default_factory=lambda: ["http://localhost:3000"])
    receipt_storage_path: str = "./data/receipts"
    auto_migrate: bool = True  # 서버가 켜질 때 DB 테이블을 최신으로 (alembic upgrade head)


def load_settings() -> Settings:
    return Settings(
        database_url=os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL),
        cors_origins=_list(os.getenv("CORS_ORIGINS", "http://localhost:3000")),
        receipt_storage_path=os.getenv("RECEIPT_STORAGE_PATH", "./data/receipts"),
        auto_migrate=os.getenv("AUTO_MIGRATE", "true").strip().lower() in {"1", "true", "yes", "on"},
    )


settings = load_settings()
