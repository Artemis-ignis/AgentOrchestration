"""API middleware components."""

import hmac
import logging
import os
import time
from typing import Callable, Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from src.common.metrics import metrics

logger = logging.getLogger(__name__)


class AuthMiddleware(BaseHTTPMiddleware):
    """Bearer-token auth for the API.

    The expected token comes from the `api_key` argument or the AO_API_KEY
    environment variable. When no key is configured, auth is disabled
    (local development mode).
    """

    def __init__(self, app, api_key: Optional[str] = None):
        super().__init__(app)
        self.api_key = api_key if api_key is not None else os.getenv("AO_API_KEY", "")

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if self.api_key and request.url.path.startswith("/api/v2"):
            auth = request.headers.get("Authorization", "")
            expected = f"Bearer {self.api_key}"
            if not hmac.compare_digest(auth, expected):
                return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_requests: int = 100, window: int = 60):
        super().__init__(app)
        self.max_requests = max_requests
        self.window = window
        self._requests = {}

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()

        timestamps = [t for t in self._requests.get(client_ip, []) if now - t < self.window]

        if len(timestamps) >= self.max_requests:
            return JSONResponse(status_code=429, content={"detail": "Too many requests"})

        timestamps.append(now)
        self._requests[client_ip] = timestamps
        return await call_next(request)


class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start = time.time()
        response = await call_next(request)
        duration = time.time() - start
        metrics.increment("http.requests.total")
        metrics.increment(f"http.responses.{response.status_code}")
        metrics.observe("http.request.duration", duration)
        logger.info(f"{request.method} {request.url.path} {response.status_code} {duration:.3f}s")
        return response
