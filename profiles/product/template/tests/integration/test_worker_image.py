"""The worker's image, built from the product's own Dockerfile, with nothing mounted.

IMPORT-DEF-020. Every other suite here runs where the whole source tree is on
the path. A worker does not: it runs in an image that carries the worker, the
shared packages and a handful of API files copied one line at a time. On
2026-10-02 that image was run for the first time, to measure memory, and an
import in it did this:

- the dry run's job ended in `ModuleNotFoundError` -- the audit sink calls
  `rebind_tenant` after it commits, which lived in `core/database.py`, which
  the image never carried -- so the queue recorded a failed job while the run
  it was for had been committed `validated`;
- every commit logged that it finished and could not be witnessed, after the
  row that witnessed it had been written.

The harness that measured GR-352C before it bind-mounted the tree and could
not see either.

`tests/unit/test_worker_image_contents.py` holds the Dockerfile to copying
every module the worker reaches. This is the other half: the image is built,
a worker is started from it the way it starts when deployed, and
`worker_image_probe.py` is run inside a second container of it -- fed on
standard input, so nothing of the tree is mounted -- to load every module the
worker names and to take a dry run and a commit from their first line to
their last against a real PostgreSQL.

**What it asserts is that a job and its run agree.** A job that succeeded has
a run that says so and evidence beside it; a job that failed, by returning or
by raising, has no run that says it succeeded.

Skipped without an image, a database and a queue, for the reason
`test_import_commit_rls.py` gives. `Generator Integration` builds the image,
supplies all three, names this file and fails if any test in it skipped.

    WORKER_IMAGE                the image, as `docker build` tagged it
    E2E_DATABASE_URL            the round trip's database, as this process reaches it
    WORKER_IMAGE_REDIS_URL      a Redis, as a container reaches it
    WORKER_IMAGE_DATABASE_URL   the same database as a container reaches it;
                                defaults to E2E_DATABASE_URL
    WORKER_IMAGE_NETWORK        the Docker network to run in; defaults to `host`
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

IMAGE = os.environ.get("WORKER_IMAGE", "")
DATABASE_URL = os.environ.get("E2E_DATABASE_URL", "")
REDIS_URL = os.environ.get("WORKER_IMAGE_REDIS_URL", "")
NETWORK = os.environ.get("WORKER_IMAGE_NETWORK", "host")
#: As the worker's own settings spell it: no driver in the scheme.
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

PROBE = Path(__file__).with_name("worker_image_probe.py")
ROWS = 25


def _docker(*arguments: str, stdin: str | None = None, timeout: int = 300) -> str:
    done = subprocess.run(  # noqa: S603 - the arguments are this file's own
        ["docker", *arguments],  # noqa: S607 - whichever docker the runner has
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
        check=False,
    )
    assert done.returncode == 0, f"docker {arguments[0]} failed:\n{done.stdout}\n{done.stderr}"
    return done.stdout


#: A product generated with `secure_files` (ADR 0013) carries the upload window module, and its
#: worker refuses to start without a scanner and an object store.
SECURE_FILES = (
    Path(__file__).resolve().parents[2] / "services/api/koras_api/core/upload_window.py"
).exists()

#: What that worker is given. An import reads neither the scanner nor the store -- its source is a
#: stand-in object store inside the probe -- so none of these is reached, and each is checked for
#: being *set*, which is all start-up asks.
SECURE_FILES_SETTINGS = {
    "FILE_SCAN_BACKEND": "clamd",
    "FILE_SCAN_CLAMD_HOST": "127.0.0.1",
    "STORAGE_ENDPOINT": "http://127.0.0.1:9",
    "STORAGE_BUCKET": "image-test",
    "STORAGE_ACCESS_KEY": "image-test",
    "STORAGE_SECRET_KEY": "image-test",
}


def _environment() -> list[str]:
    """What a deployed worker is given, and nothing that would stand in for a file."""
    settings = {"OTEL_SDK_DISABLED": "true", **(SECURE_FILES_SETTINGS if SECURE_FILES else {})}
    out = [
        "--network",
        NETWORK,
        "-e",
        "ENVIRONMENT=dev",
        "-e",
        f"DATABASE_URL={IN_IMAGE_DATABASE_URL}",
        "-e",
        f"REDIS_URL={REDIS_URL}",
    ]
    for name, value in settings.items():
        out += ["-e", f"{name}={value}"]
    return out


@pytest.fixture(scope="module")
def worker() -> Iterator[str]:
    """A worker started the way the image starts it: its own command, unchanged."""
    name = f"worker-image-{uuid.uuid4().hex[:8]}"
    _docker("run", "-d", "--name", name, *_environment(), IMAGE)
    try:
        yield name
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)  # noqa: S603, S607


@pytest.fixture(scope="module")
def probe(worker: str) -> dict[str, Any]:
    """`worker_image_probe.py`, run in a second container of the same image.

    On standard input. No volume, no bind mount: the only files in reach are
    the ones the image was built with.
    """
    out = _docker(
        "run",
        "--rm",
        "-i",
        *_environment(),
        "-e",
        "PROBE_QUEUE=1",
        IMAGE,
        "python",
        "-",
        stdin=PROBE.read_text(encoding="utf-8"),
        timeout=600,
    )
    report: dict[str, Any] = json.loads(out.strip().splitlines()[-1])
    return report


def test_what_ran_was_the_image_and_not_the_tree(probe: dict[str, Any]) -> None:
    """The tree has the API's entry point, its sessions and its settings. The image has none."""
    assert probe["image"] == {"api_main": False, "api_database": False, "api_settings": False}


def test_every_module_the_worker_names_loads_in_the_image(probe: dict[str, Any]) -> None:
    assert probe["loads"], "the worker names no module of the API, which is not this product"
    broken = {module: why for module, why in probe["loads"].items() if why != "ok"}

    assert not broken, f"the worker reaches these by name and the image cannot load them: {broken}"


def test_the_worker_starts_and_runs_a_job(worker: str, probe: dict[str, Any]) -> None:
    """Its own command, its isolation check against the database, and a job off the queue."""
    assert probe["through_the_worker"]["example_task"] == {"status": "ok", "payload": {"n": 1}}

    state = json.loads(_docker("inspect", "--format", "{{json .State}}", worker))
    assert state["Running"] is True and state["OOMKilled"] is False, state


def test_a_dry_run_completes_and_its_job_and_its_run_agree(probe: dict[str, Any]) -> None:
    dry_run = probe["dry_run"]

    assert dry_run["raised"] is None, dry_run["raised"]
    assert dry_run["answer"]["status"] == "ok" and dry_run["answer"]["state"] == "validated"
    assert dry_run["run"]["status"] == "validated"
    assert dry_run["run"]["rows_total"] == ROWS
    # The verdict has its evidence, written through the API's own sink.
    assert dry_run["run"]["audit"] == [["import.run.validated", "ok"]]
    assert dry_run["complaints"] == []


def test_a_commit_completes_is_witnessed_and_is_announced(probe: dict[str, Any]) -> None:
    commit = probe["commit"]

    assert commit["raised"] is None, commit["raised"]
    assert commit["answer"]["status"] == "ok" and commit["answer"]["created"] == ROWS
    assert commit["run"]["status"] == "committed"
    assert commit["run"]["written"] == ROWS and commit["run"]["rows_created"] == ROWS
    assert commit["run"]["audit"] == [["import.run.finished", "ok"]]
    # Neither "could not be witnessed" nor "could not be announced": the audit
    # sink, the notice and the dispatch point all loaded and all ran.
    assert commit["complaints"] == []


def test_a_dry_run_that_fails_says_so_on_its_run(probe: dict[str, Any]) -> None:
    refused = probe["dry_run_refused"]

    assert refused["raised"] is None
    assert refused["answer"]["status"] == "failed"
    assert refused["run"]["status"] == "failed" and refused["run"]["error"]
    assert refused["run"]["audit"] == []


def test_a_dry_run_that_raises_leaves_no_run_that_says_it_succeeded(
    probe: dict[str, Any],
) -> None:
    """The job is one the queue records as failed. Its run must not say otherwise."""
    raised = probe["dry_run_raised"]

    assert raised["raised"] and "RuntimeError" in raised["raised"]
    assert raised["run"]["status"] == "failed", (
        f"a job that raised left its run {raised['run']['status']!r}"
    )
    assert raised["run"]["audit"] == []


def test_a_job_the_worker_itself_ran_and_refused_agrees_with_its_run(
    probe: dict[str, Any],
) -> None:
    """Enqueued, picked up by the worker the image started, and refused by it.

    The worker's own registry, its own run store and its own session: nothing
    here was replaced. A module missing from the image would answer `skipped`
    and leave the run where it was.
    """
    through = probe["through_the_worker"]["imports.validate"]

    assert through["raised"] is None, through["raised"]
    assert through["answer"] == {"status": "failed", "reason": "unknown target"}
    assert through["run"]["status"] == "failed"
    assert through["run"]["error"] == "this product no longer accepts that import"


def test_the_worker_is_still_up_after_all_of_it(worker: str, probe: dict[str, Any]) -> None:
    del probe
    time.sleep(1)
    state = json.loads(_docker("inspect", "--format", "{{json .State}}", worker))

    assert state["Running"] is True and state["ExitCode"] == 0, state
    logs = subprocess.run(  # noqa: S603
        ["docker", "logs", worker],  # noqa: S607
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert "Traceback" not in logs.stdout + logs.stderr, logs.stdout + logs.stderr
