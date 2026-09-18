#!/bin/bash
set -e

echo ">>> Running migrations..."
python manage.py migrate --noinput

echo ">>> Collecting static files..."
python manage.py collectstatic --noinput

echo ">>> Starting Gunicorn..."
exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers 3 \
    --threads 2 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile -
