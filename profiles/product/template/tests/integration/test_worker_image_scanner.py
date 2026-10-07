# ruff: noqa: E501, S101, S603, S607
"""The worker's image, built from the product's own Dockerfile, as a scanner host (ADR 0013).

Every other suite runs where the whole source tree is on the path. A deployed worker runs in an
image that carries the worker, the shared packages and a handful of API files copied one line at a
time (`tests/unit/test_worker_image_contents.py` holds the Dockerfile to copying every module the
worker reaches; this is the other half, as `test_worker_image.py` is for the import). Here the image
is run with nothing mounted and the things only an image can show are asserted:

* every scanner module, and the three API files it reaches by name, import in it, and the audit
  actions the scanner records register;
* `file.scan` is bound and the sweep is scheduled in the worker the image starts;
* a worker started from it with `FILE_SCAN_BACKEND=none`, no scanner host, or a limit outside its
  range **exits non-zero naming the setting and never serves**, and with a valid configuration it
  starts and stays up.

Skipped without an image, a database and a queue. `Generator Integration` builds the image,
supplies all three and fails if any test in it skipped.

    WORKER_IMAGE                    the image, as `docker build` tagged it
    E2E_DATABASE_URL                the round trip's database, as this process reaches it
    WORKER_IMAGE_REDIS_URL          a Redis, as a container reaches it
    WORKER_IMAGE_DATABASE_URL       the same database as a container reaches it
    WORKER_IMAGE_SERVICES_HOST      where a container reaches the scanner and the store (default 127.0.0.1)
    WORKER_IMAGE_NETWORK            the Docker network to run in; defaults to `host`
"""

from __future__ import annotations

import os
import subprocess
import time
import uuid
from collections.abc import Iterator

import pytest

IMAGE = os.environ.get("WORKER_IMAGE", "")
DATABASE_URL = os.environ.get("E2E_DATABASE_URL", "")
REDIS_URL = os.environ.get("WORKER_IMAGE_REDIS_URL", "")
NETWORK = os.environ.get("WORKER_IMAGE_NETWORK", "host")
SERVICES = os.environ.get("WORKER_IMAGE_SERVICES_HOST", "127.0.0.1")
IN_IMAGE_DATABASE_URL = (os.environ.get("WORKER_IMAGE_DATABASE_URL") or DATABASE_URL).replace(
    "postgresql+asyncpg://", "postgresql://", 1
)

pytestmark = pytest.mark.skipif(
    not (IMAGE and DATABASE_URL and REDIS_URL),
    reason=(
        "needs the worker image, a real PostgreSQL and a Redis; set WORKER_IMAGE, "
        "E2E_DATABASE_URL and WORKER_IMAGE_REDIS_URL"
    ),
)

#: Run inside the image, on standard input, so nothing of the source tree is in reach.
PROBE = '''
import importlib, json
names = [
    "koras_worker.worker", "koras_worker.secure_files", "koras_worker.scanning",
    "koras_worker.scanning.clamd", "koras_worker.scanning.config", "koras_worker.scanning.objects",
    "koras_worker.scanning.release", "koras_worker.scanning.runtime", "koras_worker.scanning.s3",
    "koras_worker.scanning.structure", "koras_worker.scanning.transition",
    "koras_worker.tasks.scan", "koras_worker.tasks.scan_sweep", "koras_worker.tasks.finalize",
    "koras_api.core.scan_jobs", "koras_api.core.scan_enqueue", "koras_api.core.scan_audit",
    "koras_api.core.upload_window",
]
for name in names:
    importlib.import_module(name)
from koras_audit import actions
from koras_worker import worker
from koras_worker.tasks import scan
(bound,) = scan.bound()
functions = [getattr(f, "name", getattr(f, "__name__", "")) for f in worker.WorkerSettings.functions]
print(json.dumps({
    "imported": len(names),
    "bound": bound.definition.name,
    "functions": functions,
    "cron": [j.name for j in worker.WorkerSettings.cron_jobs],
    "actions": sorted(a.key for a in actions if a.key.startswith("storage.object.scan")),
    "enqueue": callable(scan._enqueue_module().enqueue_scan),
}))
'''


def _environment(**overrides: str) -> list[str]:
    values = {
        "ENVIRONMENT": "dev",
        "OTEL_SDK_DISABLED": "true",
        "DATABASE_URL": IN_IMAGE_DATABASE_URL,
        "REDIS_URL": REDIS_URL,
        "FILE_SCAN_BACKEND": "clamd",
        "FILE_SCAN_CLAMD_HOST": SERVICES,
        "FILE_SCAN_CLAMD_PORT": os.environ.get("E2E_CLAMD_PORT", "3310"),
        "STORAGE_ENDPOINT": os.environ.get("STORAGE_ENDPOINT", f"http://{SERVICES}:9000"),
        "STORAGE_BUCKET": os.environ.get("STORAGE_BUCKET", "koras-files"),
        "STORAGE_ACCESS_KEY": os.environ.get("STORAGE_ACCESS_KEY", "minioadmin"),
        "STORAGE_SECRET_KEY": os.environ.get("STORAGE_SECRET_KEY", "minioadmin123"),
    }
    values.update(overrides)
    out = ["--network", NETWORK]
    for name, value in values.items():
        if value != "":
            out += ["-e", f"{name}={value}"]
    return out


def _run(*arguments: str, stdin: str | None = None, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *arguments],
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
        check=False,
    )


def test_every_scanner_module_loads_in_the_image_and_the_task_is_bound() -> None:
    import json

    done = _run("run", "--rm", "-i", *_environment(), IMAGE, "python", "-", stdin=PROBE)
    assert done.returncode == 0, done.stdout + done.stderr
    report = json.loads(done.stdout.strip().splitlines()[-1])
    assert report["imported"] == 18 and report["bound"] == "file.scan" and report["enqueue"] is True
    assert "file.scan" in report["functions"] and "file.finalize" in report["functions"]
    assert "cron:sweep_pending_scans" in report["cron"] and "cron:sweep_finalize" in report["cron"]
    assert report["actions"] == [
        "storage.object.scan_exhausted",
        "storage.object.scan_failed",
        "storage.object.scanned",
    ]


#: The release rule in the image (layer 4): importable beside `secure_files.py` alone, answering as
#: the capability says, and without the API-only gate, which the image must never carry.
RELEASE_PROBE = '''
import importlib, importlib.util, json
present = importlib.util.find_spec("koras_api.core.file_release") is not None
if not present:
    print(json.dumps({"present": False, "gate_in_image": importlib.util.find_spec("koras_api.core.file_release_gate") is not None}))
    raise SystemExit(0)
rule = importlib.import_module("koras_api.core.file_release")
constants = importlib.import_module("koras_api.core.secure_files")
tenant = "00000000-0000-0000-0000-00000000000a"
key = f"tenants/{tenant}/documents/11111111-1111-1111-1111-111111111111/final/22222222-2222-4222-8222-222222222222/a.pdf"

def ask(scan, **changes):
    arguments = dict(tenant_id=tenant, row_tenant_id=tenant, storage_key=key, scan_object_etag="etag-1")
    arguments.update(changes)
    return rule.releasable(status="ready", scan_status=scan, **arguments)

print(json.dumps({
    "present": True,
    "secure": constants.SECURE_FILES,
    "clean": ask("clean"),
    "pending": ask("pending"),
    "skipped": ask("skipped"),
    "infected": ask("infected"),
    "unstamped": ask("clean", scan_object_etag=None),
    "another_tenants_row": ask("clean", row_tenant_id="00000000-0000-0000-0000-00000000000b"),
    "incoming_key": ask("clean", storage_key=key.replace("/final/", "/incoming/")),
    "gate_in_image": importlib.util.find_spec("koras_api.core.file_release_gate") is not None,
}))
'''


def test_the_release_rule_loads_in_the_image_and_is_strict_without_the_api_only_gate() -> None:
    """The image carries the rule where something in it asks (the import source) and never the gate."""
    import json
    from pathlib import Path

    has_imports = (
        Path(__file__).resolve().parents[2] / "services/api/koras_api/core/imports.py"
    ).exists()
    done = _run("run", "--rm", "-i", *_environment(), IMAGE, "python", "-", stdin=RELEASE_PROBE)
    assert done.returncode == 0, done.stdout + done.stderr
    report = json.loads(done.stdout.strip().splitlines()[-1])
    assert report["gate_in_image"] is False
    assert report["present"] is has_imports
    if has_imports:
        assert report == {
            "present": True,
            "secure": True,
            "clean": True,
            "pending": False,
            "skipped": False,
            "infected": False,
            "unstamped": False,
            "another_tenants_row": False,
            "incoming_key": False,
            "gate_in_image": False,
        }


@pytest.mark.parametrize(
    ("overrides", "named"),
    [
        ({"FILE_SCAN_BACKEND": "none"}, "FILE_SCAN_BACKEND"),
        ({"FILE_SCAN_BACKEND": ""}, "FILE_SCAN_BACKEND"),
        ({"FILE_SCAN_BACKEND": "clamav"}, "FILE_SCAN_BACKEND"),
        ({"FILE_SCAN_CLAMD_HOST": ""}, "FILE_SCAN_CLAMD_HOST"),
        ({"FILE_SCAN_MAX_BYTES": "104857601"}, "FILE_SCAN_MAX_BYTES"),
        ({"FILE_SCAN_TIMEOUT_SECONDS": "601"}, "FILE_SCAN_TIMEOUT_SECONDS"),
        ({"FILE_SCAN_TIMEOUT_SECONDS": "5", "FILE_SCAN_CONNECT_TIMEOUT_SECONDS": "6"}, "FILE_SCAN_CONNECT_TIMEOUT_SECONDS"),
        ({"FILE_SCAN_MAX_ATTEMPTS": "0"}, "FILE_SCAN_MAX_ATTEMPTS"),
        ({"FILE_SCAN_MAX_ATTEMPTS": "twelve"}, "FILE_SCAN_MAX_ATTEMPTS"),
    ],
)
def test_a_worker_with_no_valid_scanner_configuration_refuses_to_start(
    overrides: dict[str, str], named: str
) -> None:
    done = _run("run", "--rm", *_environment(**overrides), IMAGE, timeout=120)
    output = done.stdout + done.stderr
    assert done.returncode != 0, "the worker started without a valid scanner configuration"
    assert "secure_files is enabled and the product refuses to start" in output, output[-2000:]
    assert named in output
    assert "twelve" not in output, "a value is never in the refusal"


@pytest.fixture
def worker() -> Iterator[str]:
    name = f"scanner-worker-{uuid.uuid4().hex[:8]}"
    done = _run("run", "-d", "--name", name, *_environment(), IMAGE)
    assert done.returncode == 0, done.stderr
    try:
        yield name
    finally:
        _run("rm", "-f", name)


def test_a_worker_with_a_valid_scanner_configuration_starts_and_stays_up(worker: str) -> None:
    time.sleep(10)
    status = _run("inspect", worker, "--format", "{{.State.Status}}").stdout.strip()
    logs = _run("logs", worker)
    output = logs.stdout + logs.stderr
    assert status == "running", output[-2000:]
    assert "Traceback" not in output and "refuses to start" not in output
