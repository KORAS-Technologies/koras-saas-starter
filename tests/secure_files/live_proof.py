"""The live API proof for `secure_files` (ADR 0013): real HTTP, real stores, real worker.

Run inside a generated product's environment (`uv run python live_proof.py ...` from the
product root), against a stack the workflow started: the product's own API under uvicorn, the
local identity provider the browser suite uses, PostgreSQL as the restricted application role,
MinIO, Redis, and -- in `secure` mode -- the product's worker and a real clamd.

    --mode secure   a product generated with `--with secure_files,clamd,worker,data_import`
    --mode compat   a default product: the contract it had before the capability existed

What is faked: nothing in the product. Two things are *operated*, and said so where they
happen: the clock (an upload is finalized only after a 16 minute window, so the row's
`created_at` is moved back by an administrator and the deferred job is replaced by the same
function the API calls), and a store that accepts bytes the claim does not describe (a
provider that does not enforce the signed digest is written to directly, with the store's
own credentials, because the attack is on the finalizer's check and not on the store).

Exit status is non-zero when any check fails. A check that cannot run fails; none is skipped.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from jose import jwt

EICAR_BASE64 = (
    "WDVPIVAlQEFQWzRcUFpYNTQoUF4pN0NDKTd9JEVJQ0FSLVNUQU5EQVJELUFOVElWSVJVUy1URVNULUZJTEUhJEgrSCo="
)
OWN_ORG, OTHER_ORG = "e2e-organization", "e2e-other-organization"
FAILURES: list[str] = []


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def check(description: str, condition: bool, detail: object = "") -> bool:
    if condition:
        print(f"  ok    {description}")
    else:
        print(f"::error::FAILED: {description} {detail}")
        FAILURES.append(description)
    return condition


def admin(statement: str) -> str:
    """One statement as the migration superuser (libpq reads the connection from PG*)."""
    return subprocess.run(  # noqa: S603
        ["psql", "-X", "-v", "ON_ERROR_STOP=1", "-q", "-tA", "-c", statement],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


class Api:
    def __init__(self, base: str, identity_file: Path, project_id: str) -> None:
        self.base = base.rstrip("/")
        identity = json.loads(identity_file.read_text())
        self.issuer: str = identity["issuer"]
        self.key_id: str = identity["keyId"]
        self.private_jwk: dict[str, Any] = identity["privateJwk"]
        self.project_id = project_id
        self.http = httpx.Client(timeout=60.0)

    def token(self, org: str, subject: str) -> str:
        now = int(time.time())
        claims = {
            "iss": self.issuer,
            "sub": subject,
            "aud": [self.project_id],
            "iat": now,
            "exp": now + 3600,
            "email": f"{subject}@example.com",
            "urn:zitadel:iam:org:id": org,
            "urn:zitadel:iam:org:project:roles": {
                "organization_admin": {org: "e2e.localhost"},
            },
            "amr": ["pwd", "mfa"],
        }
        return str(jwt.encode(claims, self.private_jwk, algorithm="RS256", headers={"kid": self.key_id}))

    def call(
        self, method: str, path: str, token: str, body: dict[str, Any] | None = None
    ) -> httpx.Response:
        return self.http.request(
            method,
            f"{self.base}/api/v1{path}",
            headers={"Authorization": f"Bearer {token}"},
            json=body,
        )


def code_of(response: httpx.Response) -> str:
    try:
        detail = response.json().get("detail")
    except ValueError:
        return ""
    return str(detail.get("code", "")) if isinstance(detail, dict) else ""


def row_of(file_id: str) -> dict[str, str]:
    names = ("status", "scan_status", "scan_failure", "storage_key", "scan_object_etag")
    out = admin(
        "select status, scan_status, coalesce(scan_failure,''), storage_key, "
        f"coalesce(scan_object_etag,'') from public.files where id = '{file_id}'"
    )
    return dict(zip(names, out.split("|"), strict=True))


def s3_client() -> Any:
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=os.environ["STORAGE_ENDPOINT"],
        aws_access_key_id=os.environ["STORAGE_ACCESS_KEY"],
        aws_secret_access_key=os.environ["STORAGE_SECRET_KEY"],
        region_name="us-east-1",
    )


def put(ticket: dict[str, Any], body: bytes, *, headers: dict[str, str] | None = None) -> httpx.Response:
    """The browser's PUT: the signed URL and exactly the headers the ticket names."""
    sent = ticket["headers"] if headers is None else headers
    return httpx.put(ticket["upload_url"], content=body, headers=sent, timeout=60.0)


def upload_request(name: str, body: bytes, *, claim: str | None | bool = True) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": name,
        "size_bytes": len(body),
        "content_type": "text/plain",
    }
    if claim is True:
        payload["checksum_sha256"] = sha256(body)
    elif isinstance(claim, str):
        payload["checksum_sha256"] = claim
    return payload


# ------------------------------------------------------------------------------------
# secure mode
# ------------------------------------------------------------------------------------


def secure(api: Api) -> None:
    own = api.token(OWN_ORG, "e2e-subject")
    other = api.token(OTHER_ORG, "e2e-other-subject")

    print("-- the ticket needs a well-formed claim")
    body = b"secure live proof, the honest file\n"
    refused = api.call("POST", "/files/uploads", own, upload_request("a.txt", body, claim=None))
    check("a ticket without checksum_sha256 is refused (422)", refused.status_code == 422, refused.text)
    for label, bad in (
        ("uppercase", sha256(body).upper()),
        ("short", sha256(body)[:63]),
        ("long", sha256(body) + "0"),
        ("non-hex", "z" * 64),
    ):
        got = api.call("POST", "/files/uploads", own, upload_request("a.txt", body, claim=bad))
        check(f"a {label} checksum is refused (422)", got.status_code == 422, got.text)

    print("-- the signed PUT goes to an incoming key and only the signed request is accepted")
    issued = api.call("POST", "/files/uploads", own, upload_request("a.txt", body))
    check("a valid ticket is issued (201)", issued.status_code == 201, issued.text)
    ticket = issued.json()
    clean_id = str(ticket["file_id"])
    check("the ticket's key is an incoming key", "/incoming/" in ticket["upload_url"].split("?")[0])
    check(
        "the ticket signs the digest header",
        ticket["headers"].get("x-amz-checksum-sha256")
        == base64.b64encode(bytes.fromhex(sha256(body))).decode(),
    )
    unsigned = put(ticket, body, headers={"Content-Type": ticket["headers"]["Content-Type"]})
    check("a PUT without the signed headers is refused by the store", unsigned.status_code >= 400, unsigned.status_code)
    other_bytes = b"not the bytes the claim describes\n"
    tampered = put(ticket, other_bytes)
    check("bytes that do not hash to the signed digest are refused by the store", tampered.status_code >= 400, tampered.status_code)
    sent = put(ticket, body)
    check("the PUT with the signed headers is accepted", sent.status_code in (200, 204), sent.status_code)

    forged = ticket["upload_url"].replace("/incoming/", "/final/", 1)
    forged_put = httpx.put(forged, content=body, headers=ticket["headers"], timeout=60.0)
    check("a client cannot write a final key with a ticket's signature", forged_put.status_code >= 400, forged_put.status_code)

    print("-- completion records nothing the client says and releases nothing")
    wrong = api.call("POST", f"/files/{clean_id}/complete", own, {"checksum_sha256": sha256(b"other")})
    check(
        "completion with a different digest is refused (422 upload_checksum_claim_invalid)",
        wrong.status_code == 422 and code_of(wrong) == "upload_checksum_claim_invalid",
        wrong.text,
    )
    done = api.call("POST", f"/files/{clean_id}/complete", own, {})
    check("completion succeeds (200)", done.status_code == 200, done.text)
    if done.status_code == 200:
        check("the completed row is not available", done.json().get("content_available") is False)
    early = api.call("GET", f"/files/{clean_id}/download", own)
    check(
        "download before finalization is refused and signs nothing",
        early.status_code in (403, 409) and "url" not in early.text and code_of(early) in ("file_quarantined", "file_scan_pending"),
        f"{early.status_code} {early.text}",
    )
    print(f"        (refusal: {early.status_code} {code_of(early)})")

    print("-- EICAR, and bytes that are not the claim")
    eicar = base64.b64decode(EICAR_BASE64)
    infected = api.call("POST", "/files/uploads", own, upload_request("eicar.txt", eicar))
    infected_id = str(infected.json()["file_id"])
    check("EICAR upload accepted by the store (it is only a signed PUT)", put(infected.json(), eicar).status_code in (200, 204))
    check("EICAR completion (200)", api.call("POST", f"/files/{infected_id}/complete", own, {}).status_code == 200)

    claimed = b"the bytes the ticket was authorized for!"
    swapped = bytes(reversed(claimed))
    check("claim and swapped bytes differ and have equal length", swapped != claimed and len(claimed) == len(swapped))
    mismatch = api.call("POST", "/files/uploads", own, upload_request("m.txt", claimed))
    mismatch_ticket = mismatch.json()
    mismatch_id = str(mismatch_ticket["file_id"])
    key = mismatch_ticket["upload_url"].split("?")[0].split(f"/{os.environ['STORAGE_BUCKET']}/", 1)[1]
    # A provider that does not enforce the signed digest: written with the store's own credentials,
    # carrying the provenance the ticket's own PUT would have (so the only thing wrong with the
    # object is that its bytes are not the claim).
    from koras_storage import UPLOAD_PROVENANCE_META

    upload_id = key.split("/")[5]
    s3_client().put_object(
        Bucket=os.environ["STORAGE_BUCKET"],
        Key=key,
        Body=swapped,
        Metadata={UPLOAD_PROVENANCE_META: upload_id},
    )
    check("completion of the swapped upload (size matches, 200)", api.call("POST", f"/files/{mismatch_id}/complete", own, {}).status_code == 200)

    print("-- the real finalizer, the real scanner (clock operated, nothing else)")
    ids = (clean_id, infected_id, mismatch_id)
    in_list = ",".join(f"'{i}'" for i in ids)
    admin(f"update public.files set created_at = now() - interval '2 hours' where id in ({in_list})")
    asyncio.run(requeue(own_org=OWN_ORG, file_ids=ids))
    deadline = time.time() + 240
    while time.time() < deadline:
        rows = {i: row_of(i) for i in ids}
        settled = (
            rows[clean_id]["scan_status"] == "clean"
            and rows[infected_id]["scan_status"] == "infected"
            and rows[mismatch_id]["scan_failure"] == "integrity_mismatch"
        )
        if settled:
            break
        time.sleep(3)
    rows = {i: row_of(i) for i in ids}
    check("the clean file is clean on a final key, stamped by the scanner", rows[clean_id]["scan_status"] == "clean" and "/final/" in rows[clean_id]["storage_key"] and bool(rows[clean_id]["scan_object_etag"]), rows[clean_id])
    check("EICAR is infected and quarantined", rows[infected_id]["scan_status"] == "infected" and rows[infected_id]["status"] == "quarantined", rows[infected_id])
    check("swapped bytes are held integrity_mismatch, still pending", rows[mismatch_id]["scan_status"] == "pending" and rows[mismatch_id]["scan_failure"] == "integrity_mismatch", rows[mismatch_id])

    print("-- download follows the verdict")
    served = api.call("GET", f"/files/{clean_id}/download", own)
    check("the clean file is served (200)", served.status_code == 200, served.text)
    if served.status_code == 200:
        fetched = httpx.get(served.json()["url"], timeout=60.0)
        check("the served bytes are the uploaded bytes", fetched.status_code == 200 and sha256(fetched.content) == sha256(body))
    quarantined = api.call("GET", f"/files/{infected_id}/download", own)
    check("EICAR is refused (403 file_quarantined)", quarantined.status_code == 403 and code_of(quarantined) == "file_quarantined", quarantined.text)
    held = api.call("GET", f"/files/{mismatch_id}/download", own)
    check("swapped bytes are refused and sign nothing", held.status_code in (403, 409) and "url" not in held.text, f"{held.status_code} {held.text}")
    never = admin(f"select count(*) from public.files f where f.id = '{mismatch_id}' and {releasable_sql()}")
    check("swapped bytes are not releasable under RELEASABLE_SQL", never == "0", never)
    theirs = api.call("GET", f"/files/{clean_id}/download", other)
    check("another tenant cannot download it (404 file_not_found)", theirs.status_code == 404 and code_of(theirs) == "file_not_found", theirs.text)
    listing = api.call("GET", "/files", own)
    if listing.status_code == 200:
        by_id = {f["id"]: f for f in listing.json()["files"]}
        check("the listing says content_available only for the clean file", by_id.get(clean_id, {}).get("content_available") is True and by_id.get(mismatch_id, {}).get("content_available") is not True, by_id)
    else:
        check("the listing answers (200)", False, listing.text)

    print("-- import activation is off unless explicitly on")
    targets = api.call("GET", "/imports/targets", own)
    check("imports are refused by default (403 import_not_enabled)", targets.status_code == 403 and code_of(targets) == "import_not_enabled", f"{targets.status_code} {targets.text}")
    started = api.call("POST", "/imports", own, {"file_id": clean_id, "target": "x", "operation": "create"})
    check("starting an import is refused the same way", started.status_code == 403 and code_of(started) == "import_not_enabled", f"{started.status_code} {started.text}")


def releasable_sql() -> str:
    from koras_api.core.file_release import RELEASABLE_SQL

    return str(RELEASABLE_SQL)


async def requeue(*, own_org: str, file_ids: tuple[str, ...]) -> None:
    """Replace each file's deferred finalize job with one that is due now.

    The API enqueued `file.finalize` for the end of the upload window. The window is not a
    setting and is not shortened here: the row's issue time is moved back (above) and the job
    is put back by the same function the API calls, under the same identity, so the worker's
    own finalizer decides whether the window has passed.
    """
    import redis
    from koras_api.core.finalize_enqueue import enqueue_finalize
    from koras_api.core.finalize_jobs import FILE_FINALIZE, finalize_idempotency_key
    from koras_queue import job_id_for, queue_for

    url = os.environ["REDIS_URL"]
    client = redis.Redis.from_url(url)
    tenant = admin("select id from public.tenants where zitadel_org_id = '" + own_org + "'")
    queue = queue_for(url)
    for file_id in file_ids:
        job_id = job_id_for(FILE_FINALIZE, tenant, finalize_idempotency_key(file_id))
        client.zrem("arq:queue", job_id)
        client.delete(f"arq:job:{job_id}")
        enqueued = await enqueue_finalize(
            queue,
            tenant_id=tenant,
            file_id=file_id,
            created_at=datetime.now(UTC) - timedelta(hours=2),
            now=datetime.now(UTC),
            actor_id="live-proof",
        )
        check(f"file.finalize re-enqueued for {file_id[:8]}", enqueued is not None and not enqueued.simulated)
    await queue.aclose()


# ------------------------------------------------------------------------------------
# compat mode
# ------------------------------------------------------------------------------------


def compat(api: Api, schema: str) -> None:
    own = api.token(OWN_ORG, "e2e-subject")
    other = api.token(OTHER_ORG, "e2e-other-subject")

    print("-- no secure module, migration or constant is present")
    import importlib.util

    from koras_api.core import secure_files

    check("SECURE_FILES is False", secure_files.SECURE_FILES is False)
    check("the upload window module is absent", importlib.util.find_spec("koras_api.core.upload_window") is None)
    check("the finalize job module is absent", importlib.util.find_spec("koras_api.core.finalize_jobs") is None)
    scan_columns = admin(
        "select count(*) from information_schema.columns where table_schema = 'public' "
        "and table_name = 'files' and column_name in ('scan_attempts','scan_failure','scan_object_etag')"
    )
    expected = "3" if schema == "upgraded" else "0"
    check(f"the database has {'the upgraded' if schema == 'upgraded' else 'no'} scan columns ({schema} schema)", scan_columns == expected, scan_columns)

    print("-- the legacy contract: a ticket needs no checksum")
    body = b"compat live proof\n"
    legacy = api.call("POST", "/files/uploads", own, upload_request("legacy.txt", body, claim=None))
    check("a ticket without checksum_sha256 is issued (201)", legacy.status_code == 201, legacy.text)
    ticket = legacy.json()
    file_id = str(ticket["file_id"])
    path = ticket["upload_url"].split("?")[0]
    check("the key is the legacy shape (no incoming segment)", "/incoming/" not in path)
    check("the ticket signs Content-Type only", set(ticket["headers"]) == {"Content-Type"}, ticket["headers"])
    check("the PUT works", put(ticket, body).status_code in (200, 204))
    done = api.call("POST", f"/files/{file_id}/complete", own, {})
    check("completion succeeds (200)", done.status_code == 200, done.text)
    check("completion does not queue a finalizer or sign a URL", "content_available" not in done.text)

    print("-- an optional checksum is a claim and never a trust anchor")
    claimed_for = b"the bytes the client says it sent\n"
    stored = bytes(reversed(claimed_for))
    lying = api.call("POST", "/files/uploads", own, upload_request("lying.txt", claimed_for))
    check("a ticket with a (well-formed) checksum is issued (201)", lying.status_code == 201, lying.text)
    lying_ticket = lying.json()
    lying_id = str(lying_ticket["file_id"])
    key = lying_ticket["upload_url"].split("?")[0].split(f"/{os.environ['STORAGE_BUCKET']}/", 1)[1]
    s3_client().put_object(Bucket=os.environ["STORAGE_BUCKET"], Key=key, Body=stored)
    lying_done = api.call("POST", f"/files/{lying_id}/complete", own, {"checksum_sha256": sha256(claimed_for)})
    check("completion with an unverifiable claim succeeds (200)", lying_done.status_code == 200, lying_done.text)
    if lying_done.status_code == 200:
        check("the claim is recorded and marked unverified", lying_done.json().get("checksum_sha256") == sha256(claimed_for) and lying_done.json().get("checksum_verified") is False, lying_done.text)
        served = api.call("GET", f"/files/{lying_id}/download", own)
        check("and does not gate the download (200)", served.status_code == 200, served.text)

    print("-- legacy download semantics are unchanged")
    for scan, expect, label in (
        ("pending", 200, "pending is served (no scanner is installed)"),
        ("skipped", 200, "skipped is served"),
        ("clean", 200, "clean is served"),
        ("infected", 403, "infected is refused"),
    ):
        admin(f"update public.files set scan_status = '{scan}' where id = '{file_id}'")
        got = api.call("GET", f"/files/{file_id}/download", own)
        ok = got.status_code == expect and (expect == 200 or code_of(got) == "file_quarantined")
        check(f"{label} ({expect})", ok, f"{got.status_code} {got.text}")
        if expect == 200 and got.status_code == 200:
            fetched = httpx.get(got.json()["url"], timeout=60.0)
            check("  and the bytes come back", fetched.status_code == 200 and sha256(fetched.content) == sha256(body))
    admin(f"update public.files set scan_status = 'clean' where id = '{file_id}'")
    theirs = api.call("GET", f"/files/{file_id}/download", other)
    check("another tenant cannot download it (404)", theirs.status_code == 404, theirs.text)
    listing = api.call("GET", "/files", own)
    check("the listing answers (200)", listing.status_code == 200, listing.text)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("secure", "compat"), required=True)
    parser.add_argument("--api", default="http://127.0.0.1:3213")
    parser.add_argument("--identity", default=".e2e/identity.json")
    parser.add_argument("--project-id", default=os.environ.get("E2E_PROJECT_ID", "e2e-project"))
    parser.add_argument("--schema", choices=("fresh", "upgraded"), default="fresh")
    args = parser.parse_args()
    api = Api(args.api, Path(args.identity), args.project_id)
    health = api.http.get(f"{api.base}/api/v1/health")
    if not check("the API answers its health route", health.status_code == 200, health.text):
        return 1
    started = uuid.uuid4()
    print(f"live proof {started} mode={args.mode}")
    if args.mode == "secure":
        secure(api)
    else:
        compat(api, args.schema)
    if FAILURES:
        print(f"::error::{len(FAILURES)} live-proof checks failed: {FAILURES}")
        return 1
    print(f"live proof passed ({args.mode})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
