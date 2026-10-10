"""One error shape for every failure: {"error": {"code", "message"}, "disclaimer"}."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.constants import DISCLAIMER
from app.core.logging import get_logger

log = get_logger(__name__)


def error_response(code: int, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=code,
        content={"error": {"code": code, "message": message}, "disclaimer": DISCLAIMER},
    )


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return error_response(exc.status_code, str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(x) for x in first.get("loc", []))
        return error_response(422, f"invalid request: {loc} {first.get('msg', '')}".strip())

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error", exc_info=exc)
        return error_response(500, "internal server error")
