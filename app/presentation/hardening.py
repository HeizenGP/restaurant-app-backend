"""Streaming-safe HTTP hardening; never buffer bodies or log request secrets."""

import logging
import re
from uuid import uuid4

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}


def apply_headers(headers: MutableHeaders, request_id: str) -> None:
    for name, value in SECURITY_HEADERS.items():
        headers[name] = value
    headers["X-Request-ID"] = request_id


class HardeningMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        supplied = Headers(scope=scope).get("x-request-id", "")
        request_id = (
            supplied
            if re.fullmatch(r"[A-Za-z0-9._:-]{1,64}", supplied)
            else str(uuid4())
        )
        scope.setdefault("state", {})["request_id"] = request_id

        async def safe_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                apply_headers(MutableHeaders(scope=message), request_id)
                logger.info(
                    "HTTP response request_id=%s method=%s status=%s",
                    request_id,
                    scope["method"],
                    message["status"],
                )
            await send(message)

        await self.app(scope, receive, safe_send)
