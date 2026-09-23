# RankLLMs Engine - Setup & Architecture Documentation

Welcome to the **RankLLMs Engine** documentation. This engine powers [RankLLMs.com](https://rankllms.com) by fetching, structuring, caching, and serving Large Language Model (LLM) metadata, pricing, capabilities, Artificial Analysis benchmark scores, daily usage trends, top app rankings, and task classification market share backed by a cloud-native **Neon PostgreSQL** database.

**Acknowledgments / data sources:** [OpenRouter](https://openrouter.ai) · [Artificial Analysis](https://artificialanalysis.ai) · [models.dev](https://models.dev) · Product: [rankllms.com](https://rankllms.com) · Built by [CodaiPro](https://codaipro.com). See the free [User Guide](../USER_GUIDE.md).

---

## 1. Project Overview & Vision

**Goal:** Create an independent, cached, high-performance API catalog of all Large Language Models (LLMs) available across the industry.

RankLLMs Engine ingests data from OpenRouter's 70+ endpoints and stores it cleanly inside your own Neon PostgreSQL database. This enables RankLLMs.com to feature:
- **Zero API Lock-in:** Full independence from external API rate-limits, downtime, or paywall changes.
- **Artificial Analysis Benchmarks:** Ingests `intelligence_index`, `coding_index`, and `agentic_index`.
- **Top AI App Usage Rankings:** Shows token consumption trends across major AI agents & apps.
- **Task Classification Market Share:** Shows breakdown of tokens by task type (Workflow Execution, Code Generation, Debugging, Reasoning, Writing).
- **Historical Price Tracking:** Logs all pricing changes per 1M tokens over time.

---

## 2. Architecture & Tech Stack

| Layer | Technology |
| :--- | :--- |
| **Framework** | Django 6.0 / Python 3.14 |
| **API Framework** | Django Ninja (Fast, Pydantic-validated OpenAPI) |
| **Database** | Neon PostgreSQL (`rankllms-engine`) |
| **DB Driver** | `psycopg2-binary` + `dj-database-url` |
| **Data Ingestion** | Custom Django Management Command + Requests |
| **Background Scheduler** | APScheduler (Automated 6-hour interval sync) |
| **CORS** | `django-cors-headers` (Configured for frontend consumption) |

---

## 3. Database Schema

The database models are located in [`llms/models.py`](file:///C:/Users/pc/Documents/LuckyLabs/rankllms-engine/llms/models.py):

### `Provider` Table
Stores AI model vendors/creators (OpenAI, Anthropic, Google, Meta, DeepSeek, Mistral, etc.).

### `LLMModel` Table
Stores individual language, image, video, and embedding models.
- `openrouter_id` (unique string): Model identifier (e.g., `openai/gpt-4o`).
- `slug` (unique string): URL-friendly slug (e.g., `openai-gpt-4o`).
- `name` (string): Model name.
- `provider` (FK to `Provider`).
- `category` (choice): `llm`, `image`, `video`, `embedding`.
- `context_length` (int): Context window size in tokens.
- `max_completion_tokens` (int): Maximum output tokens.
- `modality` (string), `is_multimodal` (bool), `supports_vision` (bool), `supports_tools` (bool).
- `prompt_price_per_1m` (decimal): Cost per 1 Million prompt/input tokens.
- `completion_price_per_1m` (decimal): Cost per 1 Million completion/output tokens.
- `is_free` (bool): True if prompt and completion costs are zero.
- **Artificial Analysis Indices:** `intelligence_index` (float), `coding_index` (float), `agentic_index` (float).
- `elo_score` (float), `rank_overall` (int).
- `raw_json` (JSONField): Complete original JSON payload.

### `AppRanking` Table
Stores top AI apps by token usage (`Hermes Agent`, `Claude Code`, `Kilo Code`, etc.).
- `app_id`, `app_name`, `rank`, `total_tokens`, `total_requests`, `updated_at`.

### `TaskClassification` Table
Stores market share by task type.
- `tag`, `display_name`, `macro_category`, `usage_share`, `token_share`, `top_models_share`.

### `DailyModelRanking` Table
Daily token usage totals for top models.

### `PricingHistory` Table
Historical log of model price adjustments.

---

## 4. OpenRouter Data Ingestion Pipeline

### Data Sync Service ([`llms/services/openrouter_sync.py`](file:///C:/Users/pc/Documents/LuckyLabs/rankllms-engine/llms/services/openrouter_sync.py))
- Fetches data from:
  - `GET /api/v1/models` (Catalog & Pricing)
  - `GET /api/v1/benchmarks` (Artificial Analysis Indices)
  - `GET /api/v1/datasets/app-rankings` (Top AI Applications)
  - `GET /api/v1/classifications/task` (Task Market Share)
- Executes ultra-fast **bulk database operations** (`bulk_create`, `bulk_update` with `ignore_conflicts=True`) inside a single atomic transaction block.

### Running Manual Sync
You can trigger data ingestion at any time via the Django CLI:
```bash
.\venv\Scripts\python.exe manage.py sync_openrouter
```

---

## 5. Django Ninja REST API Reference

Interactive Swagger/OpenAPI documentation: `/api/v1/docs`.

### Key Endpoints

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/api/v1/health` | `GET` | Health check & model count in Neon DB |
| `/api/v1/providers` | `GET` | List all AI providers with model counts |
| `/api/v1/models` | `GET` | Filter, search, and sort LLMs (by category, context, vision, tools, price limits, intelligence/coding indices) |
| `/api/v1/models/{path:identifier}` | `GET` | Specs, benchmark indices, raw payload, and pricing history for a specific model |
| `/api/v1/leaderboard` | `GET` | Rankings by `overall`, `coding`, `agentic`, `cost_effective`, `context`, `free` |
| `/api/v1/apps` | `GET` | Top AI applications ranked by total token volume |
| `/api/v1/task-share` | `GET` | Task classification market share (Workflow Execution, Code Gen, Debugging) |
| `/api/v1/compare` | `GET` | Side-by-side comparison payload for multiple models |
| `/api/v1/sync` | `POST` | Trigger full data sync on demand |

---

## 6. Local Development Guide

### Running Local Server
```bash
.\venv\Scripts\python.exe manage.py runserver
```
Navigate to [http://127.0.0.1:8000/api/v1/docs](http://127.0.0.1:8000/api/v1/docs) in your browser.
