"""Enforce streaming body limits before multipart data is spooled or parsed."""

from typing import Any

from starlette.exceptions import HTTPException

MAX_REQUEST_BYTES = 522 * 1024 * 1024
MAX_JSON_BYTES = 2 * 1024 * 1024


class RequestBodyLimit:
    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        limit = MAX_REQUEST_BYTES
        content_type = headers.get(b"content-type", b"").lower().split(b";", 1)[0].strip()
        if content_type != b"multipart/form-data":
            limit = min(limit, MAX_JSON_BYTES)
        received = 0

        async def counted_receive() -> dict[str, Any]:
            nonlocal received
            message = await receive()
            received += len(message.get("body", b""))
            if received > limit:
                raise HTTPException(413, "Request body exceeds the safe upload limit")
            return message

        await self.app(scope, counted_receive, send)
