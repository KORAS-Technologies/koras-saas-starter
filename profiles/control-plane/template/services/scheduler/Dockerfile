FROM python:3.12-slim
WORKDIR /app
RUN pip install uv
COPY pyproject.toml .
RUN uv sync --no-dev
COPY koras_scheduler/ ./koras_scheduler/
CMD ["uv", "run", "python", "-m", "koras_scheduler.main"]
