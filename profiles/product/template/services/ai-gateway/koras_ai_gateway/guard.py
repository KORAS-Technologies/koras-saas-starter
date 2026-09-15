"""Refuse a request the proxy would answer wrongly, before the proxy sees it.

LiteLLM answers a request with a missing or wrong bearer by raising an
authentication error and then, while classifying that error, importing
Prisma to ask whether it was really a database outage. This image ships no
Prisma -- the proxy runs without its key store on purpose -- so the
classification itself fails and the caller gets a 400 or a 500 where a 401
was meant. Harmless to the product, which always sends the master key, and
misleading to anyone probing the gateway by hand: a 500 says "the gateway
is broken" when the truth is "you did not say who you are".

This middleware answers both cases itself. No `Authorization` header: 401.
A bearer that is not the gateway's master key, where the key is configured:
401. The comparison is constant-time and the key never appears in a
response. Where no key is configured -- a smoke test with none set -- any
bearer reaches the proxy and the answer is LiteLLM's, as before.

The health endpoints stay open, because the platform's probes carry no key
and a liveness check that needs a credential is not a liveness check.
"""

from __future__ import annotations

import hmac
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

_MISSING = (
    b'{"error":{"message":"Authentication required: send the gateway key as a bearer",'
    b'"type":"authentication_error","code":"401"}}'
)
_WRONG = b'{"error":{"message":"Invalid gateway key","type":"authentication_error","code":"401"}}'


def is_open(path: str) -> bool:
    """Liveness, readiness and the root answer without a credential."""
    return path in {"/", "/health"} or path.startswith("/health/")


def bearer_of(headers: MutableMapping[bytes, bytes]) -> str | None:
    """The bearer token, or None when the header is absent or not a bearer."""
    raw = headers.get(b"authorization")
    if not raw:
        return None
    scheme, _, token = raw.decode("latin-1").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


class RequireBearer:
    """ASGI middleware: 401 for a request with no bearer, or the wrong one."""

    def __init__(self, app: ASGIApp, key: str | None = None) -> None:
        self._app = app
        # Empty is unset: a deployment with no master key validates nothing
        # here and leaves the answer to the proxy.
        self._key = key or None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http" or is_open(str(scope.get("path", ""))):
            await self._app(scope, receive, send)
            return
        token = bearer_of(dict(scope.get("headers") or ()))
        if token is None:
            await _refuse(send, _MISSING)
            return
        if self._key is not None and not hmac.compare_digest(token, self._key):
            await _refuse(send, _WRONG)
            return
        await self._app(scope, receive, send)


async def _refuse(send: Send, body: bytes) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"www-authenticate", b"Bearer"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
