"""같이정산 API 서버. 실행 중 API 문서는 /docs (Swagger), /redoc."""

from __future__ import annotations

import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from .api.v1 import router as v1_router
from .core.config import settings
from .core.errors import install_error_handlers

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def create_app() -> FastAPI:
    app = FastAPI(title="같이정산 API", version="0.1.0", description="영수증은 사진으로, 분담 조건은 말로.")

    # 화면(web, 포트 3000)이 브라우저에서 직접 부르므로 허용할 주소를 연다
    app.add_middleware(
        CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
        allow_methods=["*"], allow_headers=["*"], expose_headers=["X-Request-Id"],
    )

    @app.middleware("http")
    async def request_id(request: Request, call_next):
        """요청마다 X-Request-Id를 붙인다. 화면에서 오류를 알려 줄 때 이 값으로 서버 로그를 찾는다."""
        rid = request.headers.get("X-Request-Id") or uuid.uuid4().hex
        request.state.request_id = rid
        response = await call_next(request)
        response.headers["X-Request-Id"] = rid
        return response

    install_error_handlers(app)
    app.include_router(v1_router)
    return app


app = create_app()
