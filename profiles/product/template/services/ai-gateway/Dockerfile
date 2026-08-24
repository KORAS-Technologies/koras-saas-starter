FROM python:3.12-slim

WORKDIR /app

RUN pip install uv

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
COPY services/ai-gateway/pyproject.toml ./services/ai-gateway/

# Ahead of the source copy, so editing the service does not resync every
# dependency. Run from the member directory: uv finds the workspace root
# above it and syncs this member against it.
RUN cd services/ai-gateway && uv sync --no-dev

COPY services/ai-gateway/koras_ai_gateway/ ./services/ai-gateway/koras_ai_gateway/
COPY services/ai-gateway/litellm_config.yaml ./services/ai-gateway/litellm_config.yaml

WORKDIR /app/services/ai-gateway

CMD ["uv", "run", "python", "-m", "koras_ai_gateway.main"]
