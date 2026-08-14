# 🚀 RankLLMs Engine

> **High-Performance LLM & Multi-Modal Leaderboard Data API Engine**  
> Powered by **Django 6.0**, **Django Ninja (Pydantic v2)**, and **Neon PostgreSQL**.

[![Python 3.12+](https://img.shields.io/badge/Python-3.12+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Django 6.0](https://img.shields.io/badge/Django-6.0-092E20?style=for-the-badge&logo=django&logoColor=white)](https://www.djangoproject.com/)
[![Django Ninja](https://img.shields.io/badge/Django_Ninja-REST_API-C01A29?style=for-the-badge&logo=fastapi&logoColor=white)](https://django-ninja.dev/)
[![Neon Postgres](https://img.shields.io/badge/Neon-PostgreSQL-00E599?style=for-the-badge&logo=postgresql&logoColor=white)](https://neon.tech/)

---

## 🌟 Overview

**RankLLMs Engine** is a specialized, production-ready backend engine designed to aggregate, normalize, score, and rank **760+ AI models** (Large Language Models, Image Generation, Video Generation, and Audio/Speech models) across **120+ AI providers** (OpenAI, Anthropic, Google, Meta, DeepSeek, Qwen, Mistral, and more).

It powers high-speed REST APIs for leaderboards, token-usage app analytics, task classification market share, model comparisons, and real-time benchmark evaluation.

---

## 📚 Documentation Index

To keep documentation clean and easy to navigate, detailed guides are organized into separate files:

- 🏗️ **[Architecture & Data Schema](docs/01_Architecture.md)** — Core models, data flow, OpenRouter & Artificial Analysis ingestion pipelines.
- 🔌 **[API Reference Guide](docs/02_API_Reference.md)** — Complete list of REST API endpoints, query parameters, and JSON response examples.
- 🚀 **[Deployment Options & Guide](docs/03_Deployment_Guide.md)** — Deploying to Render, Railway, Hostinger VPS (Nginx + Gunicorn), Docker, or Cloudflare.
- 💻 **[Local Development Guide](docs/04_Local_Development.md)** — Local setup, environment variables, running migrations, and manual data sync commands.

---

## ⚡ Quick Start (Local Setup)

### 1. Clone & Setup Virtual Environment
```bash
git clone https://github.com/Luckyyaduvanshiofficial/rankllms-engine.git
cd rankllms-engine

python -m venv venv
# On Windows:
.\venv\Scripts\activate
# On Linux/macOS:
source venv/bin/activate

pip install -r requirements.txt
```

### 2. Configure Environment Variables
Copy `.env.example` to `.env` and add your database credentials and API key:
```env
DEBUG=True
SECRET_KEY=your-secret-key-here
DATABASE_URL=postgresql://user:password@ep-sample-123.neon.tech/neondb?sslmode=require
ARTIFICIAL_ANALYSIS_API_URL=https://artificialanalysis.ai/api/v2
ARTIFICIAL_ANALYSIS_API_KEY=aa_DtsFXIHlTbHDWSJdfhNFKjlZfHKnAeBk
```

### 3. Run Migrations & Master Data Pipeline
```bash
# Apply migrations to database
python manage.py migrate

# Run master data pipeline (Ingests OpenRouter catalog + Artificial Analysis benchmarks + Null backfill)
python manage.py sync_all
```

### 4. Start Development Server
```bash
python manage.py runserver
```
Visit **`http://127.0.0.1:8000/`** in your browser to access the **Interactive Tabbed Documentation Portal**, or **`http://127.0.0.1:8000/api/v1/docs`** for the Swagger REST API documentation.

---

## 🔄 Automated Data Pipeline

The engine includes an automated background scheduler (**APScheduler**) that periodically runs `sync_all` every **6 hours**.

You can also trigger sync manually via CLI or API:
```bash
# Terminal CLI Command
python manage.py sync_all
```
```bash
# REST API POST Trigger
curl -X POST "http://localhost:8000/api/v1/sync"
```

---

## ⚙️ Environment Variables Reference

| Variable | Required | Description | Example |
| :--- | :---: | :--- | :--- |
| `DEBUG` | Optional | Enable Django debug mode | `True` / `False` |
| `SECRET_KEY` | **Yes** | Django secret key | `django-insecure-...` |
| `DATABASE_URL` | **Yes** | Neon PostgreSQL connection URI | `postgresql://...neon.tech/neondb?sslmode=require` |
| `ARTIFICIAL_ANALYSIS_API_URL` | Optional | Artificial Analysis base URL | `https://artificialanalysis.ai/api/v2` |
| `ARTIFICIAL_ANALYSIS_API_KEY` | **Yes** | Artificial Analysis API Key | `aa_DtsFXIHl...` |

---

## 📜 License & Credits

Built for **RankLLMs** platform. Open-sourced under the MIT License.
