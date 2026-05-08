# syntax=docker/dockerfile:1.7
# ----------------------------------------------------------------------------
# Builder: устанавливаем зависимости в .venv через poetry
# ----------------------------------------------------------------------------
FROM python:3.12-slim AS builder

ENV POETRY_VERSION=1.8.3 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=true \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN pip install "poetry==${POETRY_VERSION}"

COPY pyproject.toml poetry.lock* ./

RUN poetry install --only main --no-root --no-ansi

# ----------------------------------------------------------------------------
# Runtime: минимальный образ + ffmpeg (для конвертации .ogg голосовых) +
# libgomp1 (OpenMP runtime, нужен ctranslate2 → faster-whisper)
# ----------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    TZ=UTC

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY src/ ./src/
COPY alembic.ini ./

# UID for the in-container `bot` user. Default 1000 matches a fresh Ubuntu /
# Debian image. Some cloud images (e.g. Oracle's Ubuntu Cloud) put the default
# user at UID 1001 — pass `--build-arg BOT_UID=1001` (or whatever `id -u`
# returns on the host) so the container's bot user matches the host user that
# owns the mounted ./data volume. install.sh does this automatically.
ARG BOT_UID=1000
ARG BOT_GID=1000
RUN groupadd -g ${BOT_GID} bot \
    && useradd -m -u ${BOT_UID} -g ${BOT_GID} bot \
    && mkdir -p /data \
    && chown -R bot:bot /app /data
USER bot

CMD ["python", "-m", "src.main"]
