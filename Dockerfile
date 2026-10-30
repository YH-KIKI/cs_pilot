FROM node:24-bookworm-slim AS frontend
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run typecheck && npm run build

FROM python:3.12-slim-bookworm AS python-build
COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-cache
COPY app ./app
COPY scripts ./scripts
COPY data/orders ./data/orders
COPY artifacts ./artifacts
# Restore the frozen vectors locally; neither build nor startup needs an API key.
RUN .venv/bin/python -m scripts.start --prepare-only

FROM python:3.12-slim-bookworm
WORKDIR /app
COPY --from=python-build /app /app
COPY --from=frontend /frontend/dist /app/app/static
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["python", "-m", "scripts.start"]
