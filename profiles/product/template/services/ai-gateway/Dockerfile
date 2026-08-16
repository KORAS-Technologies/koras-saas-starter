FROM python:3.12-slim
WORKDIR /app
RUN pip install uv
COPY pyproject.toml .
RUN uv sync --no-dev
COPY src/ ./src/
COPY litellm_config.yaml .
CMD ["uv", "run", "python", "-m", "src.main"]
