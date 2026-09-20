"""Telling somebody an import finished.

IMPORT-US-018, and the outbox's second producer. A commit over a file at the
row ceiling is minutes of work in a worker, and the person who confirmed it has
long since closed the page — so the run finishing has to reach them rather than
waiting to be looked at.

**The kind is declared here**, beside the thing that raises it, the way the
assistant declares its own and an audit action is declared by the module that
records it. A product generated without `data_import` has neither the producer
nor the kind.

**In-app only, and said out loud rather than hidden.** The audience is two
subjects -- who started the run and who confirmed it -- and a subject carries
no address in this product's own tables. The one place addresses live is the
platform's member list, which needs a caller's token, and a worker has no
token: nobody is signed in when a background job finishes. So `html` is None
and the mail half skips, which is the same mechanism a template with no mail
form has always used. Giving the worker a token to fetch addresses is a change
to what a worker is allowed to do, and it is not worth making for a message
that already arrives in the feed and the bell.

The two subjects rather than an audience by permission on purpose. An import is
one person's piece of work; telling every administrator that somebody loaded a
file is the kind of notification people switch off, and then they miss the one
that mattered.
"""

from __future__ import annotations

from dataclasses import dataclass

from koras_email import Locale

from .dispatch import Rendered, Template
from .notifications import NotificationKind, Severity, kinds
from .recipients import Audience

#: An import run reached a terminal state.
#:
#: One kind for both outcomes rather than two. A person who imported a file
#: wants to know it finished; whether it worked is the body of the message and
#: the severity, not a different subscription. Two kinds would mean somebody
#: could switch off failures and keep successes, which is exactly backwards.
IMPORT_FINISHED = NotificationKind(
    key="imports.finished",
    summary="An import run finished, either by writing its rows or by failing.",
    # The default. A run that failed renders `error` instead -- the severity is
    # per message, and this is what a message carries when nothing says
    # otherwise.
    default_severity="info",
)
kinds.add(IMPORT_FINISHED)


@dataclass(frozen=True)
class Outcome:
    """What the commit did, in the words the notice needs and no others."""

    created: int = 0
    updated: int = 0
    skipped: int = 0
    #: The safe sentence the run recorded, when it failed. Never a stack: this
    #: goes into a message somebody reads.
    error: str | None = None

    @property
    def failed(self) -> bool:
        return self.error is not None


#: Who hears about it: the person who started the run and the person who
#: confirmed it, and nobody else. Frequently the same person, and the audience
#: de-duplicates by subject.
def audience_for(*subjects: str | None) -> Audience | None:
    """The rule, or `None` when there is nobody to tell.

    `Audience` refuses an empty rule and is right to -- a notification with no
    recipients is a call site mistake. Here the empty case is reachable, from a
    run whose actors the row somehow lacks, and it must not take a completed
    commit down with it. So it is a `None` the caller checks rather than an
    exception the caller has to remember to catch.
    """
    named = tuple(sorted({subject for subject in subjects if subject}))
    return Audience(subjects=named) if named else None


_WORDS: dict[str, dict[str, str]] = {
    "en": {
        "done": "Your import finished",
        "failed": "Your import could not be completed",
        "counts": "{created} added, {updated} updated, {skipped} skipped.",
        "nothing": "Nothing was written.",
    },
    "de": {
        "done": "Ihr Import wurde abgeschlossen",
        "failed": "Ihr Import konnte nicht abgeschlossen werden",
        "counts": "{created} hinzugefügt, {updated} aktualisiert, {skipped} übersprungen.",
        "nothing": "Es wurde nichts geschrieben.",
    },
    "es": {
        "done": "La importación ha finalizado",
        "failed": "No se ha podido completar la importación",
        "counts": "{created} añadidos, {updated} actualizados, {skipped} omitidos.",
        "nothing": "No se ha escrito nada.",
    },
}


def finished_notice(outcome: Outcome) -> Template:
    """The notice, as a template the dispatch point renders once per language.

    Written in three languages here rather than as a key the browser resolves,
    because a feed row stores the words: it is read months later, possibly by
    somebody whose language has since changed, and re-resolving it then would
    silently rewrite history. The same reason the outbox stores a rendered body
    rather than the means to rebuild one.
    """

    def render(locale: Locale) -> Rendered:
        words = _WORDS.get(locale, _WORDS["en"])
        if outcome.failed:
            title = words["failed"]
            body = outcome.error or words["nothing"]
            severity: Severity = "error"
        else:
            title = words["done"]
            body = words["counts"].format(
                created=outcome.created, updated=outcome.updated, skipped=outcome.skipped
            )
            severity = IMPORT_FINISHED.default_severity
        return Rendered(
            title=title,
            body=body,
            # The list, not a detail page: there is no detail page, and a link
            # to one would be a link to a 404. The run is at the top of the
            # list, which is the next best thing and is true today.
            url="/dashboard/imports",
            severity=severity,
            # No mail form. See the module docstring: a worker has no token, so
            # a subject has no address, and `html=None` is how a template says
            # "in-app only" without a second flag anywhere.
            html=None,
        )

    return render


__all__ = ["IMPORT_FINISHED", "Outcome", "audience_for", "finished_notice"]
