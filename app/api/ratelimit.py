"""Fixed-window rate limiter (per client IP, per minute), backed by the shared cache."""

import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.api.errors import error_response
from app.core.constants import DISCLAIMER

EXEMPT = ("/health", "/docs", "/openapi.json", "/redoc")


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, limit_per_minute: int) -> None:
        super().__init__(app)
        self.limit = limit_per_minute

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path.startswith(EXEMPT) or self.limit <= 0:
            response = await call_next(request)
        else:
            ip = request.client.host if request.client else "unknown"
            window = int(time.time() // 60)
            count = request.app.state.cache.incr_window(f"rl:{ip}:{window}", 60)
            if count > self.limit:
                response = error_response(
                    429, f"rate limit exceeded ({self.limit} requests/minute)"
                )
                response.headers["Retry-After"] = str(60 - int(time.time()) % 60)
            else:
                response = await call_next(request)
        response.headers["X-PumpGuard-Disclaimer"] = DISCLAIMER
        return response
