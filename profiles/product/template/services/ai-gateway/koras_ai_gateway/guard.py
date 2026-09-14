"""Refuse an unauthenticated request before the proxy sees it.

LiteLLM answers a request with no bearer by raising an authentication error
and then, while classifying that error, importing Prisma to ask whether it
was really a database outage. This image ships no Prisma -- the proxy runs
without its key store on purpose -- so the classification itself fails and
the caller gets a 500 where a 401 was meant. Harmless to the product, which
always sends the master key, and misleading to anyone probing the gateway
by hand: a 500 says "the gateway is broken" when the truth is "you did not
say who you are".

This middleware answers that case itself: no `Authorization` header, no
proxy. The health endpoints stay open, because the platform's probes carry
no key and a liveness check that needs a credential is not a liveness
check. Nothing here validates the key -- that stays LiteLLM's, and a wrong
key still gets LiteLLM's answer -- it only refuses the request that carries
none.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

_REFUSAL = (
    b'{"error":{"message":"Authentication required: send the gateway key as a bearer",'
    b'"type":"authentication_error","code":"401"}}'
)


def is_open(path: str) -> bool:
    """Liveness, readiness and the root answer without a credential."""
    return path in {"/", "/health"} or path.startswith("/health/")


class RequireBearer:
    """ASGI middleware: 401 for an HTTP request with no Authorization header."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http" or is_open(str(scope.get("path", ""))):
            await self._app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or ())
        if headers.get(b"authorization"):
            await self._app(scope, receive, send)
            return
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(_REFUSAL)).encode()),
                    (b"www-authenticate", b"Bearer"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": _REFUSAL})
