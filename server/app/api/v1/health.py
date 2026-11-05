"""상태 확인 API. 화면 첫 화면의 연결 확인과 Docker Compose 헬스체크에 쓴다.

DB에 `SELECT 1`을 보내 server 컨테이너 → db 컨테이너 통신까지 확인한다.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from ..deps import DB

log = logging.getLogger("settle.health")

router = APIRouter(tags=["health"])


class HealthOut(BaseModel):
    status: str
    db: str


@router.get("/health", response_model=HealthOut, summary="상태 확인 (서버 · DB)",
            responses={503: {"model": HealthOut, "description": "DB에 연결할 수 없음"}})
def health(db: DB):
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError as e:
        log.warning("health: db unreachable: %s", e.__class__.__name__)
        return JSONResponse(status_code=503, content={"status": "error", "db": "error"})
    return HealthOut(status="ok", db="ok")
