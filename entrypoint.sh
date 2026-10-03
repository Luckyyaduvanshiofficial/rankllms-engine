#!/bin/bash
set -e

# Dokploy proxies to the port set in the app UI (this project: 8000).
# Honor $PORT if Dokploy injects it; otherwise bind 8000.
PORT="${PORT:-8000}"

echo ">>> PORT=${PORT}"

# The 6-hourly catalog sync is opt-in (ENABLE_SCHEDULER). It is off
# by default because gunicorn forks one worker per process and each
# would otherwise run its own copy; the scheduler takes a file lock
# so only one worker owns it when enabled.
ENABLE_SCHEDULER="${ENABLE_SCHEDULER:-false}"
SYNC_INTERVAL_HOURS="${SYNC_INTERVAL_HOURS:-6}"
# Seed the catalog on boot so a fresh deploy serves data immediately
# (the scheduler alone would leave an empty catalog until its first
# 6-hour tick). Disable when a separate job or cron handles ingestion.
RUN_INITIAL_SYNC="${RUN_INITIAL_SYNC:-true}"
export ENABLE_SCHEDULER SYNC_INTERVAL_HOURS RUN_INITIAL_SYNC

# Gunicorn workers scale with available CPUs, not a fixed 2. A hardcoded count
# ignores the container's CPU limit and under-uses bigger hosts.
WEB_CONCURRENCY="${WEB_CONCURRENCY:-}"
if [ -z "$WEB_CONCURRENCY" ]; then
  WEB_CONCURRENCY="$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 2)"
  # Keep a floor so a 1-CPU container still gets 2 workers (sync + requests).
  [ "$WEB_CONCURRENCY" -lt 2 ] && WEB_CONCURRENCY=2
  # And a sane ceiling so a 64-core host doesn't spawn 64 Postgres clients.
  [ "$WEB_CONCURRENCY" -gt 8 ] && WEB_CONCURRENCY=8
fi
export WEB_CONCURRENCY

# Migrations touch the database and can race a rolling deploy, so only one
# container should run them. Deployments that scale to >1 replica should set
# RUN_MIGRATIONS=false on the replicas and run them once as a job.
RUN_MIGRATIONS="${RUN_MIGRATIONS:-true}"

wait_for_db() {
  echo ">>> Waiting for database..."
  DJANGO_SETTINGS_MODULE=config.settings python - <<'PY'
import sys
import time

import django

django.setup()

from django.db import connection
from django.db.utils import OperationalError

# Neon and most managed Postgres can accept the connection a moment before it
# is ready to serve queries. Retry briefly instead of crash-looping.
for attempt in range(1, 11):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        print(">>> Database reachable")
        sys.exit(0)
    except OperationalError as exc:
        if attempt == 10:
            print(f">>> Database still unreachable after {attempt} tries: {exc}")
            sys.exit(1)
        time.sleep(2)

sys.exit(1)
PY
}

if [ "$RUN_MIGRATIONS" = "true" ]; then
  wait_for_db
  echo ">>> Running migrations..."
  python manage.py migrate --noinput
else
  echo ">>> Skipping migrations (RUN_MIGRATIONS=${RUN_MIGRATIONS})"
fi

echo ">>> Collecting static files..."
python manage.py collectstatic --noinput --clear

# The deployment guide's build step runs `sync_all` before serving, so a
# fresh deploy has data on first load. The in-process scheduler only
# fires every SYNC_INTERVAL_HOURS (and is off by default), so without
# this a brand-new deploy would serve an empty catalog until the first
# manual sync. Skippable with RUN_INITIAL_SYNC=false, e.g. when a
# separate job or a cron handles ingestion.
if [ "$RUN_INITIAL_SYNC" = "true" ]; then
  echo ">>> Running initial catalog sync..."
  python manage.py sync_all || echo ">>> WARNING: initial sync failed; serving existing data."
else
  echo ">>> Skipping initial sync (RUN_INITIAL_SYNC=${RUN_INITIAL_SYNC})"
fi

echo ">>> Starting Gunicorn on 0.0.0.0:${PORT} (workers=${WEB_CONCURRENCY})..."
exec gunicorn config.wsgi:application \
    --bind "0.0.0.0:${PORT}" \
    --workers "${WEB_CONCURRENCY}" \
    --threads "${GUNICORN_THREADS:-4}" \
    --timeout "${GUNICORN_TIMEOUT:-120}" \
    --graceful-timeout "${GUNICORN_GRACEFUL_TIMEOUT:-30}" \
    --keep-alive "${GUNICORN_KEEPALIVE:-5}" \
    --max-requests "${GUNICORN_MAX_REQUESTS:-1000}" \
    --max-requests-jitter "${GUNICORN_MAX_REQUESTS_JITTER:-100}" \
    --access-logfile - \
    --error-logfile -
