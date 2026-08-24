FROM python:3.12-slim
WORKDIR /app
RUN pip install uv
COPY pyproject.toml .
RUN uv sync --no-dev
COPY koras_ai_gateway/ ./koras_ai_gateway/
COPY litellm_config.yaml .
CMD ["uv", "run", "python", "-m", "koras_ai_gateway.main"]
