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
COPY services/worker/pyproject.toml ./services/worker/

# The root pyproject names the API in its dev group and points that dependency
# at the workspace, so uv refuses to read the root manifest at all unless
# services/api resolves to a member it can find -- `--no-dev` skips installing
# the group, not parsing it. The API's manifest alone satisfies that; no API
# source is copied and nothing from it is installed into this image.
COPY services/api/pyproject.toml ./services/api/

# Ahead of the source copy, so editing the service does not resync every
# dependency. Run from the member directory: uv finds the workspace root
# above it and syncs this member against it.
RUN cd services/worker && uv sync --no-dev

COPY services/worker/koras_worker/ ./services/worker/koras_worker/

WORKDIR /app/services/worker

CMD ["uv", "run", "python", "-m", "koras_worker.main"]
