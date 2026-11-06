"""상태 확인 API. 화면 연결 확인과 Docker Compose 헬스체크에 쓴다. (DB를 붙이는 PR에서 DB 연결 확인을 더한다)"""

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["health"])


class HealthOut(BaseModel):
    status: str


@router.get("/health", response_model=HealthOut, summary="상태 확인")
def health() -> HealthOut:
    return HealthOut(status="ok")
