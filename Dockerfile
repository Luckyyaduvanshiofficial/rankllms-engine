# syntax=docker/dockerfile:1
#
# Django 6 requires Python >= 3.12.
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000 \
    DJANGO_SETTINGS_MODULE=config.settings

WORKDIR /app

# curl is kept because the HEALTHCHECK below uses it. Everything else that was
# here (libpq-dev, gcc) only existed to compile psycopg2, but requirements.txt
# pins psycopg2-binary, which ships prebuilt wheels. Dropping them removes a
# compiler and headers from the runtime image.
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Dependencies in their own layer: editing application code no longer
# invalidates the pip cache.
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy the app before collectstatic so the manifest step can see real files.
COPY . .

# Fail the build here rather than at first request if any referenced asset is
# missing from STATIC_ROOT.
RUN chmod +x entrypoint.sh && \
    SECRET_KEY=build-only-not-a-real-secret \
    python manage.py collectstatic --noinput --clear

# Drop root. The app only reads its own code and writes to staticfiles/.
RUN useradd --create-home --uid 1000 appuser && \
    chown -R appuser:appuser /app
USER appuser

# Dokploy Traefik must target this same port (app setting: Port = 8000).
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f "http://127.0.0.1:${PORT:-8000}/ping" || exit 1

CMD ["./entrypoint.sh"]
