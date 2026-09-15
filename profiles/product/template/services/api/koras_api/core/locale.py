"""Which language a request's side effects are written in.

The API renders no page, so it needs no language for its answers -- the
web tier maps a `code` to a sentence in the reader's language, and the
`message` beside it is for the log. What the API *does* write for a person
is mail: the assistant's approval notice, a scheduled report's delivery.
Those are composed here, after the response, and the request is the last
moment anybody knows what language the person was reading.

Resolved from `Accept-Language`, the standard header for exactly this,
negotiated against the languages `koras_email` can speak. The web tier
sends the locale it resolved for the page as this header when it calls the
API on the person's behalf -- a cookie is scoped to the web host and never
reaches the API's origin, so the header is the one channel there is. A
request carrying none is answered in the product's default language, which
is what the page would have shown a visitor who never chose.

A body field may say the same thing more precisely -- a schedule names the
language its deliveries are written in, because the person who reads them
may not be the person who created it -- and where one exists it wins.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from koras_email import DEFAULT_LOCALE, Locale, negotiate_locale


def request_locale(request: Request) -> Locale:
    return negotiate_locale(request.headers.get("accept-language"), fallback=DEFAULT_LOCALE)


RequestLocale = Annotated[Locale, Depends(request_locale)]

__all__ = ["RequestLocale", "request_locale"]
