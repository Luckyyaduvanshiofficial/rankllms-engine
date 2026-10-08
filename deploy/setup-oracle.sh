#!/bin/bash
set -e

echo "=== RankLLMs Engine — Oracle Cloud Setup ==="

# 1. System packages
apt-get update && apt-get install -y docker.io docker-compose nginx certbot python3-certbot-nginx
systemctl enable docker nginx

# 2. Firewall (Oracle Cloud already has security lists, this adds UFW)
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

# 3. Clone the repo
cd /opt
git clone https://github.com/Luckyyaduvanshiofficial/rankllms-engine.git
cd rankllms-engine

# 4. Prompt for env vars
echo ""
echo "Enter your Neon DATABASE_URL (e.g. postgresql://user:pass@host/neondb?sslmode=require):"
read DATABASE_URL

echo "Enter your SECRET_KEY (run: python3 -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key)'):"
read SECRET_KEY

echo "Enter the public hostname (for example api.rankllms.com):"
read PUBLIC_HOST

echo "Enter ARTIFICIAL_ANALYSIS_API_KEY:"
read -r -s ARTIFICIAL_ANALYSIS_API_KEY
printf '\n'

echo "Enter OPENROUTER_API_KEY (optional; needed for OpenRouter Data API snapshots):"
read -r -s OPENROUTER_API_KEY
printf '\n'

cat > .env <<EOF
DATABASE_URL=${DATABASE_URL}
SECRET_KEY=${SECRET_KEY}
DEBUG=False
ALLOWED_HOSTS=${PUBLIC_HOST},localhost,127.0.0.1
CORS_ALLOWED_ORIGINS=https://rankllms.com,https://www.rankllms.com,https://api.rankllms.com
CSRF_TRUSTED_ORIGINS=https://${PUBLIC_HOST}
ARTIFICIAL_ANALYSIS_API_URL=https://artificialanalysis.ai/api/v2
ARTIFICIAL_ANALYSIS_API_KEY=${ARTIFICIAL_ANALYSIS_API_KEY}
ARTIFICIAL_ANALYSIS_MODELS_PATH=language/models/free
OPENROUTER_API_KEY=${OPENROUTER_API_KEY}
MODELS_DEV_API_URL=https://models.dev/api.json

# The 6-hourly sync runs in-process; with multiple gunicorn workers each would
# run its own copy, so it stays off and sync_all is invoked on a cron/timer.
ENABLE_SCHEDULER=false
RUN_MIGRATIONS=true
RUN_INITIAL_SYNC=false
EOF

# 5. Build and run with Neon DB (no local postgres)
docker compose up -d --build

# 6. Run migrations + initial sync
docker compose exec web python manage.py migrate --noinput
docker compose exec web python manage.py sync_all

# 7. Nginx reverse proxy
cp deploy/oracle-nginx.conf /etc/nginx/sites-available/rankllms
ln -sf /etc/nginx/sites-available/rankllms /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

echo ""
echo "=== DONE — API live at http://YOUR_VM_IP ==="
echo "Run 'certbot --nginx' for HTTPS (optional)"
