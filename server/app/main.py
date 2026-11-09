"""같이정산 API 서버. 실행 중 API 문서는 /docs (Swagger), /redoc."""

from __future__ import annotations

import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from .api.v1 import router as v1_router
from .core.config import settings
from .core.errors import install_error_handlers, internal_error_response

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("settle")


def create_app() -> FastAPI:
    app = FastAPI(title="같이정산 API", version="0.1.0", description="영수증은 사진으로, 분담 조건은 말로.")
    install_error_handlers(app)
    app.include_router(v1_router)

    # 미들웨어는 나중에 붙인 것이 바깥쪽이다. 순서: CORS(바깥) → request_id → 라우터(안쪽)
    #
    # 처리하지 못한 예외를 FastAPI의 Exception 처리기에 맡기면, 그 처리기는 모든 미들웨어 바깥에서 돌아서
    # 500 응답에 X-Request-Id와 CORS 헤더가 빠진다 (화면에는 오류 문장 대신 CORS 오류만 보임).
    # 그래서 request_id 미들웨어에서 예외를 잡아 500으로 바꾸고, CORS를 그 바깥에 둬서 두 헤더가 항상 붙게 한다.

    @app.middleware("http")
    async def request_id(request: Request, call_next):
        """요청마다 X-Request-Id를 붙인다. 화면에서 오류를 알려 줄 때 이 값으로 서버 로그를 찾는다."""
        rid = request.headers.get("X-Request-Id") or uuid.uuid4().hex
        request.state.request_id = rid
        try:
            response = await call_next(request)
        except Exception:
            log.exception("unhandled error (request_id=%s) %s %s", rid, request.method, request.url.path)
            response = internal_error_response()
        response.headers["X-Request-Id"] = rid
        return response

    app.add_middleware(
        CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
        allow_methods=["*"], allow_headers=["*"], expose_headers=["X-Request-Id"],
    )
    return app


app = create_app()
