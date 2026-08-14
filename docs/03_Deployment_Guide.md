# 🚀 Deployment Guide & Hosting Options

This guide covers step-by-step options to deploy **RankLLMs Engine** to production environments.

---

## 📌 Deployment Checklist

Before deploying to any platform:
1. Ensure your Neon PostgreSQL database URL is set: `DATABASE_URL=postgresql://...neon.tech/neondb?sslmode=require`
2. Set `DEBUG=False` in production.
3. Set a strong `SECRET_KEY`.
4. Ensure `ARTIFICIAL_ANALYSIS_API_KEY` is added to your production environment.

---

## Option A: Render Deployment (Recommended - PaaS)

Render is one of the easiest platforms to host Django applications.

### Step 1: Create a `render.yaml` or Web Service
In the Render Dashboard:
1. Click **New +** -> **Web Service**.
2. Connect your GitHub repository: `https://github.com/Luckyyaduvanshiofficial/rankllms-engine.git`.
3. Set build configuration:
   - **Environment**: Python 3
   - **Build Command**: `pip install -r requirements.txt && python manage.py migrate && python manage.py sync_all`
   - **Start Command**: `gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --workers 3`

### Step 2: Set Environment Variables on Render
Add the following key-value pairs under **Environment**:
```env
DEBUG=False
SECRET_KEY=your-super-secret-production-key
DATABASE_URL=postgresql://user:password@ep-sample-123.neon.tech/neondb?sslmode=require
ARTIFICIAL_ANALYSIS_API_URL=https://artificialanalysis.ai/api/v2
ARTIFICIAL_ANALYSIS_API_KEY=aa_DtsFXIHlTbHDWSJdfhNFKjlZfHKnAeBk
```

---

## Option B: Railway Deployment

1. Go to [Railway.app](https://railway.app) and create a **New Project**.
2. Select **Deploy from GitHub repo** and select `rankllms-engine`.
3. Railway automatically detects `requirements.txt` and `Procfile`.
4. Set Environment Variables (`DATABASE_URL`, `SECRET_KEY`, `ARTIFICIAL_ANALYSIS_API_KEY`).
5. Click **Deploy**.

---

## Option C: VPS Deployment (Hostinger / DigitalOcean / AWS EC2)

Deploying on a Linux Virtual Private Server (Ubuntu 22.04 LTS / 24.04 LTS).

### Step 1: SSH into VPS & Install Dependencies
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install python3-pip python3-venv nginx git -y
```

### Step 2: Clone Codebase & Install Requirements
```bash
cd /var/www
sudo git clone https://github.com/Luckyyaduvanshiofficial/rankllms-engine.git
cd rankllms-engine

python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt gunicorn
```

### Step 3: Configure `.env` File
```bash
cp .env.example .env
nano .env
```
Fill in production `DATABASE_URL`, `SECRET_KEY`, `DEBUG=False`.

### Step 4: Run Migrations & Initial Sync
```bash
python manage.py migrate
python manage.py sync_all
```

### Step 5: Setup Systemd Service for Gunicorn
Create `/etc/systemd/system/rankllms.service`:
```ini
[Unit]
Description=RankLLMs Engine Gunicorn Service
After=network.target

[Service]
User=root
WorkingDirectory=/var/www/rankllms-engine
ExecStart=/var/www/rankllms-engine/venv/bin/gunicorn --workers 3 --bind 127.0.0.1:8000 config.wsgi:application
Restart=always

[Install]
WantedBy=multi-user.target
```
Enable and start service:
```bash
sudo systemctl daemon-reload
sudo systemctl enable rankllms
sudo systemctl start rankllms
```

### Step 6: Configure Nginx Reverse Proxy
Create `/etc/nginx/sites-available/rankllms`:
```nginx
server {
    listen 80;
    server_name api.rankllms.com;  # Replace with your domain or IP

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```
Activate and reload Nginx:
```bash
sudo ln -s /etc/nginx/sites-available/rankllms /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

---

## Option D: Docker & Docker Compose Deployment

If you prefer containerized deployment, Dockerfiles are provided in the repo.

### `Dockerfile`
```dockerfile
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY . .

EXPOSE 8000

CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "3", "config.wsgi:application"]
```

### `docker-compose.yml`
```yaml
version: '3.8'

services:
  engine:
    build: .
    container_name: rankllms_engine
    restart: always
    ports:
      - "8000:8000"
    env_file:
      - .env
    command: >
      sh -c "python manage.py migrate &&
             python manage.py sync_all &&
             gunicorn --bind 0.0.0.0:8000 --workers 3 config.wsgi:application"
```

To run with Docker:
```bash
docker-compose up -d --build
```
