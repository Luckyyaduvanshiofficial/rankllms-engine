# RankLLMs Engine — Free AI Model Leaderboard & Benchmark API

> **Open-source, free AI model data API** for catalog metadata, source-attributed pricing, and independently published benchmarks.
> Powers **[rankllms.com](https://rankllms.com)** · Built by **[CodaiPro](https://codaipro.com)** · Free for everyone.

[![Python 3.12+](https://img.shields.io/badge/Python-3.12+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Django 6.x](https://img.shields.io/badge/Django-6.x-092E20?style=for-the-badge&logo=django&logoColor=white)](https://www.djangoproject.com/)
[![Django Ninja](https://img.shields.io/badge/Django_Ninja-REST_API-C01A29?style=for-the-badge&logo=fastapi&logoColor=white)](https://django-ninja.dev/)
[![Neon Postgres](https://img.shields.io/badge/Neon-PostgreSQL-00E599?style=for-the-badge&logo=postgresql&logoColor=white)](https://neon.tech/)
[![MIT License](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)](LICENSE)

---

## 🌟 Overview

**RankLLMs Engine** is a free Django application that ingests model catalogs, normalizes model identities, preserves source payloads, and publishes canonical model and ranking snapshots. Missing prices, capabilities, and benchmarks remain unknown; the pipeline does not estimate them from model names.

It serves high-speed REST APIs for:

- 🏆 **AI model leaderboards** (intelligence, coding, agentic, open-weight)
- 📊 **Benchmark matrices** (GPQA, SWE-bench, Tau-bench, Artificial Analysis, Design Arena)
- ⚖️ **Side-by-side model comparison** (specs, pricing, context, scores)
- 🎴 **Model cards** (JSON export)
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

Copy `.env.example` to `.env`, use a local SQLite database or add a PostgreSQL URL, and keep source keys server-side:

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

# Ingests enabled sources and rebuilds the canonical rankindex snapshot
python manage.py sync_all
```

### 4. Start Development Server

```bash
python manage.py runserver
```

Open **`http://127.0.0.1:8000/`** for the docs portal, or **`http://127.0.0.1:8000/api/v1/docs`** for Swagger.

---

## 🔄 Data pipeline and staff controls

The pipeline is **fetch → validate → normalize → match → merge → publish**. Source-specific rows remain available in `ormodels` / `orbench`, `aamodels` / `aabanch`, and `modelsdev`; `rankindex` is the canonical catalog consumed by the product-facing leaderboard and model catalog.

Render is configured to queue a sync every **6 hours while its instance is awake**. Free Render instances sleep while idle; use a paid instance or a Render Cron Job if a schedule must run continuously. The staff-only Settings page is at `/settings/data-sync/`. Create a Django staff account with `python manage.py createsuperuser`, sign in at `/admin/`, then open the Settings page.

Use the Settings page to sync all sources or one source, run a dry-run preview, toggle sources, and set bounded timeout/retry values. Dry run runs the same pipeline inside a database transaction and rolls back all writes. The old `fill_nulls` command is now a read-only completeness report; it does not invent data.

Command-line sync (for a trusted local shell or Render Shell):

```bash
python manage.py sync_all
```

`POST /api/v1/sync` is also available to an authenticated Django staff session and returns `202 Accepted`; it is not a public trigger. The staff UI handles the session and CSRF token for you.

**Pipeline sources:**

1. **OpenRouter** — model catalog, pricing, benchmarks, app rankings
2. **models.dev** — provider/model metadata (context, cost, capabilities, license and canonical IDs where published)
3. **Artificial Analysis** — independent indices, benchmark evaluations, performance and pricing. Free-tier endpoint: `language/models/free`; use `language/models` only with a tier that permits it.
4. **Canonical merge** — strict provider-scoped source-ID matching, with unmatched or ambiguous records kept separate

---

## ⚙️ Environment Variables Reference

| Variable | Required | Description | Example |
| :--- | :---: | :--- | :--- |
| `DEBUG` | Optional | Enable Django debug mode | `True` / `False` |
| `SECRET_KEY` | **Yes** | Django secret key | `django-insecure-...` |
| `DATABASE_URL` | Production | PostgreSQL connection URI; local development defaults to SQLite | `postgresql://.../neondb?sslmode=require` |
| `ALLOWED_HOSTS` | Optional | Explicit comma-separated hosts; wildcard `*` is rejected | `api.rankllms.com,rankllms-engine-kqso.onrender.com` |
| `CORS_ALLOWED_ORIGINS` | Optional | Browser origins allowed to call the API | `https://rankllms.com,https://api.rankllms.com` |
| `CSRF_TRUSTED_ORIGINS` | Optional | Trusted staff-session form origins | `https://api.rankllms.com` |
| `ARTIFICIAL_ANALYSIS_API_URL` | Optional | Artificial Analysis API v2 base URL | `https://artificialanalysis.ai/api/v2` |
| `ARTIFICIAL_ANALYSIS_API_KEY` | Optional | Server-side AA API key; required for AA sync | `your-key` |
| `ARTIFICIAL_ANALYSIS_MODELS_PATH` | Optional | Free or eligible Pro endpoint | `language/models/free` |
| `MODELS_DEV_API_URL` | Optional | models.dev catalog JSON | `https://models.dev/api.json` |
| `OPENROUTER_API_URL` | Optional | OpenRouter models endpoint | `https://openrouter.ai/api/v1/models` |
| `OPENROUTER_API_KEY` | Optional | Required for OpenRouter benchmarks and Data API datasets | `sk-or-...` |
| `ENABLE_SCHEDULER` | Optional | Enable APScheduler in one web instance | `true` |
| `SYNC_INTERVAL_HOURS` | Optional | Scheduler interval, 1–168 hours | `6` |
| `RUN_INITIAL_SYNC` | Optional | Import data during container startup | `false` |

---

## 🙏 Acknowledgments & Data Sources

RankLLMs Engine is free and open-source thanks to these projects and teams:

| Source | What we use | Link |
| :--- | :--- | :--- |
| **OpenRouter** | Model catalog, pricing, unified benchmarks, usage rankings | [openrouter.ai](https://openrouter.ai) |
| **Artificial Analysis** | Independent indices, benchmark evaluations, media arenas, performance and pricing | [artificialanalysis.ai](https://artificialanalysis.ai) |
| **models.dev** | Provider + model metadata (context, cost, capabilities) | [models.dev](https://models.dev) |
| **RankLLMs** | Product, leaderboards, and community | [rankllms.com](https://rankllms.com) |
| **CodaiPro** | Engineering, hosting, and open-source sponsorship | [codaipro.com](https://codaipro.com) |

Also built with [Django](https://www.djangoproject.com/) and [Django Ninja](https://django-ninja.dev/). PostgreSQL is configured through `DATABASE_URL` (Neon is supported); SQLite is used for local tests.

OpenRouter Data API datasets require attribution and are licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Artificial Analysis evaluations are third-party measurements, not benchmarks run by RankLLMs. Raw payloads and source IDs are retained for traceability.

## 🧪 Tests and checks

Run checks against isolated in-memory SQLite settings (these commands do not use `DATABASE_URL`):

```bash
DJANGO_SETTINGS_MODULE=config.test_settings python manage.py check
DJANGO_SETTINGS_MODULE=config.test_settings python manage.py makemigrations --check --dry-run
DJANGO_SETTINGS_MODULE=config.test_settings python manage.py test
```

See [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md), and [the API reference](docs/02_API_Reference.md).

---

## 📜 License & Credits

Built for **[RankLLMs](https://rankllms.com)** by **[CodaiPro](https://codaipro.com)**. Open-sourced under the **MIT License**.

**Keywords:** AI leaderboard API, LLM rankings, model comparison API, free benchmark API, OpenRouter data, Artificial Analysis scores, models.dev, open-weight models, SWE-bench leaderboard, RankLLMs.
