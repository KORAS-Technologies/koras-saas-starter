"""Whether a file is the template a target gave out, and whether it still fits.

Three questions that are easy to conflate, kept apart here because ADR 0012
says they must be:

1. **Template identity** — which target, at which version, with which shape,
   this file was rendered from. Carried by an XLSX as a document property; not
   carried by a CSV at all.
2. **The product's version** — an integer the product bumps when a field's
   meaning changes. The engine cannot detect meaning, so it never bumps it.
3. **Structural compatibility** — whether the file's header can be mapped
   onto the target as declared today. Judged from the header for every
   format, by the same normalised name match the mapping suggestion uses.

A file with no identity and a compatible header is fine: that is every export
from another system. A file whose identity names an older version is told so,
and is still fine if its header fits. The verdict is information; the mapping
is the gate, and it refuses by name exactly as it did before templates existed.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass

from .mapping import suggest
from .targets import ImportTarget

#: The custom document property an XLSX template carries. Outside every cell,
#: survives a save from Excel and LibreOffice, and a customer never sees it.
PROPERTY_NAME = "koras.import.template"

#: How many hex digits of the digest a fingerprint keeps. Twelve is 48 bits:
#: enough that two shapes a product will ever declare do not collide, short
#: enough to read aloud from an Instructions sheet.
FINGERPRINT_LENGTH = 12


def fingerprint(target: ImportTarget) -> str:
    """A digest of the declared shape, in declaration order.

    Name, kind, required and options are the four things a filled-in file
    depends on. Labels, examples, help and the writer are not: changing any
    of those changes nothing about which files the target accepts.
    """
    digest = hashlib.sha256()
    for spec in target.fields:
        digest.update(spec.name.encode())
        digest.update(b"\0")
        digest.update(spec.kind.value.encode())
        digest.update(b"\0")
        digest.update(b"1" if spec.required else b"0")
        digest.update(b"\0")
        digest.update("\x1f".join(spec.options).encode())
        digest.update(b"\n")
    return digest.hexdigest()[:FINGERPRINT_LENGTH]


def identity(target: ImportTarget) -> str:
    """`key/vN/fingerprint`, the string a template carries."""
    return f"{target.key}/v{target.version}/{fingerprint(target)}"


@dataclass(frozen=True)
class Identity:
    target: str
    version: int
    fingerprint: str


def parse_identity(text: str | None) -> Identity | None:
    """The identity a file carried, or None when it carried nothing usable.

    Lenient on purpose: a property somebody edited, or one from a different
    product's template, reads as "no identity" rather than as an error. The
    header decides whether the file can be used; this only says where it
    came from.
    """
    if not text:
        return None
    parts = text.strip().split("/")
    if len(parts) != 3:
        return None
    key, version, digest = parts
    if not version.startswith("v") or not version[1:].isdigit():
        return None
    if not digest or any(char not in "0123456789abcdef" for char in digest):
        return None
    return Identity(target=key, version=int(version[1:]), fingerprint=digest)


@dataclass(frozen=True)
class Compatibility:
    """What the header says about the target, and what the identity adds."""

    #: `compatible`, `unknown_columns` or `incompatible`.
    verdict: str
    #: Required fields no column matched by name. Non-empty means incompatible.
    missing_required: tuple[str, ...]
    #: Columns that matched no field. Non-empty means unknown_columns, unless
    #: something is also missing.
    unknown_columns: tuple[str, ...]
    #: The version the file's identity named, when it named this target.
    version_found: int | None
    #: The file carried an identity for this target and it is not the current
    #: one: an older version, or a shape that changed without a bump.
    stale: bool

    @property
    def compatible(self) -> bool:
        return self.verdict != "incompatible"


def compare(
    target: ImportTarget, columns: Iterable[str], *, found: str | None = None
) -> Compatibility:
    """Judge a header against the target, and an identity against the target.

    The header match is `suggest`'s: a column matches a field when their
    names agree once punctuation, spacing and case are ignored, and a
    contested match is no match. That is the same rule the mapping page
    pre-fills with, so "compatible" here means "would be mapped without a
    hand".
    """
    available = tuple(columns)
    matched = suggest(target, available)
    matched_fields = set(matched.values())
    missing = tuple(name for name in target.required_fields if name not in matched_fields)
    unknown = tuple(name for name in available if name not in matched)

    parsed = parse_identity(found)
    version_found = parsed.version if parsed is not None and parsed.target == target.key else None
    stale = (
        parsed is not None
        and parsed.target == target.key
        and (parsed.version < target.version or parsed.fingerprint != fingerprint(target))
    )

    if missing:
        verdict = "incompatible"
    elif unknown:
        verdict = "unknown_columns"
    else:
        verdict = "compatible"
    return Compatibility(
        verdict=verdict,
        missing_required=missing,
        unknown_columns=unknown,
        version_found=version_found,
        stale=stale,
    )


__all__ = [
    "FINGERPRINT_LENGTH",
    "PROPERTY_NAME",
    "Compatibility",
    "Identity",
    "compare",
    "fingerprint",
    "identity",
    "parse_identity",
]
