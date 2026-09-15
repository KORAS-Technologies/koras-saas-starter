"""The mail catalogue: three languages that say the same thing.

Most of what the catalogue promises is checked by mypy rather than here --
a missing key in one language does not typecheck. What a test adds is the
part a type cannot say: that every translation keeps the placeholders the
English sentence has, that negotiation reads a browser header the way the
TypeScript package does, and that nothing here ever raises on bad input,
because a mail in the wrong language is a defect and a mail not sent is a
worse one.
"""

from __future__ import annotations

import re
from typing import cast

from koras_email import (
    DEFAULT_LOCALE,
    MESSAGES,
    SUPPORTED_LOCALES,
    negotiate_locale,
    resolve_locale,
    translate,
)

_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def test_every_language_keeps_every_placeholder() -> None:
    """A translation that dropped `{where}` is a notice with no link in it."""
    english = cast(dict[str, str], MESSAGES["en"])
    for locale in SUPPORTED_LOCALES:
        for key, sentence in cast(dict[str, str], MESSAGES[locale]).items():
            expected = set(_PLACEHOLDER.findall(english[key]))
            assert set(_PLACEHOLDER.findall(sentence)) == expected, f"{locale}: {key}"


def test_no_translation_is_left_blank() -> None:
    for locale in SUPPORTED_LOCALES:
        for key, sentence in cast(dict[str, str], MESSAGES[locale]).items():
            assert sentence.strip(), f"{locale}: {key} is empty"


def test_translate_fills_placeholders_and_leaves_an_unfilled_one_visible() -> None:
    assert (
        translate("de", "approval_subject_one", product="Acme", first="Datei löschen")
        == "[Acme] Freigabe erforderlich: Datei löschen"
    )
    # Seen in review rather than silently blank.
    assert translate("en", "approval_requested_at") == "Requested {when}."


def test_resolve_locale_never_raises_and_falls_back() -> None:
    assert resolve_locale("de") == "de"
    assert resolve_locale("fr") == DEFAULT_LOCALE
    assert resolve_locale(None) == DEFAULT_LOCALE
    assert resolve_locale(42, fallback="es") == "es"


def test_negotiation_matches_the_typescript_package() -> None:
    """`de-AT` finds `de`; quality orders; nothing on offer answers the fallback."""
    assert negotiate_locale("de-AT,de;q=0.9,en;q=0.8") == "de"
    assert negotiate_locale("en-GB;q=0.9, de;q=0.95") == "de"
    assert negotiate_locale("fr, it") == "en"
    assert negotiate_locale(None) == "en"
    assert negotiate_locale("de;q=notanumber, es") == "es"
    assert negotiate_locale("de", available=("en", "es"), fallback="es") == "es"
