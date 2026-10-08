# RankLLMs Engine - Setup & Architecture Documentation

Welcome to the **RankLLMs Engine** documentation. This engine powers [RankLLMs.com](https://rankllms.com) by fetching, structuring, caching, and serving Large Language Model (LLM) metadata, pricing, capabilities, Artificial Analysis benchmark scores, daily usage trends, top app rankings, and task classification market share backed by a cloud-native **Neon PostgreSQL** database.

**Acknowledgments / data sources:** [OpenRouter](https://openrouter.ai) · [Artificial Analysis](https://artificialanalysis.ai) · [models.dev](https://models.dev) · Product: [rankllms.com](https://rankllms.com) · Built by [CodaiPro](https://codaipro.com). See the free [User Guide](../USER_GUIDE.md).

---

## 1. Project Overview & Vision

**Goal:** Build a source-attributed canonical model catalog for metadata, pricing, performance, and independent benchmarks.

RankLLMs Engine ingests the OpenRouter model catalog and selected key-gated Data API feeds, Artificial Analysis Data API v2, and models.dev. It validates source snapshots and stores them in PostgreSQL (SQLite locally). This enables RankLLMs.com to feature:
- **Cached public reads:** Normal visitors use the stored database snapshot; user requests do not call source APIs.
- **Artificial Analysis Benchmarks:** Ingests `intelligence_index`, `coding_index`, and `agentic_index`.
- **Top AI App Usage Rankings:** Shows token consumption trends across major AI agents & apps.
- **Task Classification Market Share:** Shows breakdown of tokens by task type (Workflow Execution, Code Generation, Debugging, Reasoning, Writing).
- **Historical Price Tracking:** Logs all pricing changes per 1M tokens over time.

---

## 2. Architecture & Tech Stack

| Layer | Technology |
| :--- | :--- |
| **Framework** | Django 6.x / Python 3.12+ |
| **API Framework** | Django Ninja (Fast, Pydantic-validated OpenAPI) |
| **Database** | PostgreSQL via `DATABASE_URL` (Neon supported); SQLite for tests/local development |
| **DB Driver** | `psycopg2-binary` + `dj-database-url` |
| **Data Ingestion** | Custom Django Management Command + Requests |
| **Background Scheduler** | APScheduler (configured interval; Render instances may sleep) |
| **CORS** | `django-cors-headers` (Configured for frontend consumption) |

---

## 3. Database Schema

The database models are located in [`llms/models.py`](../llms/models.py):

### `Provider` Table
Stores AI model vendors/creators (OpenAI, Anthropic, Google, Meta, DeepSeek, Mistral, etc.).

### `LLMModel` Table
Stores individual language, image, video, and embedding models.
- `openrouter_id` (unique string): Model identifier (e.g., `openai/gpt-4o`).
- `slug` (unique string): URL-friendly slug (e.g., `openai-gpt-4o`).
- `name` (string): Model name.
- `provider` (FK to `Provider`).
- `category` (choice): `llm`, `image`, `video`, `audio`, `music`, `embedding`.
- `context_length` (nullable int): Context window size in tokens when a source reports it.
- `max_completion_tokens` (int): Maximum output tokens.
- `modality` (string), `is_multimodal` (bool), `supports_vision` (bool), `supports_tools` (bool).
- `prompt_price_per_1m` (decimal): Cost per 1 Million prompt/input tokens.
- `completion_price_per_1m` (decimal): Cost per 1 Million completion/output tokens.
- `is_free` (nullable bool): True/false only when source prices establish free/paid; otherwise unknown.
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

### Data Sync Service ([`llms/services/openrouter_sync.py`](../llms/services/openrouter_sync.py))
- Fetches data from:
  - `GET /api/v1/models` (Catalog & Pricing)
  - `GET /api/v1/benchmarks` (requires an OpenRouter key; unified third-party benchmark records)
  - `GET /api/v1/datasets/app-rankings` (Top AI Applications)
  - `GET /api/v1/classifications/task` (Task Market Share)
- Validates responses before atomic source writes, uses bounded retries, and preserves raw source payloads for provenance.

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
| `/api/v1/rankindex` | `GET` | Normalized canonical catalog with source IDs and provenance |
| `/api/v1/leaderboard/rankindex` | `GET` | Canonical RankLLMs leaderboard |
| `/api/v1/sync` | `POST` | Staff-session/CSRF protected; queues a background sync |
| `/settings/data-sync/` | `GET/POST` | Staff-only source controls, dry run, history, and integrity report |

---

## 6. Local Development Guide

### Running Local Server
```bash
.\venv\Scripts\python.exe manage.py runserver
```
Navigate to [http://127.0.0.1:8000/api/v1/docs](http://127.0.0.1:8000/api/v1/docs) in your browser.
