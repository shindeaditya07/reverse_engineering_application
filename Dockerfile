FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY services ./services
ARG GIT_SHA=unknown
ENV GIT_SHA=${GIT_SHA}
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "services.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
