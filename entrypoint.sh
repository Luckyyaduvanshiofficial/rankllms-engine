#!/bin/bash
set -e

# Dokku sets PORT (default 5000). Bind 0.0.0.0 so the proxy can reach us.
PORT="${PORT:-5000}"

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
