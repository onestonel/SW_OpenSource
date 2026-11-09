"""오류 응답 형식과 예외 처리기.

모든 오류는 {"error": {"code", "message", "details"}} 로 내려간다.
화면은 code로 분기하고, message는 사용자에게 그대로 보여 줄 수 있는 한국어 문장이다.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("settle.errors")


class AppError(Exception):
    """API에서 의도적으로 내는 오류. raise AppError(409, "MEMBER_NAME_DUPLICATE", "같은 이름의 구성원이 이미 있습니다.")"""

    def __init__(self, status: int, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details


def error_response(status: int, code: str, message: str, details: dict[str, Any] | None = None) -> JSONResponse:
    body: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        body["details"] = details
    return JSONResponse(status_code=status, content={"error": body})


_HTTP_CODES = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}
_HTTP_MESSAGES = {
    404: "요청한 주소를 찾을 수 없습니다.",
    405: "허용되지 않은 메서드입니다.",
}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, e: AppError) -> JSONResponse:
        return error_response(e.status, e.code, e.message, e.details)

    @app.exception_handler(RequestValidationError)
    async def handle_validation(_: Request, e: RequestValidationError) -> JSONResponse:
        fields = [
            {"loc": ".".join(str(p) for p in err.get("loc", ()) if p != "body"), "msg": err.get("msg", "")}
            for err in e.errors()
        ]
        return error_response(422, "VALIDATION_ERROR", "입력값을 확인해 주세요.", {"fields": fields})

    @app.exception_handler(StarletteHTTPException)
    async def handle_http(_: Request, e: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_CODES.get(e.status_code, "BAD_REQUEST")
        message = _HTTP_MESSAGES.get(e.status_code, str(e.detail))
        return error_response(e.status_code, code, message)

    @app.exception_handler(Exception)
    async def handle_unexpected(_: Request, e: Exception) -> JSONResponse:
        log.exception("unhandled error: %s", e)
        return error_response(500, "INTERNAL_ERROR", "서버 오류가 발생했습니다.")
