"""How long an upload ticket can be used, and when its object may first be read.

One module because two numbers that must agree were about to live in two places
(ADR 0013, `secure_files`). The signed PUT the API hands out lives for
`UPLOAD_URL_SECONDS`; the scanner may not read the object until that has
certainly passed, because a PUT inside the window can still replace the bytes.
Both the upload route and the scanner's window gate read the constants here, so
raising the ticket's lifetime raises the gate with it and the two cannot drift.

**The 60 seconds is not slack to be tuned away.** The row is inserted, and its
`created_at` is taken, before the URL is signed, so the URL's real expiry is
`created_at` plus a request's worth of work plus `UPLOAD_URL_SECONDS`. The
margin covers that gap and ordinary clock skew between the database and a
worker. It has no setting: the canonical minimum delay is 16 minutes, and a
knob would be the way to shorten it.

**Upload finalization.** The window above only says when a ticket
stops being *accepted at the start of a request*. Measured against a real
provider store while this was proven in Docoris, a request begun inside the
window can run on for about 150 seconds after it, and can replace the object
after a scanner has read it. So a key a ticket was ever signed for is never
what is scanned or released: the ticket targets an **incoming** key, and once the window and the
measured in-flight bound have passed the worker copies the object to a **final**
key no ticket was ever signed for, switches the row to it, and scans that. The
key helpers live here because they are the same stdlib-only arrangement as the
constants, and the API (which names the incoming key) and the worker (which
names the final one and refuses to scan an incoming one) must agree on the shape.

Standard library only, so the worker image can carry this one file.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

#: Signed upload URLs live this long. Long enough for a slow connection to
#: finish a large upload, short enough that a leaked URL is worth little.
UPLOAD_URL_SECONDS = 15 * 60

#: Added to the ticket's lifetime before an object may be read for scanning.
UPLOAD_SAFETY_MARGIN_SECONDS = 60

#: The canonical minimum delay between a ticket being issued and the object
#: being read by the scanner: 16 minutes.
SCAN_READ_DELAY_SECONDS = UPLOAD_URL_SECONDS + UPLOAD_SAFETY_MARGIN_SECONDS


def earliest_scan_read(ticket_issued_at: datetime) -> datetime:
    """The first instant at which the object for this ticket may be read.

    `ticket_issued_at` is the file row's `created_at`, which is never later than
    the moment the URL was signed. It must be timezone-aware: a naive value
    would be compared against the wrong clock without any error.
    """
    if ticket_issued_at.tzinfo is None or ticket_issued_at.utcoffset() is None:
        raise ValueError("the ticket's issue time must be timezone-aware")
    return ticket_issued_at + timedelta(seconds=SCAN_READ_DELAY_SECONDS)


#: Longest a request begun inside the ticket's window was observed to stay in
#: flight afterwards: the provider cut every slow request at about 150 s
#: (measured, not documented), and this rounds that up. It is a
#: measurement of one provider's edge, **not a guarantee**, and it is not what
#: keeps the final object safe: a write that lands after finalization lands on
#: the incoming key and nothing reads that. It decides only how long the worker
#: waits before copying, so that an honest slow upload is not cut short.
IN_FLIGHT_BOUND_SECONDS = 180

#: Earliest the worker may copy an incoming object to its final key: the ticket's
#: life, the longest observed in-flight request, and the same margin as above.
FINALIZE_DELAY_SECONDS = UPLOAD_URL_SECONDS + IN_FLIGHT_BOUND_SECONDS + UPLOAD_SAFETY_MARGIN_SECONDS


def earliest_finalization(ticket_issued_at: datetime) -> datetime:
    """The first instant at which this ticket's incoming object may be finalized."""
    if ticket_issued_at.tzinfo is None or ticket_issued_at.utcoffset() is None:
        raise ValueError("the ticket's issue time must be timezone-aware")
    return ticket_issued_at + timedelta(seconds=FINALIZE_DELAY_SECONDS)


# --- the two key shapes ----------------------------------------------------------
#
#   tenants/<tenant>/<category>/<file>/incoming/<upload-id>/<name>   a ticket's target
#   tenants/<tenant>/<category>/<file>/final/<generation>/<name>     never ticketed
#
# Keys written before this change (`tenants/<tenant>/<category>/<file>/<name>`) are
# neither, and are not rewritten.

INCOMING = "incoming"
FINAL = "final"


def _name_segment(name: str) -> str:
    """A file name as one key segment, without spaces.

    Supabase's S3 gateway refuses `CopyObject` for a key containing a space (with an
    empty error code), and finalization is a copy. The person's own name is kept on
    the row and used for the download's filename; the key only has to be a key.
    """
    cleaned = name.replace(" ", "_")
    if not cleaned or "/" in cleaned or cleaned in {".", ".."}:
        raise ValueError("the name is not a key segment")
    return cleaned


def incoming_key(
    tenant_id: str, category: str, file_id: str, upload_id: str, safe_name: str
) -> str:
    """The key a ticket is signed for. `safe_name` is already `safe_filename`d."""
    for label, value in (("tenant", tenant_id), ("file", file_id), ("upload", upload_id)):
        if str(uuid.UUID(value)) != value:
            raise ValueError(f"the {label} id is not canonical")
    if "/" in category or not category:
        raise ValueError("the category is not a key segment")
    name = _name_segment(safe_name)
    return f"tenants/{tenant_id}/{category}/{file_id}/{INCOMING}/{upload_id}/{name}"


def is_incoming_key(key: str) -> bool:
    """Whether a ticket was (or could have been) signed for this key. Fails closed.

    Any `incoming` directory segment counts, not only the exact shape: a key that
    merely looks like one is refused for scanning rather than argued about. A file
    name is the last segment and cannot be a directory, and the category is a closed
    set, so nothing a person chooses can put `incoming` anywhere else.
    """
    return INCOMING in key.split("/")[2:-1]


def is_final_key(key: str) -> bool:
    """Whether this is exactly the shape `final_key_for` writes. Fails closed.

    The scanner reads and releases only a key of this shape: one a worker wrote after
    finalization, which no ticket was ever signed for. A key of any other shape -- an
    incoming one, or the pre-finalization shape -- is not scanned, whatever else is true
    of it (ADR 0013 section 6).
    """
    parts = key.split("/")
    if len(parts) != 7 or parts[0] != "tenants" or parts[4] != FINAL:
        return False
    try:
        return str(uuid.UUID(parts[5])) == parts[5] and all(parts[1:4]) and bool(parts[6])
    except ValueError:
        return False


def final_key_for(incoming: str, generation: str) -> str:
    """The key an incoming object is copied to. One per attempt; see the worker.

    `generation` is a fresh UUID for every finalization attempt, so two attempts
    can never write the same final key and the one that wins the row owns its key
    alone. Raises for anything that is not exactly an incoming key.
    """
    if str(uuid.UUID(generation)) != generation:
        raise ValueError("the generation is not canonical")
    parts = incoming.split("/")
    if len(parts) != 7 or parts[0] != "tenants" or parts[4] != INCOMING:
        raise ValueError("not an incoming key")
    return "/".join([*parts[:4], FINAL, generation, parts[6]])


def final_key(
    tenant_id: str, category: str, file_id: str, generation: str, safe_name: str
) -> str:
    """A final key a *server-side writer other than the finalizer* puts an object at.

    The finalizer reaches a final key by copying an incoming one (`final_key_for`). A restore has
    no ticket and no incoming object: it writes a new object straight to a key of exactly the same
    shape, so the one rule that says which key the scanner reads and the release primitive accepts
    (`is_final_key`) is also the shape a restore writes. `generation` is a fresh UUID per object, so
    a replacement can never be written to a key an earlier object, or a retry, already used.
    """
    for label, value in (("tenant", tenant_id), ("file", file_id), ("generation", generation)):
        if str(uuid.UUID(value)) != value:
            raise ValueError(f"the {label} id is not canonical")
    if "/" in category or not category:
        raise ValueError("the category is not a key segment")
    name = _name_segment(safe_name)
    return f"tenants/{tenant_id}/{category}/{file_id}/{FINAL}/{generation}/{name}"
