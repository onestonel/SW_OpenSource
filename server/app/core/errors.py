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


def validation_error(field: str, reason: str, message: str = "입력값을 확인해 주세요.") -> AppError:
    """코드에서 직접 내는 입력 오류. 모양은 FastAPI 검사 실패와 같다."""
    return AppError(422, "VALIDATION_ERROR", message, {"fields": {field: reason}})


def field_reason(err: dict[str, Any]) -> str:
    """pydantic 검사 실패 한 건 → 화면에 보여 줄 짧은 한국어 이유 (API 약속서: details.fields)."""
    kind, ctx = err.get("type", ""), err.get("ctx") or {}
    if kind == "missing":
        return "필수"
    if kind == "string_too_short":
        return "빈 값은 안 됩니다" if ctx.get("min_length") == 1 else f"{ctx.get('min_length')}자 이상이어야 합니다"
    if kind == "string_too_long":
        return f"{ctx.get('max_length')}자 이하여야 합니다"
    if kind == "too_short":
        return f"{ctx.get('min_length')}개 이상이어야 합니다"
    if kind == "too_long":
        return f"{ctx.get('max_length')}개 이하여야 합니다"
    if kind == "literal_error":
        return f"{str(ctx.get('expected')).replace(' or ', ' 또는 ')} 중 하나여야 합니다"
    if kind == "greater_than":
        return f"{ctx.get('gt')}보다 커야 합니다"
    if kind == "greater_than_equal":
        return f"{ctx.get('ge'):,} 이상이어야 합니다"
    if kind == "less_than_equal":
        return f"{ctx.get('le'):,} 이하여야 합니다"
    if kind in ("int_parsing", "int_type"):
        return "정수여야 합니다"
    if kind == "extra_forbidden":
        return "알 수 없는 칸입니다"
    if kind == "value_error":
        return str(err.get("msg", "")).removeprefix("Value error, ")
    return str(err.get("msg", "올바르지 않습니다"))


def internal_error_response() -> JSONResponse:
    return error_response(500, "INTERNAL_ERROR", "서버 오류가 발생했습니다.")


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
        fields: dict[str, str] = {}
        for err in e.errors():
            loc = ".".join(str(p) for p in err.get("loc", ()) if p != "body") or "body"
            fields.setdefault(loc, field_reason(err))  # 같은 칸에 여러 이유가 있으면 첫 번째만
        return error_response(422, "VALIDATION_ERROR", "입력값을 확인해 주세요.", {"fields": fields})

    @app.exception_handler(StarletteHTTPException)
    async def handle_http(_: Request, e: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_CODES.get(e.status_code, "BAD_REQUEST")
        message = _HTTP_MESSAGES.get(e.status_code, str(e.detail))
        return error_response(e.status_code, code, message)

    @app.exception_handler(Exception)
    async def handle_unexpected(_: Request, e: Exception) -> JSONResponse:
        # 마지막 안전망. 보통의 예외는 main.py의 request_id 미들웨어가 먼저 잡아 헤더까지 붙여 보낸다.
        # 이 처리기는 미들웨어 바깥에서 돌아 X-Request-Id·CORS 헤더가 붙지 않는다.
        log.exception("unhandled error outside middleware: %s", e)
        return internal_error_response()
