FROM python:3.12-slim
WORKDIR /app
RUN pip install uv
COPY pyproject.toml .
RUN uv sync --no-dev
COPY koras_worker/ ./koras_worker/
CMD ["uv", "run", "python", "-m", "koras_worker.main"]
