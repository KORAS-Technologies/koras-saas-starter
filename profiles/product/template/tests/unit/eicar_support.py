"""The EICAR antivirus test string, assembled at run time and never stored at rest.

EICAR is inert text, but every antivirus that reads a repository, a build context or a
developer's disk may quarantine or delete a file that contains the literal 68-byte string,
and that would break collection of the tests that need it. So no file in a generated
product carries it: it lives here base64-encoded, so this source file does not contain the
trigger string either, and `materialize()` decodes it fresh on every call. The recorded
SHA-256 lets a caller tell a corrupted constant from the real thing without printing or
logging the string.

Used by the scanner's tests as the sample a real engine must find, and by nothing in
production code.
"""

from __future__ import annotations

import base64

#: The standard 68-byte EICAR antivirus test file, base64-encoded so this
#: source file itself does not carry the literal trigger string a second time.
EICAR_BASE64 = (
    "WDVPIVAlQEFQWzRcUFpYNTQoUF4pN0NDKTd9JEVJQ0FSLVNUQU5EQVJELUFOVElWSVJVUy1URVNULUZJTEUhJEgrSCo="
)

EICAR_SHA256 = "275a021bbfb6489e54d471899f7db9d1663fc695ec2fe2a2c4538aabf651fd0f"


def materialize() -> bytes:
    """The EICAR test file's bytes, decoded fresh every call.

    Compared against `EICAR_SHA256` so a caller can tell a corrupted constant
    from the real thing without ever printing or logging the string itself.
    """
    import hashlib

    raw = base64.b64decode(EICAR_BASE64)
    digest = hashlib.sha256(raw).hexdigest()
    if digest != EICAR_SHA256:
        raise ValueError("the embedded EICAR constant does not match its recorded checksum")
    return raw
