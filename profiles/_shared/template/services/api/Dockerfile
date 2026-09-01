FROM python:3.12-slim

WORKDIR /app

RUN pip install uv

# Pin where uv puts the environment, and put it on PATH. fly.toml may override
# the CMD below with a [processes] entry, and those run the bare command -- a
# `python -m ...` that resolves to the system interpreter finds none of the
# dependencies uv just installed. That failure looks like a missing dependency
# rather than a missing PATH, and the dependency is right there in pyproject.
ENV UV_PROJECT_ENVIRONMENT=/app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Built from the repository root, not from this directory. The service
# depends on the shared packages in python-packages/ as uv workspace
# members, so uv cannot resolve it without the workspace root and those
# members present -- a context of this directory alone fails on the first
# `workspace = true` entry it reads.
# uv.lock is a wildcard because a freshly generated project has not
# resolved one yet. A non-matching wildcard is tolerated only because
# pyproject.toml on the same line always matches.
COPY pyproject.toml uv.lock* ./
COPY python-packages/ ./python-packages/
COPY services/api/pyproject.toml ./services/api/

# Ahead of the source copy, so editing the service does not resync every
# dependency. Run from the member directory: uv finds the workspace root
# above it and syncs this member against it.
RUN cd services/api && uv sync --no-dev

COPY services/api/koras_api/ ./services/api/koras_api/

# The workspace members again, now that their sources are here.
#
# The sync above runs before any source is copied, so it installs third-party
# dependencies and leaves every local member -- this service and the shared
# python-packages -- installed from a manifest with nothing behind it. This
# second sync completes them, in the image, where the cost is paid once.
RUN cd services/api && uv sync --no-dev

WORKDIR /app/services/api

# The venv directly, so `uv` is not on the runtime path at all.
#
# On Fly on 2026-08-30 a machine spent two minutes on `Building koras-audit ...
# Built koras-database` for eleven packages *after* `Preparing to run` and
# before the server process existed -- longer than the deploy pipeline's
# health-check budget, so a service that would have come up was reported as one
# that never became healthy.
#
# What triggered the resync there is not established: the same image built and
# run locally, from this Dockerfile and from the previous one, rebuilt nothing.
# So this is not a fix for a reproduced trigger. It removes the mechanism --
# `uv run` synchronises the environment before it execs, and nothing else in
# the container can rebuild anything. A cause that cannot be reached does not
# need to be understood first.
#
# It also removes the `uv` parent from the process tree, so the server is a
# direct child of Fly's init and receives Fly's signals on shutdown rather than
# depending on `uv` to forward them.
#
# This said "puts the process at PID 1 ... Measured: PID 10 before, PID 1 now",
# and PID 1 is not what a Fly machine shows. `/fly/init` is PID 1 there, always;
# the server is its child. Checked on a deployed machine on 2026-09-01, where
# `/proc` lists `/app/.venv/bin/python /app/.venv/bin/uvicorn ...` and no `uv`
# anywhere. The benefit is real and the number was wrong -- corrected rather
# than deleted, because a measurement nobody can reproduce is worse than none.
#
# /app/.venv/bin is already on PATH for the reason given at the top of this
# file, so the bare command resolves there.
CMD ["uvicorn", "koras_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
