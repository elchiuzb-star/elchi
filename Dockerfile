FROM python:3.12-slim

# PYTHONPATH is set because `python scripts/foo.py` puts /app/scripts on
# sys.path, not /app, so the seed scripts cannot `import app`. uvicorn is
# unaffected either way, since it adds the working directory itself.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

WORKDIR /app

# curl is only here so the container healthcheck can hit /api/v1/health.
# psycopg is installed as [binary], so no libpq/build toolchain is needed.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY scripts ./scripts

# Non-root. storage/uploads is a mount point at runtime; creating it here
# gives the volume the right ownership on first start.
RUN useradd --create-home --uid 1000 elchi \
    && mkdir -p storage/uploads \
    && chown -R elchi:elchi /app
USER elchi

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/v1/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
