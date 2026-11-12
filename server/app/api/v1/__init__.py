"""/api/v1 아래 API를 모은다. 새 기능 라우터는 여기 목록에 더한다."""

from fastapi import APIRouter

from . import checks, health, receipts, rooms, settlements

router = APIRouter(prefix="/api/v1")
for module in (health, rooms, receipts, checks, settlements):
    router.include_router(module.router)
