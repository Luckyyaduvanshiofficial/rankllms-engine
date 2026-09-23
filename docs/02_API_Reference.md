# 🔌 API Reference Guide

The RankLLMs REST API is powered by **Django Ninja** and **Pydantic v2**. It offers high-speed JSON serialization, automatic null guarding, and interactive OpenAPI Swagger documentation at **`/api/v1/docs`**.

Base API URL: `http://localhost:8000/api/v1` (or your production server URL)

> **Free & open-source.** Product: [rankllms.com](https://rankllms.com) · Maintainer: [CodaiPro](https://codaipro.com) · User guide: [USER_GUIDE.md](../USER_GUIDE.md)

**Data sources (acknowledgments):** [OpenRouter](https://openrouter.ai), [Artificial Analysis](https://artificialanalysis.ai), [models.dev](https://models.dev).

---

## 📌 Summary of Endpoints

| Endpoint | Method | Tag | Description |
| :--- | :---: | :--- | :--- |
| **`/health`** | `GET` | Health | Service status, total database record counts |
| **`/providers`** | `GET` | Providers | List of all 120+ AI Providers & Model Counts |
| **`/models`** | `GET` | Catalog | Search, filter, and paginate 760+ AI models |
| **`/models/{identifier}`** | `GET` | Catalog | Get detailed model specs, pricing & benchmarks |
| **`/leaderboard`** | `GET` | Leaderboards | Filterable model leaderboards (coding, speed, price, open-weight) |
| **`/apps`** | `GET` | Analytics | Top 50 AI apps ranked by token consumption |
| **`/task-share`** | `GET` | Analytics | Task classification market share breakdown |
| **`/compare`** | `GET` | Analytics | Side-by-side spec & pricing comparison |
| **`/sync`** | `POST` | Admin | Trigger full master data sync pipeline |

---

## 🔍 Detailed Endpoint Documentation

### 1. Health Check
`GET /api/v1/health`

**Response Example:**
```json
{
  "status": "healthy",
  "engine": "RankLLMs Engine 1.0",
  "database": "connected (Neon PostgreSQL)",
  "total_models": 764,
  "total_providers": 123,
  "app_rankings": 50,
  "task_classifications": 29
}
```

---

### 2. Models Catalog
`GET /api/v1/models`

**Query Parameters:**
- `search` *(string, optional)*: Filter by model name, slug, or provider.
- `category` *(string, optional)*: `llm`, `image`, `video`, `audio`, `embedding`.
- `provider` *(string, optional)*: Filter by provider slug (e.g. `anthropic`, `openai`).
- `is_free` *(boolean, optional)*: `true` to return free models.
- `is_open_weight` *(boolean, optional)*: `true` to return open-weight/open-source models.
- `limit` *(int, default: 50)*: Number of records to return.

**Response Example:**
```json
[
  {
    "id": 1,
    "openrouter_id": "anthropic/claude-3.7-sonnet",
    "slug": "claude-3-7-sonnet",
    "name": "Claude 3.7 Sonnet",
    "provider": {
      "name": "Anthropic",
      "slug": "anthropic"
    },
    "category": "llm",
    "is_open_weight": false,
    "is_free": false,
    "spec": {
      "context_length": 200000,
      "max_completion_tokens": 64000,
      "modality": "text+image->text",
      "supports_vision": true,
      "supports_tools": true
    },
    "pricing": {
      "prompt_price_per_1m": "3.000000",
      "completion_price_per_1m": "15.000000"
    },
    "benchmark": {
      "rankllms_index": 63.1,
      "intelligence_index": 63.1,
      "coding_index": 76.5,
      "agentic_index": 71.0,
      "tokens_per_second": 65.2,
      "time_to_first_token": 0.45
    }
  }
]
```

---

### 3. Leaderboard
`GET /api/v1/leaderboard`

**Query Parameters:**
- `sort_by` *(string, default: `rankllms_index`)*:
  - `rankllms_index`: Sorted by RankLLMs Index (highest overall intelligence at top).

  - `coding`: Sorted by Coding Index.
  - `speed`: Sorted by output throughput (`tokens_per_second`).
  - `price`: Sorted by lowest input prompt cost (`prompt_price_per_1m`).
- `category` *(string, default: `all`)*:
  - `all`: Full catalog.
  - `open-llm`: Only open-weight / open-source models (Llama 3.3, DeepSeek R1, Qwen 2.5).
  - `free`: Only 100% free models.
  - `weekly-top-10`: Returns curated weekly top 10 models.

---

### 4. Side-by-Side Model Comparison
`GET /api/v1/compare`

**Query Parameters:**
- `model_a` *(string, required)*: OpenRouter ID, slug, or ID of Model A (e.g. `anthropic/claude-3.5-sonnet`).
- `model_b` *(string, required)*: OpenRouter ID, slug, or ID of Model B (e.g. `deepseek/deepseek-r1`).

**Response Example:**
```json
{
  "model_a": {
    "name": "Claude 3.5 Sonnet",
    "context_length": 200000,
    "prompt_price_per_1m": "$3.00",
    "completion_price_per_1m": "$15.00",
    "coding_index": 76.5,
    "tokens_per_second": 65.2
  },
  "model_b": {
    "name": "DeepSeek R1",
    "context_length": 128000,
    "prompt_price_per_1m": "$0.55",
    "completion_price_per_1m": "$2.19",
    "coding_index": 75.8,
    "tokens_per_second": 82.0
  },
  "comparison": {
    "intelligence_winner": "Model A",
    "price_winner": "Model B (81% Cheaper)",
    "speed_winner": "Model B (25% Faster)"
  }
}
```

---

### 5. Master Data Sync Trigger
`POST /api/v1/sync`

**Response Example:**
```json
{
  "status": "success",
  "summary": {
    "elapsed_seconds": 152.7,
    "total_models": 764,
    "total_providers": 123,
    "total_benchmarks": 764,
    "coverage_pct": 100.0
  }
}
```
