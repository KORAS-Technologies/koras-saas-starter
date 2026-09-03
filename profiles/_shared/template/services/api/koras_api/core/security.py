"""Response headers, on every response including the ones nobody finished.

None of this replaces authorisation. It removes the browser-side footguns that
turn one mistake elsewhere into an exploitable one.

Promoted from the Control Plane as TS-13. Until this file existed, the
generated API served **no** security headers at all: the Next applications set
theirs in `next.config`, and the API -- which is the thing holding the data --
set none. That gap reached every generated project.

Deliberately only the headers. The Control Plane's version of this module also
carries a rate limiter, and that one is *not* promoted: `koras_ratelimit` and
`core/ratelimit.py` already do it here, in Redis, with a two-tier design that
survives more than one machine. Shipping both would give a product two limiters
disagreeing about the same request, which is worse than either alone.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from .settings import settings

Handler = Callable[[Request], Awaitable[Response]]

# The API returns JSON to programs. It is never framed, never rendered as a
# document, and loads nothing -- so the policy can be the most restrictive one
# there is rather than a negotiated set.
#
# If a route ever serves a document, this is the wrong default for it, and the
# right response is a narrower policy on that route rather than a wider one
# here.
_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'; sandbox",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=(), payment=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Set the headers on every response, including errors.

    Errors especially: a 500 rendered without `nosniff` is still a response a
    browser will guess a type for, and the responses most worth protecting are
    the ones a handler did not finish producing.

    `setdefault` rather than assignment, so a route that has deliberately set
    one of these keeps it. A middleware that overwrites a considered decision is
    one people work around.
    """

    async def dispatch(self, request: Request, call_next: Handler) -> Response:
        response = await call_next(request)
        for name, value in _HEADERS.items():
            response.headers.setdefault(name, value)

        # HSTS only where TLS is actually terminated. Sending it from a local
        # http listener pins the developer's browser to https for localhost and
        # breaks every other project on that machine -- and it is not undone by
        # removing the header again, which is what makes it worth guarding.
        if settings.environment.value != "dev":
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response
