# 🚀 Deployment Guide & Hosting Options

This guide covers step-by-step options to deploy **RankLLMs Engine** to production environments.

---

## 📌 Deployment Checklist

Before deploying to any platform:
1. Set a PostgreSQL `DATABASE_URL` (Neon is supported). Local development can use SQLite.
2. Set `DEBUG=False` in production.
3. Set a strong `SECRET_KEY`.
4. Add `ARTIFICIAL_ANALYSIS_API_KEY` and `OPENROUTER_API_KEY` as server-side secrets when those source datasets are enabled.
5. Set explicit `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, and `CSRF_TRUSTED_ORIGINS`; never use `ALLOWED_HOSTS=*`.

---

## Option A: Render Deployment (Recommended - PaaS)

Render is one of the easiest platforms to host Django applications.

The repository includes a `render.yaml` Blueprint for a native Python web service. It installs dependencies, collects static files, runs migrations at startup, and configures `/ping` as the health check.

### Step 1: Connect the Blueprint
1. Push this repository to GitHub.
2. In the Render Dashboard, click **New +** -> **Blueprint** and select the repository.
3. Review and apply the Blueprint. It will create the `rankllms-engine` web service.

### Step 2: Configure required environment variables
Render generates `SECRET_KEY` and sets production `DEBUG`, explicit `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS`, and the six-hour scheduler from the Blueprint. The host allowlist includes `api.rankllms.com` and `rankllms-engine-kqso.onrender.com`; edit the Blueprint if Render assigns a different service hostname. During creation, provide:

- `DATABASE_URL`: a PostgreSQL connection string (Neon is supported; include `sslmode=require`).
- `ARTIFICIAL_ANALYSIS_API_KEY`: needed for AA sync. The default endpoint is the public Free-tier `language/models/free`; Pro access can select `language/models` with `ARTIFICIAL_ANALYSIS_MODELS_PATH`.
- `OPENROUTER_API_KEY`: needed for OpenRouter benchmarks and Data API datasets. The public model catalog works without it.

After the first deploy, create a staff account from the service's **Shell** with `python manage.py createsuperuser`, sign in at `/admin/`, and run the first import at `/settings/data-sync/`. The Blueprint leaves `RUN_INITIAL_SYNC=false` so a slow source does not block startup. Later syncs are scheduled every six hours while the Render instance is awake. Free Render instances sleep when idle; use a Cron Job or an always-on instance for uninterrupted scheduling.

### Custom domain behind Cloudflare

For `api.rankllms.com`, set a Render custom domain and point the Cloudflare DNS record at the Render hostname. Django validates the original `Host` against `ALLOWED_HOSTS`; both the API hostname and Render hostname are explicitly listed. TLS terminates at Cloudflare/Render, and `SECURE_PROXY_SSL_HEADER` honors the forwarded HTTPS protocol. `USE_X_FORWARDED_HOST` stays disabled so a forwarded host cannot bypass Django's host validation. The previous 400 was caused by the Blueprint allowlist containing only `.onrender.com`, which rejected `api.rankllms.com`.

> The Blueprint uses Render's free web plan to avoid creating a paid resource by default. Free instances spin down when idle and have an ephemeral filesystem, so keep application data in PostgreSQL and expect cold starts. Choose a paid instance in Render if you need always-on service.

### Step 3: Choose service availability
Free instances spin down after a period without traffic and may take a little time to start on the next request. An external uptime monitor does not provide an always-on guarantee. Select a paid instance in Render when you need the service to remain available without cold starts.

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
sudo useradd --system --create-home --shell /usr/sbin/nologin rankllms
sudo chown -R rankllms:rankllms /var/www/rankllms-engine
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
Also set explicit `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, and `CSRF_TRUSTED_ORIGINS`; do not use `*`. Restrict the file to the service user: `chmod 600 .env`.

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
User=rankllms
WorkingDirectory=/var/www/rankllms-engine
EnvironmentFile=/var/www/rankllms-engine/.env
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

Use the repository's actual hardened `Dockerfile` and `docker-compose.yml`. `.env` is excluded from the image and loaded by Compose at runtime. Set production hosts/origins, `DEBUG=False`, a strong `SECRET_KEY`, and database/source credentials in `.env` or a secret manager.

```bash
docker compose up -d --build
docker compose exec web python manage.py createsuperuser
```

The entrypoint waits for PostgreSQL, runs migrations, collects static files, and starts Gunicorn. Set `RUN_INITIAL_SYNC=false` in production and run the first import from the staff Settings page, or use `docker compose exec web python manage.py sync_all`.
