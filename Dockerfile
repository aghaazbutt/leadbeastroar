FROM python:3.12-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential \
      libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 \
      libcairo2 fonts-liberation \
      curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src/ ./src/

RUN pip install --upgrade pip && \
    pip install -e ".[dev]"

COPY alembic.ini ./
COPY migrations/ ./migrations/
COPY seeds/ ./seeds/

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && exec uvicorn leadbeast.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
