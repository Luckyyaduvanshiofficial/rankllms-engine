FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libpq-dev \
        gcc \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

COPY . .

RUN chmod +x entrypoint.sh

# No EXPOSE: Dokku injects $PORT (default 5000) and proxies 80/443 → $PORT.
# If you prefer a fixed port, EXPOSE it and run:
#   dokku ports:set <app> http:80:8000 https:443:8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f "http://localhost:${PORT:-5000}/" || exit 1

CMD ["./entrypoint.sh"]
