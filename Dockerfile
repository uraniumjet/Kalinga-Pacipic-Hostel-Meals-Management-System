# syntax=docker/dockerfile:1
# Build:  docker build -t hostel-meals .
# Run:    see docker-compose.yml and docs/deployment.md

FROM python:3.13-slim AS builder
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
WORKDIR /build
COPY requirements.txt requirements-prod.txt ./
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install -r requirements-prod.txt

FROM python:3.13-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    DJANGO_DEBUG=0 \
    DJANGO_STATIC_ROOT=/app/staticfiles \
    DJANGO_MEDIA_ROOT=/data/media \
    DJANGO_IMPORT_STAGING_DIR=/data/import_staging \
    SQLITE_PATH=/data/db.sqlite3

# A fixed unprivileged user; /data is the only place the app writes to.
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app \
    && mkdir -p /app /data/media /data/import_staging \
    && chown -R app:app /app /data

COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
COPY --chown=app:app . .
RUN chmod +x docker/entrypoint.sh

USER app
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz/', timeout=4).status == 200 else 1)"

ENTRYPOINT ["docker/entrypoint.sh"]
CMD ["gunicorn", "backend.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--access-logfile", "-", "--error-logfile", "-"]
