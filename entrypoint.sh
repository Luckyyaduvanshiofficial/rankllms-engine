#!/bin/bash
set -e

# Dokploy proxies to the port set in the app UI (this project: 8000).
# Honor $PORT if Dokploy injects it; otherwise bind 8000.
PORT="${PORT:-8000}"

echo ">>> PORT=${PORT}"

echo ">>> Running migrations..."
python manage.py migrate --noinput

echo ">>> Collecting static files..."
python manage.py collectstatic --noinput

echo ">>> Starting Gunicorn on 0.0.0.0:${PORT}..."
exec gunicorn config.wsgi:application \
    --bind "0.0.0.0:${PORT}" \
    --workers 2 \
    --threads 2 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile -
