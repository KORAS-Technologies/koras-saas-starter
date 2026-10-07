"""Whether data import is switched on in this deployment -- one rule, read by both processes.

**Off unless explicitly on.** Data import writes a customer's records in bulk,
so no environment of a generated product accepts an import until somebody has
*declared* that it should (``local/config/import-activation.yaml``) and set the
setting the runtime reads. Absent, blank, misspelled, numeric, ``None``: all of
them are off. There is no path from an unparseable value to ``True``, because a
gate that fails open on a malformed value is not a gate.

The API (every import route) and the worker (every import task) each read the
setting in their own process and each applies this one function, so the two
cannot disagree about what counts as "on". ADR 0013 section 7.

This is deliberately *not* a feature-flag system. It is one deployment-wide
switch, per environment, declared in a reviewed file; nothing here is
tenant-aware and nothing here is a new kind of configuration.
"""

from __future__ import annotations

#: The setting both processes read. A name, not a secret.
IMPORTS_ENABLED_SETTING = "IMPORTS_ENABLED"

#: The only spellings that switch data import on.
ACTIVATION_ON = frozenset({"true", "1", "yes", "on"})


def parse_import_activation(value: object) -> bool:
    """``True`` only for an explicit, recognised "on"; every other input is ``False``.

    Never raises: a malformed value must not stop a service from starting, and
    it must never be read as consent.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ACTIVATION_ON
    return False
