"""The words a product's mail is written in, in each language it offers.

A notice that arrives in English whatever the reader chose was the one gap
`packages/i18n` could not close: mail is composed on this side, in Python,
and the TypeScript catalogue is not reachable from here. This is the same
idea in the same shape -- English is the source of truth, every other
language is typed against it, and a key present in one and not another does
not typecheck -- kept deliberately small, because what a product mails is a
handful of sentences rather than an interface.

Three languages, the same three `packages/i18n` speaks. Which of them a
product *offers* is decided in `productConfig.i18n` on the TypeScript side;
this module cannot read that file, so it speaks all three and trusts the
caller to hand it a locale the product offers. What it is handed is checked
against `SUPPORTED_LOCALES`, and a value it does not recognise falls back to
the default rather than raising: a mail in the wrong language is a defect, a
mail not sent is a worse one.

`Messages` is a `TypedDict` with every key required, so `mypy --strict`
refuses a catalogue with a line missing; `MessageKey` is the same list as a
`Literal`, so `translate` refuses a key nobody declared. The two lists have
to agree, and mypy is what checks that they do -- indexing a `TypedDict` by
a `Literal` naming a key it does not have is an error.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, TypedDict

Locale = Literal["en", "de", "es"]

SUPPORTED_LOCALES: tuple[Locale, ...] = ("en", "de", "es")
DEFAULT_LOCALE: Locale = "en"


class Messages(TypedDict):
    """Every sentence a product's mail can say. Placeholders are `{name}`."""

    # -- the assistant's approval notice (services/api, core/notify.py) --
    approval_subject_one: str
    approval_subject_many: str
    approval_asked: str
    approval_no_message: str
    approval_proposed_one: str
    approval_proposed_many: str
    approval_not_run: str
    approval_review_at: str
    approval_review_on_page: str
    approval_requested_at: str
    approval_eyebrow: str
    approval_heading: str
    approval_button: str
    approval_footer: str

    # -- a scheduled report's delivery (services/worker, tasks/reporting.py) --
    report_subject: str
    report_body: str


MessageKey = Literal[
    "approval_subject_one",
    "approval_subject_many",
    "approval_asked",
    "approval_no_message",
    "approval_proposed_one",
    "approval_proposed_many",
    "approval_not_run",
    "approval_review_at",
    "approval_review_on_page",
    "approval_requested_at",
    "approval_eyebrow",
    "approval_heading",
    "approval_button",
    "approval_footer",
    "report_subject",
    "report_body",
]

_EN: Messages = {
    "approval_subject_one": "[{product}] Approval needed: {first}",
    "approval_subject_many": "[{product}] Approval needed: {count} actions",
    "approval_asked": "{who} asked the assistant in {product}:",
    "approval_no_message": "(no message)",
    "approval_proposed_one": "The assistant proposed to:",
    "approval_proposed_many": "The assistant proposed:",
    "approval_not_run": "It has not run. It runs only if an owner or administrator approves it.",
    "approval_review_at": "Review and decide: {where}",
    "approval_review_on_page": "Review and decide on the assistant page.",
    "approval_requested_at": "Requested {when}.",
    "approval_eyebrow": "Assistant",
    "approval_heading": "Approval needed",
    "approval_button": "Review and decide",
    "approval_footer": "Requested {when}. Nothing runs until somebody decides.",
    "report_subject": "{report}: {start} to {end}",
    "report_body": (
        "Your scheduled report is attached.\n\n{report}, {start} to {end}, as {format}.\n"
    ),
}

# Formal address throughout ("Sie"), like the interface catalogue: a product a
# company rolls out to its staff, not an app a person downloads for themselves.
_DE: Messages = {
    "approval_subject_one": "[{product}] Freigabe erforderlich: {first}",
    "approval_subject_many": "[{product}] Freigabe erforderlich: {count} Aktionen",
    "approval_asked": "{who} hat den Assistenten in {product} gebeten:",
    "approval_no_message": "(keine Nachricht)",
    "approval_proposed_one": "Der Assistent schlägt vor:",
    "approval_proposed_many": "Der Assistent schlägt vor:",
    "approval_not_run": (
        "Es wurde nicht ausgeführt. Es wird nur ausgeführt, wenn ein Eigentümer oder "
        "Administrator es freigibt."
    ),
    "approval_review_at": "Prüfen und entscheiden: {where}",
    "approval_review_on_page": "Prüfen und entscheiden Sie auf der Assistenten-Seite.",
    "approval_requested_at": "Angefragt am {when}.",
    "approval_eyebrow": "Assistent",
    "approval_heading": "Freigabe erforderlich",
    "approval_button": "Prüfen und entscheiden",
    "approval_footer": "Angefragt am {when}. Nichts wird ausgeführt, bevor jemand entscheidet.",
    "report_subject": "{report}: {start} bis {end}",
    "report_body": (
        "Ihr geplanter Bericht ist angehängt.\n\n{report}, {start} bis {end}, als {format}.\n"
    ),
}

# Neutral Spanish, "usted" throughout, like the interface catalogue.
_ES: Messages = {
    "approval_subject_one": "[{product}] Aprobación necesaria: {first}",
    "approval_subject_many": "[{product}] Aprobación necesaria: {count} acciones",
    "approval_asked": "{who} pidió al asistente en {product}:",
    "approval_no_message": "(sin mensaje)",
    "approval_proposed_one": "El asistente propuso:",
    "approval_proposed_many": "El asistente propuso:",
    "approval_not_run": (
        "No se ha ejecutado. Solo se ejecuta si un propietario o administrador lo aprueba."
    ),
    "approval_review_at": "Revisar y decidir: {where}",
    "approval_review_on_page": "Revise y decida en la página del asistente.",
    "approval_requested_at": "Solicitado el {when}.",
    "approval_eyebrow": "Asistente",
    "approval_heading": "Aprobación necesaria",
    "approval_button": "Revisar y decidir",
    "approval_footer": "Solicitado el {when}. Nada se ejecuta hasta que alguien decida.",
    "report_subject": "{report}: {start} a {end}",
    "report_body": (
        "Su informe programado está adjunto.\n\n{report}, {start} a {end}, como {format}.\n"
    ),
}

MESSAGES: dict[Locale, Messages] = {"en": _EN, "de": _DE, "es": _ES}


def is_locale(value: object) -> bool:
    return isinstance(value, str) and value in SUPPORTED_LOCALES


def resolve_locale(value: object, fallback: Locale = DEFAULT_LOCALE) -> Locale:
    """A locale this module speaks, or the fallback.

    Never raises. The value came from a request body, a header or a stored
    row, and a product that stopped offering a language should mail in its
    default rather than fail to mail at all.
    """
    for locale in SUPPORTED_LOCALES:
        if value == locale:
            return locale
    return fallback


def negotiate_locale(
    accept_language: str | None,
    available: Sequence[Locale] = SUPPORTED_LOCALES,
    fallback: Locale = DEFAULT_LOCALE,
) -> Locale:
    """The best of `available` for an `Accept-Language` header.

    The same rule as `negotiateLocale` in `packages/i18n`: quality-ordered,
    exact tag first and language-only second, so `de-AT` finds `de`. A
    header naming nothing on offer, a malformed one and none at all answer
    the fallback -- there is no error state, because a browser with an
    unusual header should get the default language rather than a 500.
    """
    if not accept_language:
        return fallback
    ranked: list[tuple[float, int, str]] = []
    for index, part in enumerate(accept_language.split(",")):
        tag, _, params = part.strip().partition(";")
        tag = tag.strip().lower()
        if not tag:
            continue
        quality = 1.0
        for raw in params.split(";"):
            param = raw.strip()
            if param.startswith("q="):
                try:
                    quality = float(param[2:])
                except ValueError:
                    quality = 0.0
        if quality > 0:
            ranked.append((-quality, index, tag))
    for _, _, tag in sorted(ranked):
        for locale in available:
            if locale.lower() == tag:
                return locale
        language = tag.split("-", 1)[0]
        for locale in available:
            if locale.lower().split("-", 1)[0] == language:
                return locale
    return fallback


class _Params(dict[str, object]):
    """Leaves an unfilled `{placeholder}` visible rather than raising.

    So a gap is seen in review instead of turning into a mail that was never
    sent -- the same choice `interpolate` makes on the TypeScript side.
    """

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def translate(locale: Locale, key: MessageKey, **params: object) -> str:
    """One sentence, in one language, with its placeholders filled.

    A blank translation falls back to English so a catalogue can be committed
    with a line deliberately left empty and the mail still says something. A
    missing key cannot happen: `Messages` requires every one.
    """
    message = MESSAGES[locale][key] or _EN[key]
    return message.format_map(_Params(params))


__all__ = [
    "DEFAULT_LOCALE",
    "MESSAGES",
    "SUPPORTED_LOCALES",
    "Locale",
    "MessageKey",
    "Messages",
    "is_locale",
    "negotiate_locale",
    "resolve_locale",
    "translate",
]
