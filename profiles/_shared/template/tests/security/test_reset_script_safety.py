"""`local/scripts/reset.sh` must refuse an unscoped, unconfirmed teardown.

**Why this exists.** `make reset` and `pnpm stack:reset` used to run `docker
compose down --volumes` directly -- an irreversible deletion of every local
database, queue and object-storage volume, the local ZITADEL instance
included -- with no confirmation and no check that docker was pointed at this
laptop. Docoris found the gap (its D-018) and guarded its own `reset.sh`; the
Starter adopted those guards for every generated project on 2026-10-09 and
added three: refuse in a linked git worktree (worktrees share the compose
project name, so a reset there deletes the main checkout's volumes), refuse
when the volumes cannot be listed first, and move `.env.local` aside rather
than delete it. Both entry points now call this script and nothing else. This
suite proves the guards hold by running the script, rather than trusting the
source by inspection.

**Why pytest, not bats.** This repository has no shell-test harness (no
`.bats` file anywhere in the tree); its established pattern for asserting
behaviour of a script under `local/scripts/` is a pytest module that shells
out to it and inspects exit code / stderr (see
tests/security/test_no_state_artifacts.py for the same shape, applied to
`git`). This module follows that pattern rather than inventing a new one.

**Why the script itself is copied into a fixture tree rather than run in
place.** `reset.sh` resolves `ROOT` from its own path
(`dirname "$0"/../..`) and, on success, moves `ROOT/.env.local` aside and execs
`ROOT/local/scripts/bootstrap.sh`. Running the real script against the real
repository would risk exactly what it is being tested for. Each test builds a
throwaway `ROOT` with only what reset.sh reads (`local/docker-compose.yml`,
`local/scripts/bootstrap.sh`, optionally `.env.local`), a stub `docker` on
`PATH` that records its invocation instead of touching a real daemon, and a
stub `bootstrap.sh` that records its invocation instead of reinstalling
anything. Nothing here starts, stops or touches Docker.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RESET_SCRIPT = REPO_ROOT / "local" / "scripts" / "reset.sh"
BASH = shutil.which("bash") or "bash"


def _make_executable(path: Path) -> None:
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _build_root(tmp_path: Path, *, env_local: str | None) -> Path:
    """A throwaway repository root with exactly what reset.sh reads."""
    root = tmp_path / "root"
    (root / "local" / "scripts").mkdir(parents=True)
    (root / "local" / "docker-compose.yml").write_text("name: fixture\n", encoding="utf-8")

    if env_local is not None:
        (root / ".env.local").write_text(env_local, encoding="utf-8")

    marker = root / "bootstrap-ran"
    bootstrap = root / "local" / "scripts" / "bootstrap.sh"
    bootstrap.write_text(
        f"#!/usr/bin/env bash\ntouch {marker.as_posix()!r}\n",
        encoding="utf-8",
    )
    _make_executable(bootstrap)

    real_reset = root / "local" / "scripts" / "reset.sh"
    shutil.copy2(RESET_SCRIPT, real_reset)
    _make_executable(real_reset)

    return root


def _stub_docker(
    tmp_path: Path,
    *,
    context_name: str = "default",
    context_show_fails: bool = False,
    context_host: str = "unix:///var/run/docker.sock",
    context_inspect_fails: bool = False,
    volumes: tuple[str, ...] = ("fixture_supabase-db",),
    volume_ls_fails: bool = False,
) -> tuple[Path, Path]:
    """A fake `docker` ahead of the real one on PATH, recording invocations.

    Also answers `docker context show` / `docker context inspect ... --format
    ...` the way a real Docker CLI would, since reset.sh's docker-context
    guard shells out to both before ever reaching `compose down`.
    Every existing caller gets the common case for free: an active context
    named "default", which reset.sh skips inspecting entirely. Tests for the
    guard itself override context_name / context_host / the *_fails flags to
    simulate a remote or unverifiable context.
    """
    bin_dir = tmp_path / "fake-bin"
    bin_dir.mkdir(exist_ok=True)
    calls = tmp_path / "docker-calls.log"
    docker = bin_dir / "docker"
    show_exit = 1 if context_show_fails else 0
    inspect_exit = 1 if context_inspect_fails else 0
    script = (
        "#!/usr/bin/env bash\n"
        f'echo "$@" >> {calls.as_posix()!r}\n'
        'if [ "$1" = "context" ] && [ "$2" = "show" ]; then\n'
        f"  echo {context_name!r}\n"
        f"  exit {show_exit}\n"
        "fi\n"
        'if [ "$1" = "context" ] && [ "$2" = "inspect" ]; then\n'
        f"  echo {context_host!r}\n"
        f"  exit {inspect_exit}\n"
        "fi\n"
        'if [ "$1" = "volume" ] && [ "$2" = "ls" ]; then\n'
        + "".join(f"  echo {v!r}\n" for v in volumes)
        + f"  exit {1 if volume_ls_fails else 0}\n"
        "fi\n"
        "exit 0\n"
    )
    docker.write_text(script, encoding="utf-8")
    _make_executable(docker)
    return bin_dir, calls


LOCAL_ENV = """\
DATABASE_URL=postgresql://postgres:postgres@localhost:54322/postgres
ZITADEL_DOMAIN=http://localhost:8080
ZITADEL_REDIRECT_URI=https://app.localhost/api/auth/callback
ZITADEL_ADMIN_REDIRECT_URI=https://admin.localhost/api/auth/callback
REDIS_URL=redis://localhost:6379
SMTP_HOST=localhost
STORAGE_ENDPOINT=http://localhost:9000
AI_GATEWAY_URL=http://localhost:4000
KORAS_CONTROL_PLANE_URL=http://localhost:8001
NEXT_PUBLIC_APP_URL=https://app.localhost
NEXT_PUBLIC_API_URL=https://api.localhost
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
CORS_ORIGINS=["https://app.localhost","https://admin.localhost"]
"""

NON_LOCAL_ENV = LOCAL_ENV.replace(
    "DATABASE_URL=postgresql://postgres:postgres@localhost:54322/postgres",
    "DATABASE_URL=postgresql://postgres:postgres@prod-db.example.com:5432/postgres",
)


def _run(
    root: Path, bin_dir: Path, *args: str, stdin_is_tty: bool = False
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env.pop("DOCKER_HOST", None)
    # subprocess's own stdin is never a TTY regardless of what is passed here;
    # DEVNULL/PIPE both give reset.sh's `[ -t 0 ]` check a non-terminal fd,
    # which is what every test below actually needs -- see the docstring on
    # test_no_tty_and_no_flag_refuses for why "stdin_is_tty" is not literally
    # honoured.
    stdin = subprocess.DEVNULL
    return subprocess.run(  # noqa: S603 -- fixed argv, absolute binary
        [BASH, str(root / "local" / "scripts" / "reset.sh"), *args],
        cwd=root,
        env=env,
        stdin=stdin,
        capture_output=True,
        text=True,
        timeout=30,
    )


class TestConfirmationGuard:
    def test_no_tty_and_no_flag_refuses(self, tmp_path: Path) -> None:
        """Bare, non-interactive, no flag: must refuse, not hang, not proceed.

        This is the behaviour actually implemented, verified directly rather
        than assumed: reset.sh checks `[ -t 0 ]` and, finding no TTY, exits 1
        with a message -- it does not attempt an interactive `read` that would
        block forever under pytest's captured, non-TTY stdin.
        """
        root = _build_root(tmp_path, env_local=LOCAL_ENV)
        bin_dir, calls = _stub_docker(tmp_path)

        result = _run(root, bin_dir)

        assert result.returncode != 0, result.stdout + result.stderr
        assert "no TTY" in result.stderr or "TTY" in result.stderr, result.stderr
        # The docker-context guard reads (never mutates) the active
        # context before the confirmation prompt is reached, so calls.log may
        # now legitimately contain a `context show` probe; what must never
        # appear is the actual destructive teardown.
        assert "down" not in (calls.read_text(encoding="utf-8") if calls.exists() else ""), (
            "docker compose down must never run without confirmation"
        )
        assert not (root / "bootstrap-ran").exists()

    def test_force_flag_skips_the_prompt_and_proceeds(self, tmp_path: Path) -> None:
        root = _build_root(tmp_path, env_local=LOCAL_ENV)
        bin_dir, calls = _stub_docker(tmp_path)

        result = _run(root, bin_dir, "--force")

        assert result.returncode == 0, result.stdout + result.stderr
        assert calls.exists(), "docker compose down should have run under --force"
        assert "down" in calls.read_text(encoding="utf-8")
        assert (root / "bootstrap-ran").exists(), "bootstrap.sh should have run after teardown"

    def test_yes_flag_is_also_accepted(self, tmp_path: Path) -> None:
        root = _build_root(tmp_path, env_local=LOCAL_ENV)
        bin_dir, calls = _stub_docker(tmp_path)

        result = _run(root, bin_dir, "--yes")

        assert result.returncode == 0, result.stdout + result.stderr
        assert calls.exists()

    def test_help_does_not_require_confirmation(self, tmp_path: Path) -> None:
        root = _build_root(tmp_path, env_local=LOCAL_ENV)
        bin_dir, calls = _stub_docker(tmp_path)

        result = _run(root, bin_dir, "--help")

        assert result.returncode == 0
        assert not calls.exists()


class TestLocalEndpointGuard:
    def test_a_non_local_database_url_is_refused(self, tmp_path: Path) -> None:
        """Even with --force, a non-local endpoint must stop the script.

        --force only waives the interactive prompt; it must not waive the
        local-endpoint check, which is exactly the scenario a shell that
        loaded deployed values into .env.local (or its own environment) would
        hit.
        """
        root = _build_root(tmp_path, env_local=NON_LOCAL_ENV)
        bin_dir, calls = _stub_docker(tmp_path)

        result = _run(root, bin_dir, "--force")

        assert result.returncode != 0, result.stdout + result.stderr
        assert "DATABASE_URL" in result.stderr, result.stderr
        assert "prod-db.example.com" in result.stderr, result.stderr
        assert not calls.exists(), "docker must never run once a non-local endpoint is found"
        assert not (root / "bootstrap-ran").exists()

    def test_a_non_local_docker_host_is_refused(self, tmp_path: Path) -> None:
        root = _build_root(tmp_path, env_local=LOCAL_ENV)
        bin_dir, calls = _stub_docker(tmp_path)

        env = dict(os.environ)
        env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
        env["DOCKER_HOST"] = "tcp://build-farm.example.com:2375"
        result = subprocess.run(  # noqa: S603 -- fixed argv, absolute binary
            [BASH, str(root / "local" / "scripts" / "reset.sh"), "--force"],
            cwd=root,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode != 0, result.stdout + result.stderr
        assert "DOCKER_HOST" in result.stderr, result.stderr
        assert not calls.exists()

    @pytest.mark.parametrize(
        "sneaky_host",
        [
            "localhost.attacker.example",
            "127.0.0.1.attacker.example",
        ],
    )
    def test_lookalike_hosts_are_not_accepted_as_local(
        self, tmp_path: Path, sneaky_host: str
    ) -> None:
        """A substring check would wrongly admit these; the anchored regex must not."""
        env_local = LOCAL_ENV.replace(
            "DATABASE_URL=postgresql://postgres:postgres@localhost:54322/postgres",
            f"DATABASE_URL=postgresql://postgres:postgres@{sneaky_host}:5432/postgres",
        )
        root = _build_root(tmp_path, env_local=env_local)
        bin_dir, calls = _stub_docker(tmp_path)

        result = _run(root, bin_dir, "--force")

        assert result.returncode != 0, result.stdout + result.stderr
        assert sneaky_host in result.stderr, result.stderr
        assert not calls.exists()

    @pytest.mark.parametrize(
        "loopback_host",
        [
            "127.0.0.2",
            "127.1.2.3",
            "127.255.255.255",
        ],
    )
    def test_full_127_range_is_accepted_as_local(self, tmp_path: Path, loopback_host: str) -> None:
        """The whole 127.0.0.0/8 block is loopback (RFC 1122), not just 127.0.0.1.

        Rejecting these would be a fail-closed false refusal, not a security
        defect, but it is still wrong: a developer legitimately bound to
        127.0.0.2 must not be told this looks non-local.
        """
        env_local = LOCAL_ENV.replace(
            "DATABASE_URL=postgresql://postgres:postgres@localhost:54322/postgres",
            f"DATABASE_URL=postgresql://postgres:postgres@{loopback_host}:5432/postgres",
        )
        root = _build_root(tmp_path, env_local=env_local)
        bin_dir, calls = _stub_docker(tmp_path)

        result = _run(root, bin_dir, "--force")

        assert result.returncode == 0, result.stdout + result.stderr
        assert calls.exists()

    @pytest.mark.parametrize(
        "upper_host",
        [
            "LOCALHOST",
            "LocalHost",
        ],
    )
    def test_uppercase_localhost_is_accepted_as_local(
        self, tmp_path: Path, upper_host: str
    ) -> None:
        """Hostname matching is case-insensitive, matching real DNS semantics.

        Refusing `LOCALHOST` would again be fail-closed rather than a security
        defect, but a case-sensitive check is still a real usability bug this
        review flagged; the anchoring itself (proven by
        test_lookalike_hosts_are_not_accepted_as_local above) must not regress
        while fixing it.
        """
        env_local = LOCAL_ENV.replace(
            "DATABASE_URL=postgresql://postgres:postgres@localhost:54322/postgres",
            f"DATABASE_URL=postgresql://postgres:postgres@{upper_host}:54322/postgres",
        )
        root = _build_root(tmp_path, env_local=env_local)
        bin_dir, calls = _stub_docker(tmp_path)

        result = _run(root, bin_dir, "--force")

        assert result.returncode == 0, result.stdout + result.stderr
        assert calls.exists()

    def test_no_env_local_at_all_is_not_a_refusal(self, tmp_path: Path) -> None:
        """A fresh checkout with no .env.local yet must not be blocked forever."""
        root = _build_root(tmp_path, env_local=None)
        bin_dir, calls = _stub_docker(tmp_path)

        result = _run(root, bin_dir, "--force")

        assert result.returncode == 0, result.stdout + result.stderr
        assert calls.exists()

    @pytest.mark.parametrize(
        "name,bad_value,host_fragment",
        [
            (
                "ZITADEL_REDIRECT_URI",
                "https://app.example.com/api/auth/callback",
                "app.example.com",
            ),
            (
                "ZITADEL_ADMIN_REDIRECT_URI",
                "https://admin.example.com/api/auth/callback",
                "admin.example.com",
            ),
            (
                "OTEL_EXPORTER_OTLP_ENDPOINT",
                "http://collector.example.com:4317",
                "collector.example.com",
            ),
        ],
    )
    def test_newly_covered_scalar_endpoints_are_checked(
        self, tmp_path: Path, name: str, bad_value: str, host_fragment: str
    ) -> None:
        """The three MEDIUM-finding variables reset.sh gained a check for.

        Each was present in local/config/.env.local.example but absent from
        reset.sh's guard loop; a shell carrying a deployed value for any of
        them must now be refused exactly like DATABASE_URL already was.
        """
        env_local = LOCAL_ENV + f"{name}={bad_value}\n"
        root = _build_root(tmp_path, env_local=env_local)
        bin_dir, calls = _stub_docker(tmp_path)

        result = _run(root, bin_dir, "--force")

        assert result.returncode != 0, result.stdout + result.stderr
        assert name in result.stderr, result.stderr
        assert host_fragment in result.stderr, result.stderr
        assert not calls.exists()

    def test_a_non_local_cors_origin_is_refused(self, tmp_path: Path) -> None:
        """CORS_ORIGINS is a JSON array; one bad origin inside it must still refuse.

        This is the fourth MEDIUM-finding variable. It is list-shaped, not a
        single URL, so it is checked element-by-element
        (check_local_endpoint_list) rather than by the same code path as a
        scalar endpoint -- this test is what proves that path actually runs
        per-origin instead of silently no-op'ing on the whole array.
        """
        env_local = LOCAL_ENV.replace(
            'CORS_ORIGINS=["https://app.localhost","https://admin.localhost"]',
            'CORS_ORIGINS=["https://app.localhost","https://admin.example.com"]',
        )
        root = _build_root(tmp_path, env_local=env_local)
        bin_dir, calls = _stub_docker(tmp_path)

        result = _run(root, bin_dir, "--force")

        assert result.returncode != 0, result.stdout + result.stderr
        assert "CORS_ORIGINS" in result.stderr, result.stderr
        assert "admin.example.com" in result.stderr, result.stderr
        assert not calls.exists()

    def test_all_local_cors_origins_do_not_block(self, tmp_path: Path) -> None:
        """The positive case for the list-shaped variable: every origin local."""
        root = _build_root(tmp_path, env_local=LOCAL_ENV)
        bin_dir, calls = _stub_docker(tmp_path)

        result = _run(root, bin_dir, "--force")

        assert result.returncode == 0, result.stdout + result.stderr
        assert calls.exists()


class TestDockerContextGuard:
    """`docker context` is a second, DOCKER_HOST-invisible way to point every
    docker invocation at a remote daemon (MEDIUM finding #1). These tests
    drive reset.sh's `docker context show` / `docker context inspect` calls
    through the context-aware `_stub_docker`, never a real Docker daemon.
    """

    def test_default_context_proceeds_normally(self, tmp_path: Path) -> None:
        """The common case: `docker context show` returns `default`.

        This must keep working exactly as before -- the new guard must not
        regress the ordinary developer machine where nobody has touched
        `docker context`.
        """
        root = _build_root(tmp_path, env_local=LOCAL_ENV)
        bin_dir, calls = _stub_docker(tmp_path, context_name="default")

        result = _run(root, bin_dir, "--force")

        assert result.returncode == 0, result.stdout + result.stderr
        assert calls.exists()
        assert (root / "bootstrap-ran").exists()

    def test_non_default_context_with_remote_endpoint_is_refused(self, tmp_path: Path) -> None:
        """A non-default context pointing at a remote daemon must refuse.

        `DOCKER_HOST` is unset in this test (see `_run`), so only the
        context-inspection guard can be what catches this -- exactly the gap
        the review flagged: `docker context use <remote>` leaves DOCKER_HOST
        alone entirely.
        """
        root = _build_root(tmp_path, env_local=LOCAL_ENV)
        bin_dir, calls = _stub_docker(
            tmp_path,
            context_name="build-farm",
            context_host="tcp://build-farm.example.com:2375",
        )

        result = _run(root, bin_dir, "--force")

        assert result.returncode != 0, result.stdout + result.stderr
        assert "docker context" in result.stderr, result.stderr
        assert "build-farm" in result.stderr, result.stderr
        assert "build-farm.example.com" in result.stderr, result.stderr
        # docker context show/inspect are read-only probes the guard itself
        # makes, so calls.log legitimately contains them; only the destructive
        # teardown must never run.
        logged = calls.read_text(encoding="utf-8") if calls.exists() else ""
        assert "down" not in logged, "docker compose must never run once a remote context is found"
        assert not (root / "bootstrap-ran").exists()

    def test_non_default_context_with_local_endpoint_proceeds(self, tmp_path: Path) -> None:
        """A non-default context is not itself disqualifying -- only a non-local one.

        A developer who named their default-daemon context something other
        than "default" must not be blocked.
        """
        root = _build_root(tmp_path, env_local=LOCAL_ENV)
        bin_dir, calls = _stub_docker(
            tmp_path,
            context_name="my-local-context",
            context_host="unix:///var/run/docker.sock",
        )

        result = _run(root, bin_dir, "--force")

        assert result.returncode == 0, result.stdout + result.stderr
        assert calls.exists()

    def test_context_show_failure_fails_closed(self, tmp_path: Path) -> None:
        """If `docker context show` cannot be run at all, refuse rather than skip.

        Modeled on an older Docker CLI with no `context` subcommand, or any
        other reason the command might error: reset.sh must treat "cannot
        verify" as "not verified as local", never as "assume default".
        """
        root = _build_root(tmp_path, env_local=LOCAL_ENV)
        bin_dir, calls = _stub_docker(tmp_path, context_show_fails=True)

        result = _run(root, bin_dir, "--force")

        assert result.returncode != 0, result.stdout + result.stderr
        assert "docker context" in result.stderr, result.stderr
        logged = calls.read_text(encoding="utf-8") if calls.exists() else ""
        assert "down" not in logged
        assert not (root / "bootstrap-ran").exists()

    def test_context_inspect_failure_fails_closed(self, tmp_path: Path) -> None:
        """A non-default context that cannot be inspected must also refuse."""
        root = _build_root(tmp_path, env_local=LOCAL_ENV)
        bin_dir, calls = _stub_docker(tmp_path, context_name="mystery", context_inspect_fails=True)

        result = _run(root, bin_dir, "--force")

        assert result.returncode != 0, result.stdout + result.stderr
        assert "mystery" in result.stderr, result.stderr
        logged = calls.read_text(encoding="utf-8") if calls.exists() else ""
        assert "down" not in logged
        assert not (root / "bootstrap-ran").exists()


class TestBothGuardsSatisfied:
    def test_proceeds_only_when_local_and_confirmed(self, tmp_path: Path) -> None:
        """The positive case: local endpoints, explicit confirmation, real teardown attempted."""
        root = _build_root(tmp_path, env_local=LOCAL_ENV)
        bin_dir, calls = _stub_docker(tmp_path)

        result = _run(root, bin_dir, "--force")

        assert result.returncode == 0, result.stdout + result.stderr
        # Moved aside, never deleted: it can hold values nothing regenerates.
        assert not (root / ".env.local").exists(), ".env.local should be moved aside"
        kept = list(root.glob(".env.local.pre-reset-*"))
        assert len(kept) == 1, kept
        assert kept[0].read_text(encoding="utf-8") == LOCAL_ENV
        assert (root / "bootstrap-ran").exists()
        logged = calls.read_text(encoding="utf-8")
        assert "down" in logged and "--volumes" in logged and "--remove-orphans" in logged

    def test_neither_guard_satisfied_refuses_before_touching_anything(self, tmp_path: Path) -> None:
        root = _build_root(tmp_path, env_local=NON_LOCAL_ENV)
        bin_dir, calls = _stub_docker(tmp_path)

        result = _run(root, bin_dir)  # no --force, no TTY, non-local endpoint

        assert result.returncode != 0
        assert not calls.exists()
        assert (root / ".env.local").exists(), ".env.local must survive a refused run"
        assert not (root / "bootstrap-ran").exists()


class TestScopeGuards:
    """Guards the Starter added on top of D-018 (2026-10-09)."""

    def test_the_volumes_are_listed_before_anything_is_deleted(self, tmp_path: Path) -> None:
        root = _build_root(tmp_path, env_local=LOCAL_ENV)
        bin_dir, calls = _stub_docker(
            tmp_path, volumes=("fixture_supabase-db", "fixture_redis-data")
        )

        result = _run(root, bin_dir, "--force")

        assert result.returncode == 0, result.stdout + result.stderr
        assert "fixture_supabase-db" in result.stdout
        assert "fixture_redis-data" in result.stdout
        logged = calls.read_text(encoding="utf-8").splitlines()
        listing = next(i for i, line in enumerate(logged) if line.startswith("volume ls"))
        teardown = next(i for i, line in enumerate(logged) if " down " in f" {line} ")
        assert listing < teardown
        assert "label=com.docker.compose.project=fixture" in logged[listing]

    def test_an_unlistable_stack_is_refused(self, tmp_path: Path) -> None:
        """If it cannot show what it would delete, it does not delete."""
        root = _build_root(tmp_path, env_local=LOCAL_ENV)
        bin_dir, calls = _stub_docker(tmp_path, volume_ls_fails=True)

        result = _run(root, bin_dir, "--force")

        assert result.returncode != 0
        assert "could not list the volumes" in result.stderr
        assert " down " not in f" {calls.read_text(encoding='utf-8')} "
        assert (root / ".env.local").exists()
        assert not (root / "bootstrap-ran").exists()

    def test_a_compose_file_without_a_project_name_is_refused(self, tmp_path: Path) -> None:
        """Without `name:` the project is named after a directory, and so are its volumes."""
        root = _build_root(tmp_path, env_local=LOCAL_ENV)
        (root / "local" / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
        bin_dir, calls = _stub_docker(tmp_path)

        result = _run(root, bin_dir, "--force")

        assert result.returncode != 0
        assert not calls.exists()

    def test_a_linked_worktree_is_refused_even_with_force(self, tmp_path: Path) -> None:
        """A worktree shares the main checkout's compose project and volumes."""
        git = shutil.which("git")
        if git is None:
            pytest.skip("git is not available")
        main = _build_root(tmp_path, env_local=LOCAL_ENV)
        ident = ["-c", "user.email=t@example.invalid", "-c", "user.name=t"]
        for argv in (["init", "-q"], [*ident, "add", "-A"], [*ident, "commit", "-q", "-m", "x"]):
            subprocess.run([git, *argv], cwd=main, check=True, capture_output=True)  # noqa: S603
        worktree = tmp_path / "worktree"
        subprocess.run(  # noqa: S603 -- fixed argv, absolute binary
            [git, "worktree", "add", "-q", str(worktree)],
            cwd=main,
            check=True,
            capture_output=True,
        )
        bin_dir, calls = _stub_docker(tmp_path)

        result = _run(worktree, bin_dir, "--force")

        assert result.returncode != 0
        assert "linked git worktree" in result.stderr
        assert not calls.exists(), "nothing, not even docker context, runs in a worktree"
