# Bot image (VPS). The scanner runs locally, not in Docker.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# NudeNet -> onnxruntime + opencv need these shared libraries.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY core ./core
COPY bot ./bot
COPY scanner ./scanner
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini
COPY config ./config

RUN pip install --upgrade pip && pip install ".[nsfw]"

# Warm the NudeNet model into the image so the first check is not slow.
RUN python -c "from nudenet import NudeDetector; NudeDetector()" || true

# Migrations first, then the bot.
CMD ["sh", "-c", "alembic upgrade head && python -m bot.main"]
