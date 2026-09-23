# RankLLMs Engine — Free AI Model Leaderboard & Benchmark API

> **Open-source, free LLM leaderboard data API** for rankings, pricing, and benchmarks across 8000+ AI models.
> Powers **[rankllms.com](https://rankllms.com)** · Built by **[CodaiPro](https://codaipro.com)** · Free for everyone.

[![Python 3.12+](https://img.shields.io/badge/Python-3.12+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Django 6.0](https://img.shields.io/badge/Django-6.0-092E20?style=for-the-badge&logo=django&logoColor=white)](https://www.djangoproject.com/)
[![Django Ninja](https://img.shields.io/badge/Django_Ninja-REST_API-C01A29?style=for-the-badge&logo=fastapi&logoColor=white)](https://django-ninja.dev/)
[![Neon Postgres](https://img.shields.io/badge/Neon-PostgreSQL-00E599?style=for-the-badge&logo=postgresql&logoColor=white)](https://neon.tech/)
[![MIT License](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)](LICENSE)

---

## 🌟 Overview

**RankLLMs Engine** is a production-ready, **free** backend that aggregates, normalizes, scores, and ranks **AI models** — LLMs, image, video, and audio models — across **120+ providers** (OpenAI, Anthropic, Google, Meta, DeepSeek, Qwen, Mistral, and more).

It serves high-speed REST APIs for:

- 🏆 **AI model leaderboards** (intelligence, coding, agentic, open-weight)
- 📊 **Benchmark matrices** (GPQA, SWE-bench, Tau-bench, Artificial Analysis, Design Arena)
- ⚖️ **Side-by-side model comparison** (specs, pricing, context, scores)
- 🎴 **Top 200 model cards** (JSON / TypeScript export)
- 📈 **Token usage & task market-share** analytics

**No API key required** for core read endpoints. Free forever for individuals and production apps.

### Live product & docs

| Resource | Link |
| :--- | :--- |
| 🌐 Main site | [https://rankllms.com](https://rankllms.com) |
| 🛠️ This engine (API) | [https://api.rankllms.com](https://api.rankllms.com) |
| 📖 Swagger / OpenAPI | [https://api.rankllms.com/api/v1/docs](https://api.rankllms.com/api/v1/docs) |
| 👨‍💻 CodaiPro | [https://codaipro.com](https://codaipro.com) |
| 📘 User guide (free API) | [USER_GUIDE.md](USER_GUIDE.md) |

---

## 📚 Documentation Index

- 📘 **[User Guide — Free API Usage](USER_GUIDE.md)** — How to call the free leaderboard API with curl, Python, and JS.
- 🌟 **[About RankLLMs & Project Overview](docs/01_Aboutus.md)** — Mission, architecture, scoring methodology, API overview.
- 🏗️ **[Architecture & Data Schema](docs/01_Architecture.md)** — Core models, data flow, OpenRouter / Artificial Analysis / models.dev ingestion.
- 🔌 **[API Reference Guide](docs/02_API_Reference.md)** — REST endpoints, query parameters, JSON examples.
- 🚀 **[Deployment Guide](docs/03_Deployment_Guide.md)** — Render, Railway, VPS, Docker, Cloudflare.
- 💻 **[Local Development Guide](docs/04_Local_Development.md)** — Local setup, env vars, migrations, sync commands.
- 🤖 **[AI Agent Guide](docs/00_AI_AGENT_GUIDE.md)** — Machine-readable integration for agents and LLM routers.

---

## ⚡ Quick Start (Local Setup)

### 1. Clone & Setup Virtual Environment

```bash
git clone https://github.com/Luckyyaduvanshiofficial/rankllms-engine.git
cd rankllms-engine

python -m venv venv
# Windows:
.\venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

pip install -r requirements.txt
```

### 2. Configure Environment Variables

Copy `.env.example` to `.env` and add your database credentials:

```env
DEBUG=True
SECRET_KEY=your-secret-key-here
DATABASE_URL=postgresql://user:password@your-host.neon.tech/neondb?sslmode=require
ARTIFICIAL_ANALYSIS_API_URL=https://artificialanalysis.ai/api/v2
ARTIFICIAL_ANALYSIS_API_KEY=your-artificial-analysis-api-key-here
MODELS_DEV_API_URL=https://models.dev/api.json
```

### 3. Run Migrations & Master Data Pipeline

```bash
python manage.py migrate

# Ingests OpenRouter catalog + models.dev catalog + Artificial Analysis benchmarks + null backfill
python manage.py sync_all
```

### 4. Start Development Server

```bash
python manage.py runserver
```

Open **`http://127.0.0.1:8000/`** for the docs portal, or **`http://127.0.0.1:8000/api/v1/docs`** for Swagger.

---

## 🔄 Automated Data Pipeline

APScheduler runs `sync_all` every **6 hours**. Trigger manually:

```bash
python manage.py sync_all
```

```bash
curl -X POST "http://localhost:8000/api/v1/sync"
```

**Pipeline sources:**

1. **OpenRouter** — model catalog, pricing, benchmarks, app rankings
2. **models.dev** — 8000+ models across 200+ providers (context, cost, capabilities)
3. **Artificial Analysis** — intelligence / coding / agentic indices & telemetry
4. **Null backfill** — fills missing specs, pricing, and fallback scores

---

## ⚙️ Environment Variables Reference

| Variable | Required | Description | Example |
| :--- | :---: | :--- | :--- |
| `DEBUG` | Optional | Enable Django debug mode | `True` / `False` |
| `SECRET_KEY` | **Yes** | Django secret key | `django-insecure-...` |
| `DATABASE_URL` | **Yes** | Neon PostgreSQL connection URI | `postgresql://...neon.tech/neondb?sslmode=require` |
| `ARTIFICIAL_ANALYSIS_API_URL` | Optional | Artificial Analysis base URL | `https://artificialanalysis.ai/api/v2` |
| `ARTIFICIAL_ANALYSIS_API_KEY` | **Yes** | Artificial Analysis API key | `your-key` |
| `MODELS_DEV_API_URL` | Optional | models.dev catalog JSON | `https://models.dev/api.json` |
| `OPENROUTER_API_URL` | Optional | OpenRouter models endpoint | `https://openrouter.ai/api/v1/models` |
| `OPENROUTER_API_KEY` | Optional | OpenRouter API key (if required) | `sk-or-...` |

---

## 🙏 Acknowledgments & Data Sources

RankLLMs Engine is free and open-source thanks to these projects and teams:

| Source | What we use | Link |
| :--- | :--- | :--- |
| **OpenRouter** | Model catalog, pricing, unified benchmarks, usage rankings | [openrouter.ai](https://openrouter.ai) |
| **Artificial Analysis** | Intelligence, coding, agentic indices & model telemetry | [artificialanalysis.ai](https://artificialanalysis.ai) |
| **models.dev** | Provider + model metadata (context, cost, capabilities) | [models.dev](https://models.dev) |
| **RankLLMs** | Product, leaderboards, and community | [rankllms.com](https://rankllms.com) |
| **CodaiPro** | Engineering, hosting, and open-source sponsorship | [codaipro.com](https://codaipro.com) |

Also built with [Django](https://www.djangoproject.com/), [Django Ninja](https://django-ninja.dev/), and [Neon](https://neon.tech/).

---

## 📜 License & Credits

Built for **[RankLLMs](https://rankllms.com)** by **[CodaiPro](https://codaipro.com)**. Open-sourced under the **MIT License**.

**Keywords:** AI leaderboard API, LLM rankings, model comparison API, free benchmark API, OpenRouter data, Artificial Analysis scores, models.dev, open-weight models, SWE-bench leaderboard, RankLLMs.
