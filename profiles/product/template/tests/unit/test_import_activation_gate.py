"""The import activation gate (ADR 0013 section 7): off by default, enforced server-side.

Proven in Docoris. A generated product that has `data_import` starts with imports
OFF in every environment until a deployment declares and sets the switch. Here:

* **The switch.** `IMPORTS_ENABLED`, on the API and on the worker, each its own process.
  Off when absent, blank, malformed or anything but an explicit "true"/"1"/"yes"/"on".
* **Every API route.** The gate is a router-level dependency, so a route cannot be added
  without it. The parametrised test below drives every route the router mounts, with a
  body that would be a 422 if the gate ever ran after validation, and expects the same 403.
* **Both worker tasks.** A job enqueued before the switch went off refuses without touching
  the engine, the registry, the object store or the heavy gate.
* **A guard** fails if a route is mounted outside the gate, if a task is bound that does not
  start with the gate, or if another module starts to enqueue or consume the import jobs.

Over scripted sessions: nothing here reads a database. Real-PG tests are not needed, no SQL
changed.
"""

from __future__ import annotations

import ast
import asyncio
import os
import re
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("ZITADEL_DOMAIN", "https://example.invalid")
os.environ.setdefault("ZITADEL_PROJECT_ID", "0")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

import koras_worker.tasks.imports as task  # noqa: E402
from fastapi.routing import APIRoute  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from koras_api.core.auth import require_auth  # noqa: E402
from koras_api.core.database import get_db  # noqa: E402
from koras_api.core.errors import ApiErrorCode  # noqa: E402
from koras_api.core.settings import Settings  # noqa: E402
from koras_api.core.settings import settings as api_settings  # noqa: E402
from koras_api.core.tenant import require_tenant  # noqa: E402
from koras_api.main import app  # noqa: E402
from koras_api.routers import imports as routes  # noqa: E402
from koras_auth import JWTClaims  # noqa: E402
from koras_import import parse_import_activation  # noqa: E402
from koras_platform import OrganizationRole  # noqa: E402
from koras_queue import JobEnvelope  # noqa: E402
from koras_tenant import TenantContext  # noqa: E402

app.state.redis = None

REPO = Path(__file__).resolve().parents[2]
TENANT = "00000000-0000-0000-0000-000000000001"
SUBJECT = "user-1"
OWNER = frozenset({OrganizationRole.OWNER})
MEMBER = frozenset({OrganizationRole.MEMBER})

#: Every spelling that must not switch anything on.
OFF_VALUES = ["", "   ", "false", "False", "0", "no", "off", "garbage", "tru", "truee", "2", "null"]
ON_VALUES = ["true", "TRUE", " True ", "1", "yes", "on"]


# -- the parse rule, in both processes, to one answer ---------------------------------


@pytest.mark.parametrize("value", OFF_VALUES)
def test_every_unrecognised_value_is_off_in_the_api(value: str) -> None:
    assert parse_import_activation(value) is False
    assert Settings(imports_enabled=value, **_required()).imports_enabled is False  # type: ignore[arg-type]


@pytest.mark.parametrize("value", ON_VALUES)
def test_only_an_explicit_on_is_on_in_the_api(value: str) -> None:
    assert parse_import_activation(value) is True
    assert Settings(imports_enabled=value, **_required()).imports_enabled is True  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [None, 0, 1, 2.5, [], {}, b"true"])
def test_a_non_string_non_bool_is_off(value: object) -> None:
    assert parse_import_activation(value) is False


def test_the_api_default_is_off_when_the_variable_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("IMPORTS_ENABLED", raising=False)
    assert Settings(_env_file=None, **_required()).imports_enabled is False  # type: ignore[call-arg]


@pytest.mark.parametrize("value", [*OFF_VALUES, *ON_VALUES])
def test_the_worker_reads_every_value_exactly_as_the_api_does(
    value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("IMPORTS_ENABLED", value)
    worker = task.ImportSettings(_env_file=None)  # type: ignore[call-arg]
    assert worker.imports_enabled is parse_import_activation(value)


def test_the_worker_default_is_off_when_the_variable_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("IMPORTS_ENABLED", raising=False)
    assert task.ImportSettings(_env_file=None).imports_enabled is False  # type: ignore[call-arg]


def test_neither_process_ships_a_default_of_on() -> None:
    """Not in a deployment config, a compose file, an env template or an infrastructure file."""
    offenders = []
    for path in REPO.rglob("*"):
        if not path.is_file() or any(
            part in {".git", ".venv", "node_modules", "__pycache__", ".next", "worktrees"}
            for part in path.relative_to(REPO).parts
        ):
            continue
        if path.suffix not in {".toml", ".yaml", ".yml", ".env", ".tf", ".example", ".json", ""}:
            continue
        if path.name == "package.json" or path.stat().st_size > 400_000:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if re.search(r"IMPORTS_ENABLED\s*[=:]\s*[\"']?(true|1|yes|on)\b", text, re.IGNORECASE):
            offenders.append(path.relative_to(REPO).as_posix())
    assert offenders == []


# -- the API: every route, one answer -------------------------------------------------


class _Result:
    def first(self) -> None:
        return None

    def one(self) -> None:
        raise AssertionError("a refused request selected a row")

    def __iter__(self) -> Iterator[Any]:
        return iter(())

    def all(self) -> list[Any]:
        return []


class _Session:
    def __init__(self) -> None:
        self.statements: list[str] = []
        self.commits = 0

    async def execute(self, statement: object, parameters: dict[str, Any] | None = None) -> _Result:
        self.statements.append(" ".join(str(statement).split()))
        return _Result()

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        return None


@dataclass
class _Audit:
    rows: list[dict[str, Any]] = field(default_factory=list)

    async def __call__(self, session: object, **fields: Any) -> None:  # noqa: ANN401
        self.rows.append(fields)


def _client(session: _Session, roles: frozenset[OrganizationRole] = OWNER) -> TestClient:
    async def _db() -> AsyncIterator[_Session]:
        yield session

    app.dependency_overrides[require_auth] = lambda: JWTClaims(
        sub=SUBJECT, roles=roles, organization_id="org-1"
    )
    app.dependency_overrides[require_tenant] = lambda: TenantContext(
        id=TENANT, slug="alpha", name="Alpha", organization_id="org-1", user_id=SUBJECT
    )
    app.dependency_overrides[get_db] = _db
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _clean() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def audit(monkeypatch: pytest.MonkeyPatch) -> _Audit:
    sink = _Audit()
    monkeypatch.setattr(routes, "record", sink)
    return sink


def _import_routes() -> list[tuple[str, str]]:
    found = []
    for route in routes.router.routes:
        assert isinstance(route, APIRoute)
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            found.append((method, route.path))
    return found


def _url(path: str) -> str:
    return "/api/v1" + re.sub(r"\{(\w+)\}", "00000000-0000-0000-0000-0000000000aa", path)


def test_the_router_exposes_the_twelve_routes_this_gate_was_written_against() -> None:
    """If this fails a route was added or removed: read the gate again, then update the list."""
    assert sorted(_import_routes()) == sorted(
        [
            ("GET", "/imports/targets"),
            ("GET", "/imports/targets/{key}/template"),
            ("GET", "/imports"),
            ("POST", "/imports"),
            ("GET", "/imports/sources/{file_id}"),
            ("GET", "/imports/{run_id}"),
            ("GET", "/imports/{run_id}/analysis"),
            ("PUT", "/imports/{run_id}/mapping"),
            ("POST", "/imports/{run_id}/validate"),
            ("POST", "/imports/{run_id}/commit"),
            ("GET", "/imports/{run_id}/errors"),
            ("POST", "/imports/{run_id}/cancel"),
        ]
    )


def _refused_everywhere(monkeypatch: pytest.MonkeyPatch, value: object, audit: _Audit) -> None:
    if value is not None:
        monkeypatch.setattr(api_settings, "imports_enabled", parse_import_activation(value))
    session = _Session()
    client = _client(session)
    for method, path in _import_routes():
        # A body that is invalid for every route that takes one: were the gate to run
        # after validation, the answer would be a 422 that names a field.
        answer = client.request(method, _url(path), json={"nonsense": True})
        assert answer.status_code == 403, (method, path, answer.text)
        assert answer.json() == {
            "detail": {
                "code": ApiErrorCode.IMPORT_NOT_ENABLED.value,
                "message": "data import is not enabled",
            }
        }, (method, path)
    # Nothing but the (replaced) audit sink was touched: no run, no target, no file.
    assert session.statements == []
    # Reads are refused without a row (a polling page must not write one per refresh).
    writes = [r for r in _import_routes() if r[0] not in ("GET", "HEAD", "OPTIONS")]
    assert len(audit.rows) == len(writes)
    for row in audit.rows:
        assert row["action"] == "import.refused"
        assert row["outcome"] == "denied"
        assert row["details"] == {"reason": "activation_disabled"}
        assert row["tenant_id"] == TENANT
        assert row["actor_id"] == SUBJECT
        assert row["target_type"] == "import_route"
        # The route template, never the caller's path values, body or a file name.
        assert row["target_id"].startswith("/imports")
        assert "0000" not in row["target_id"] and "nonsense" not in str(row)
    assert session.commits == len(writes)


def test_every_route_refuses_with_the_default_settings(
    monkeypatch: pytest.MonkeyPatch, audit: _Audit
) -> None:
    """The default object, untouched: this is what a deployment with no variable gets."""
    assert Settings(_env_file=None, **_required()).imports_enabled is False  # type: ignore[call-arg]
    monkeypatch.setattr(
        api_settings, "imports_enabled", Settings(_env_file=None, **_required()).imports_enabled
    )  # type: ignore[call-arg]
    _refused_everywhere(monkeypatch, None, audit)


@pytest.mark.parametrize("value", ["", "   ", "garbage", "false", "tru"])
def test_every_route_refuses_with_a_blank_or_malformed_value(
    value: str, monkeypatch: pytest.MonkeyPatch, audit: _Audit
) -> None:
    built = Settings(imports_enabled=value, **_required())  # type: ignore[arg-type]
    monkeypatch.setattr(api_settings, "imports_enabled", built.imports_enabled)
    _refused_everywhere(monkeypatch, None, audit)


def test_post_imports_refuses_while_disabled_even_for_a_valid_body(
    monkeypatch: pytest.MonkeyPatch, audit: _Audit
) -> None:
    monkeypatch.setattr(api_settings, "imports_enabled", False)
    session = _Session()
    answer = _client(session).post(
        "/api/v1/imports",
        json={"target": "parties.accounts", "file_id": "00000000-0000-0000-0000-0000000000bb"},
    )
    assert answer.status_code == 403
    assert answer.json()["detail"]["code"] == "import_not_enabled"
    assert "parties" not in answer.text and "file" not in answer.text.lower().replace("profile", "")
    assert session.statements == []


def test_a_caller_without_the_permission_gets_the_ordinary_refusal_and_no_audit_row(
    monkeypatch: pytest.MonkeyPatch, audit: _Audit
) -> None:
    """The switch's state is not told to someone who could not have used it either way."""
    monkeypatch.setattr(api_settings, "imports_enabled", False)
    answer = _client(_Session(), MEMBER).post("/api/v1/imports", json={})
    assert answer.status_code == 403
    assert answer.json()["detail"]["code"] == ApiErrorCode.PERMISSION_MISSING.value
    assert audit.rows == []


def test_an_unauthenticated_caller_is_still_unauthenticated_not_told_about_the_switch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(api_settings, "imports_enabled", False)
    app.dependency_overrides.clear()
    answer = TestClient(app, raise_server_exceptions=False).post("/api/v1/imports", json={})
    assert answer.status_code in {401, 403}
    assert "import_not_enabled" not in answer.text


@pytest.mark.parametrize("value", ON_VALUES)
def test_an_explicit_on_lets_a_request_past_the_gate(
    value: str, monkeypatch: pytest.MonkeyPatch, audit: _Audit
) -> None:
    """Past the gate means the route's own logic answers: here, an unknown target is a 404."""
    monkeypatch.setattr(api_settings, "imports_enabled", parse_import_activation(value))
    answer = _client(_Session()).post(
        "/api/v1/imports",
        json={"target": "no.such.target", "file_id": "00000000-0000-0000-0000-0000000000bb"},
    )
    assert answer.status_code == 404
    assert answer.json()["detail"]["code"] == ApiErrorCode.IMPORT_TARGET_NOT_FOUND.value
    assert audit.rows == []


def test_enabled_routes_answer_as_before(monkeypatch: pytest.MonkeyPatch, audit: _Audit) -> None:
    monkeypatch.setattr(api_settings, "imports_enabled", True)
    answer = _client(_Session()).get("/api/v1/imports/targets")
    assert answer.status_code == 200
    assert audit.rows == []


def test_the_refusal_is_a_registered_security_audit_action() -> None:
    """An unregistered action is refused by the real audit sink, which these tests replace.

    Found by the worker-image test: the refusal was written with a key nobody had registered,
    and the recording failure is (deliberately) swallowed -- so the job was refused and left no
    evidence. The catalogue is the only place that notices.
    """
    from koras_api.core import imports as store
    from koras_api.core.audit import actions

    assert "import.refused" in {a.key for a in store.IMPORT_ACTIONS}
    assert str(actions.classification_of("import.refused")) == "security"


# -- the guard: a new route cannot be added without the gate --------------------------


def _openapi_import_operations() -> set[tuple[str, str]]:
    app.openapi_schema = None
    paths = app.openapi()["paths"]
    return {
        (method.upper(), path.removeprefix("/api/v1"))
        for path, ops in paths.items()
        if "/imports" in path
        for method in ops
    }


def test_the_assembled_app_serves_the_imports_router_and_nothing_else_on_an_imports_path() -> None:
    """Measured on the assembled app, so a second router on `/imports` is seen too."""
    mounted = [r for r in app.routes if getattr(r, "original_router", None) is routes.router]
    assert len(mounted) == 1
    assert _openapi_import_operations() == set(_import_routes())


def test_the_gate_is_on_the_router_so_a_new_route_inherits_it() -> None:
    assert any(d.dependency is routes.require_import_activation for d in routes.router.dependencies)


def test_a_route_added_later_is_gated_without_its_author_doing_anything() -> None:
    probe = routes.APIRouter(tags=["x"], dependencies=routes.router.dependencies)

    @probe.get("/probe")
    async def _probe() -> dict[str, bool]:  # pragma: no cover - never called
        return {"ok": True}

    assert any(d.dependency is routes.require_import_activation for d in probe.dependencies)


def _py_files() -> list[Path]:
    return [
        p
        for root in ("api/koras_api", "worker/koras_worker")
        for p in (REPO / "services" / root).rglob("*.py")
        if "__pycache__" not in p.parts
    ]


def test_only_the_router_and_the_task_touch_the_import_jobs_and_the_run_store() -> None:
    """Another module that enqueues or consumes an import job is a path around the gate."""
    allowed = {
        "services/api/koras_api/routers/imports.py",
        "services/worker/koras_worker/tasks/imports.py",
    }
    names = (
        "VALIDATE_RUN",
        "COMMIT_RUN",
        "source_bytes(",
        "begin_commit(",
        # The task's own bodies and the task names as strings: a product task that calls
        # `_validate_run` directly, or enqueues `"imports.commit"` by name, is a path around.
        "_validate_run",
        "_commit_run",
        "imports.validate",
        "imports.commit",
    )
    found = {
        p.relative_to(REPO).as_posix()
        for p in _py_files()
        if p.relative_to(REPO).as_posix() != "services/api/koras_api/core/imports.py"
        and any(n in p.read_text(encoding="utf-8") for n in names)
    }
    assert found <= allowed, found - allowed


def test_the_worker_binds_exactly_two_tasks_and_both_start_with_the_gate() -> None:
    assert [b.name for b in task.bound()] == [
        "imports.validate",
        "imports.commit",
    ] or len(task.bound()) == 2
    tree = ast.parse((REPO / "services/worker/koras_worker/tasks/imports.py").read_text("utf-8"))
    bound_functions = {"validate_run", "commit_run"}
    seen = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name in bound_functions:
            seen.add(node.name)
            body = [
                s
                for s in node.body
                if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))
            ]
            # `del ctx`, then the gate, then everything else.
            assert isinstance(body[0], ast.Delete)
            gate = body[1]
            assert isinstance(gate, ast.If)
            assert "_refuse_while_disabled" in ast.unparse(gate.test)
            assert isinstance(gate.body[0], ast.Return)
    assert seen == bound_functions


def test_every_public_task_that_takes_an_envelope_starts_with_the_gate() -> None:
    """A second task function added to the module cannot skip the gate by not being bound."""
    tree = ast.parse((REPO / "services/worker/koras_worker/tasks/imports.py").read_text("utf-8"))
    public = [
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef)
        and not node.name.startswith("_")
        and any(arg.arg == "envelope" for arg in node.args.args)
    ]
    assert {node.name for node in public} == {"validate_run", "commit_run"}


# -- the worker: a job enqueued before the switch went off ----------------------------


class _Boom:
    """Anything the refused job must never reach."""

    def __init__(self, what: str) -> None:
        self.what = what

    def __call__(self, *_: object, **__: object) -> Any:  # noqa: ANN401
        raise AssertionError(f"a refused import job reached {self.what}")


@dataclass
class _Run:
    id: str
    status: str


#: What the refusal did to its session, in order. Row-level security needs the tenant said
#: again after the commit that ends the abandon's transaction, and only a real database
#: notices when it is not (`tests/integration/test_worker_image.py` does).
_EVENTS: list[str] = []


class _WSession:
    async def __aenter__(self) -> _WSession:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def execute(self, *_: object, **__: object) -> None:
        _EVENTS.append("tenant")

    async def commit(self) -> None:
        _EVENTS.append("commit")


class _Engine:
    disposed = 0

    async def dispose(self) -> None:
        _Engine.disposed += 1


@dataclass
class _Store:
    runs: dict[str, _Run]
    abandoned: dict[str, str] = field(default_factory=dict)

    async def get(self, _session: object, run_id: str) -> _Run | None:
        return self.runs.get(run_id)

    async def abandon(self, _session: object, run: _Run, reason: str) -> bool:
        _EVENTS.append("abandon")
        run.status = "failed"
        self.abandoned[run.id] = reason
        return True

    # The two ways a file is reached; neither may be called.
    source_bytes = _Boom("the source file")
    examine = _Boom("the reader")


def _job(run_id: str = "run-1") -> JobEnvelope:
    return JobEnvelope(task="imports.validate", tenant_id=TENANT, payload={"run_id": run_id})


@pytest.fixture
def refusing_worker(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """The task with imports off and every route to a file wired to fail the test."""
    recorded: list[dict[str, Any]] = []

    async def record(_session: object, **fields: Any) -> None:  # noqa: ANN401
        _EVENTS.append("record")
        recorded.append(fields)

    _EVENTS.clear()

    store = _Store(
        {"run-1": _Run("run-1", "validating"), "run-2": _Run("run-2", "commit_requested")}
    )
    monkeypatch.setattr(task.imports, "imports_enabled", False)
    monkeypatch.setattr(task, "settings", type("S", (), {"database_url": "postgresql://x/y"})())
    monkeypatch.setattr(task, "_run_store", lambda: store)
    monkeypatch.setattr(task, "_engine", _Engine)
    monkeypatch.setattr(task, "async_sessionmaker", lambda *_, **__: _WSession)
    monkeypatch.setattr(task, "_record", record)
    monkeypatch.setattr(task, "_object_store", _Boom("the object store"))
    monkeypatch.setattr(task, "_registry", _Boom("the target registry"))
    monkeypatch.setattr(task, "heavy", _Boom("the heavy gate"))
    monkeypatch.setattr(task, "_validate_run", _Boom("the validation body"))
    monkeypatch.setattr(task, "_commit_run", _Boom("the commit body"))
    return {"store": store, "recorded": recorded}


@pytest.mark.parametrize(
    ("fn", "run_id", "job"),
    [("validate_run", "run-1", "validate"), ("commit_run", "run-2", "commit")],
)
def test_a_worker_job_refuses_while_disabled_without_reaching_the_file(
    refusing_worker: dict[str, Any], fn: str, run_id: str, job: str
) -> None:
    answer = asyncio.run(getattr(task, fn)({}, _job(run_id)))
    assert answer == {"status": "refused", "reason": "activation_disabled"}
    store: _Store = refusing_worker["store"]
    # The stranded run is failed with a safe sentence, not left spinning or advanced.
    assert store.runs[run_id].status == "failed"
    assert "not enabled" in store.abandoned[run_id]
    (event,) = refusing_worker["recorded"]
    assert event["action"] == "import.refused"
    assert event["outcome"] == "denied"
    assert event["run_id"] == run_id
    assert event["details"] == {"reason": "activation_disabled", "job": job}


def test_the_tenant_is_said_again_after_the_commit_and_before_the_audit_row(
    refusing_worker: dict[str, Any],
) -> None:
    asyncio.run(task.validate_run({}, _job("run-1")))
    assert _EVENTS == ["tenant", "abandon", "commit", "tenant", "record"]


def test_a_refused_job_with_no_database_is_still_refused(
    refusing_worker: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(task, "settings", type("S", (), {"database_url": ""})())
    answer = asyncio.run(task.commit_run({}, _job("run-2")))
    assert answer == {"status": "refused", "reason": "activation_disabled"}
    assert refusing_worker["recorded"] == []


def test_a_refused_job_whose_refusal_cannot_be_recorded_is_still_refused(
    refusing_worker: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken() -> object:
        raise RuntimeError("no store")

    monkeypatch.setattr(task, "_run_store", broken)
    answer = asyncio.run(task.validate_run({}, _job()))
    assert answer == {"status": "refused", "reason": "activation_disabled"}


def test_a_job_with_no_run_id_is_refused_without_a_database_call(
    refusing_worker: dict[str, Any],
) -> None:
    envelope = JobEnvelope(task="imports.validate", tenant_id=TENANT, payload={})
    assert asyncio.run(task.validate_run({}, envelope)) == {
        "status": "refused",
        "reason": "activation_disabled",
    }
    assert refusing_worker["recorded"] == []


def test_an_enabled_worker_proceeds_past_the_gate(
    refusing_worker: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(task.imports, "imports_enabled", True)
    reached: list[str] = []

    async def body(*_: object, **__: object) -> dict[str, str]:
        reached.append("body")
        return {"status": "ok"}

    class _Gate:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, *_: object) -> None:
            return None

    monkeypatch.setattr(task, "heavy", lambda *_, **__: _Gate())
    monkeypatch.setattr(task, "_validate_run", body)
    monkeypatch.setattr(task, "_commit_run", body)
    assert asyncio.run(task.validate_run({}, _job())) == {"status": "ok"}
    assert asyncio.run(task.commit_run({}, _job())) == {"status": "ok"}
    assert reached == ["body", "body"]
    assert refusing_worker["recorded"] == []


def _required() -> dict[str, str]:
    return {
        "environment": "dev",
        "database_url": "postgresql://u:p@localhost/db",
        "zitadel_domain": "https://example.invalid",
        "zitadel_project_id": "0",
    }
