# RankLLMs Engine — Autonomous AI Agent Integration Guide

> **Target Audience:** Autonomous AI Agents, LLM Prompt Chains, Multi-Agent Orchestrators (LangChain, AutoGen, CrewAI, LlamaIndex), and Model Routing Engines.

The **RankLLMs Engine** is a high-performance, real-time AI Model Intelligence and Leaderboard API. It evaluates, ranks, and benchmarks over **900+ foundation models** across proprietary (OpenAI, Anthropic, Google, xAI) and open-weight (DeepSeek, Meta, Alibaba, Mistral) providers.

**Product:** [rankllms.com](https://rankllms.com) · **Maintainer:** [CodaiPro](https://codaipro.com) · **Free user guide:** [USER_GUIDE.md](../USER_GUIDE.md)

**Data sources (acknowledgments):** [OpenRouter](https://openrouter.ai), [Artificial Analysis](https://artificialanalysis.ai), [models.dev](https://models.dev).

---

## 1. System Overview & Core Constants

- **Base URL:** `https://api.rankllms.com/api/v1` (or local: `http://localhost:8000/api/v1`)
- **Interactive Documentation / Swagger:** `https://api.rankllms.com/api/v1/docs`
- **Machine-Readable OpenAPI Spec:** `https://api.rankllms.com/api/v1/openapi.json`
- **Default Content-Type:** `application/json`
- **Authentication Header (Optional for public tiers, required for high-throughput):**
  ```http
  X-API-Key: rk_live_xxxxxxxxxxxxxxxx
  ```

---

## 2. Agent Decision-Making Matrix (The RankLLMs Formula)

When making autonomous model selection decisions, use the **RankLLMs Composite Intelligence Formula**:

$$\text{RankLLMs Index} = 0.40 \times \text{Intelligence} + 0.25 \times \text{Coding} + 0.15 \times \text{Agentic} + 0.10 \times \text{SWE-Bench} + 0.10 \times \text{Efficiency}$$

| Metric Key | Scale | Description | Primary Use Case for Agents |
| :--- | :--- | :--- | :--- |
| `rankllms_index` | 0 – 100 | Composite holistic intelligence score | Default general-purpose model routing |
| `coding_index` | 0 – 100 | LiveCodeBench, HumanEval, and code synthesis | Code generation, debugging, refactoring |
| `agentic_index` | 0 – 100 | Multi-step tool use, function calling, planning | Autonomous agents, workflow execution |
| `swe_bench_score` | 0 – 100 | Real GitHub issue resolution rate | Software engineering & deep bug fixing |
| `context_length` | Integer | Maximum token capacity | Document synthesis & multi-file ingest |
| `prompt_price_per_1m` | USD ($) | Price per 1,000,000 input tokens | Budget optimization & cost-benefit routing |

---

## 3. Deterministic Agent Query Recipes

### Recipe 1: Retrieve Top $N$ Models Sorted by Use-Case

Agents can dynamically select the best models for a given workload.

#### Endpoint
```http
GET /api/v1/leaderboard?sort_by={sort_key}&dedup=true&limit={limit}
```

#### Query Parameters
- `sort_by`:
  - `rankllms_index` (Default): General overall intelligence.
  - `coding`: Highest code generation and refactoring capability.
  - `swe_bench`: Complex multi-file repository problem resolution.
  - `agentic`: Tool use, function execution, and multi-turn planning.
  - `context`: Largest context window (e.g. 2M+ tokens).
  - `cost`: Lowest price per million input tokens.
- `dedup`: `true` (Collapses batch endpoints, previews, and effort tags to canonical flagship models).
- `limit`: Integer (1 to 100).

#### Example cURL
```bash
curl -X GET "https://api.rankllms.com/api/v1/leaderboard?sort_by=coding&dedup=true&limit=5"
```

#### Response Envelope
```json
{
  "sort_by": "coding",
  "dedup": true,
  "count": 5,
  "rankings": [
    {
      "rank": 1,
      "id": 142,
      "slug": "anthropic-claude-opus-5",
      "openrouter_id": "anthropic/claude-opus-5",
      "name": "Claude Opus 5",
      "provider": "Anthropic",
      "is_open_weight": false,
      "rankllms_index": 94.2,
      "intelligence_index": 92.5,
      "coding_index": 99.0,
      "agentic_index": 95.0,
      "swe_bench_score": 88.4,
      "context_length": 200000,
      "prompt_price_per_1m": "15.00",
      "completion_price_per_1m": "75.00",
      "is_free": false
    }
  ]
}
```

---

### Recipe 2: Search & Filter with Complex Constraints

Find models meeting specific operational constraints (e.g., self-hostable open-weights with vision support and budget limits).

#### Endpoint
```http
GET /api/v1/models
```

#### Query Parameters
- `search`: Keyword string (e.g. `llama`, `deepseek`, `flash`).
- `provider`: Provider slug (e.g. `anthropic`, `openai`, `deepseek`, `google`, `meta`).
- `category`: `llm` | `image` | `video` | `audio` | `embedding`.
- `is_open_weight`: `true` | `false`.
- `is_free`: `true` | `false`.
- `supports_vision`: `true` | `false`.
- `supports_tools`: `true` | `false`.
- `min_context`: Integer (e.g. `128000`).
- `max_prompt_price_1m`: Float in USD (e.g. `2.50`).
- `ordering`: `-rankllms_index` | `-coding_index` | `prompt_price` | `-context_length`.
- `dedup`: `true`.
- `limit`: `20`.
- `offset`: `0`.

#### Example cURL
```bash
curl -X GET "https://api.rankllms.com/api/v1/models?is_open_weight=true&supports_vision=true&max_prompt_price_1m=1.00&ordering=-rankllms_index&dedup=true&limit=5"
```

---

### Recipe 3: Head-to-Head Model Comparison for Routing

When an agent needs to decide between two specific models, compare them side-by-side.

#### Endpoint
```http
GET /api/v1/compare?model_a={slug_or_id_a}&model_b={slug_or_id_b}
```

#### Example Request
```bash
curl -X GET "https://api.rankllms.com/api/v1/compare?model_a=claude-3-7-sonnet&model_b=gpt-4o"
```

#### Response Envelope
```json
{
  "comparison_summary": "Comparing Claude 3.7 Sonnet vs GPT-4o",
  "winner": {
    "overall": "claude-3-7-sonnet",
    "coding": "claude-3-7-sonnet",
    "pricing_value": "gpt-4o"
  },
  "models": [
    {
      "id": "claude-3-7-sonnet",
      "name": "Claude 3.7 Sonnet",
      "provider": "Anthropic",
      "benchmarks": {
        "rankllms_index": 91.5,
        "intelligence_index": 89.2,
        "coding_index": 94.0,
        "agentic_index": 92.0,
        "swe_bench_score": 70.3
      },
      "pricing": {
        "prompt_price_per_1m": "3.00",
        "completion_price_per_1m": "15.00"
      },
      "specs": {
        "context_length": 200000,
        "supports_vision": true
      }
    },
    {
      "id": "gpt-4o",
      "name": "GPT-4o",
      "provider": "OpenAI",
      "benchmarks": {
        "rankllms_index": 82.4,
        "intelligence_index": 78.5,
        "coding_index": 77.0,
        "agentic_index": 84.0,
        "swe_bench_score": 38.8
      },
      "pricing": {
        "prompt_price_per_1m": "2.50",
        "completion_price_per_1m": "10.00"
      },
      "specs": {
        "context_length": 128000,
        "supports_vision": true
      }
    }
  ]
}
```

---

### Recipe 4: Top 200 Model Cards for Static Sites & UI Renderers

Retrieve standardized model cards for instant static site generation (Astro, Next.js, Vite).

#### Endpoint
```http
GET /api/v1/models/cards?limit=200&dedup=true
```

---

## 4. OpenAI & Anthropic Tool Definitions for Function Calling

Copy and paste these JSON tool schemas directly into your LLM agent tool configurations:

```json
[
  {
    "type": "function",
    "function": {
      "name": "rankllms_get_leaderboard",
      "description": "Fetches the current leaderboard of AI models ranked by intelligence, coding capability, agentic tool use, SWE-bench software engineering, or cost.",
      "parameters": {
        "type": "object",
        "properties": {
          "sort_by": {
            "type": "string",
            "enum": ["rankllms_index", "coding", "swe_bench", "agentic", "context", "cost"],
            "description": "Ranking dimension to sort models by."
          },
          "dedup": {
            "type": "boolean",
            "description": "Set to true to deduplicate model variants and exclude batch noise.",
            "default": true
          },
          "limit": {
            "type": "integer",
            "description": "Number of top models to return (1-50).",
            "default": 10
          }
        },
        "required": ["sort_by"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "rankllms_compare_models",
      "description": "Executes an in-depth side-by-side benchmark, spec, and pricing comparison between two AI models.",
      "parameters": {
        "type": "object",
        "properties": {
          "model_a": {
            "type": "string",
            "description": "Slug, OpenRouter ID, or name of first model (e.g. 'claude-3-7-sonnet')."
          },
          "model_b": {
            "type": "string",
            "description": "Slug, OpenRouter ID, or name of second model (e.g. 'deepseek-r1')."
          }
        },
        "required": ["model_a", "model_b"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "rankllms_filter_models",
      "description": "Finds AI models matching specific capability, pricing, open-weights, and modality constraints.",
      "parameters": {
        "type": "object",
        "properties": {
          "search": { "type": "string", "description": "Search term" },
          "is_open_weight": { "type": "boolean" },
          "supports_vision": { "type": "boolean" },
          "max_prompt_price_1m": { "type": "number", "description": "Maximum USD price per 1M prompt tokens" },
          "min_context": { "type": "integer", "description": "Minimum context window tokens" }
        }
      }
    }
  }
]
```

---

## 5. Python Agent Client Reference

```python
import requests

class RankLLMsClient:
    def __init__(self, base_url: str = "https://api.rankllms.com/api/v1", api_key: str = None):
        self.base_url = base_url.rstrip("/")
        self.headers = {"User-Agent": "RankLLMs-Agent/1.0"}
        if api_key:
            self.headers["X-API-Key"] = api_key

    def get_top_coding_models(self, limit: int = 5) -> list:
        res = requests.get(f"{self.base_url}/leaderboard", params={"sort_by": "coding", "dedup": True, "limit": limit}, headers=self.headers)
        res.raise_for_status()
        return res.json().get("rankings", [])

    def compare(self, model_a: str, model_b: str) -> dict:
        res = requests.get(f"{self.base_url}/compare", params={"model_a": model_a, "model_b": model_b}, headers=self.headers)
        res.raise_for_status()
        return res.json()

    def find_budget_open_weights(self, max_price: float = 1.0, min_context: int = 128000) -> list:
        params = {
            "is_open_weight": True,
            "max_prompt_price_1m": max_price,
            "min_context": min_context,
            "ordering": "-rankllms_index",
            "dedup": True,
            "limit": 10
        }
        res = requests.get(f"{self.base_url}/models", params=params, headers=self.headers)
        res.raise_for_status()
        return res.json().get("items", [])

# Quick Execution Test:
if __name__ == "__main__":
    client = RankLLMsClient()
    top_coders = client.get_top_coding_models(3)
    print("Top 3 Coders:", [(m["name"], m["coding_index"]) for m in top_coders])
```

---

## 6. Machine-Readable Semantic Endpoints

| Resource | Path | Method | Description |
| :--- | :--- | :--- | :--- |
| **Catalog** | `/models` | `GET` | Full query & faceted filter search |
| **Cards** | `/models/cards` | `GET` | Astro / Next.js SSG payload |
| **Leaderboard** | `/leaderboard` | `GET` | Real-time multi-dimensional ranking |
| **Category** | `/leaderboard/category/{category}` | `GET` | Segmented (`llm`, `image`, `video`, `audio`, `embedding`) |
| **Top 10** | `/top-10` | `GET` | Weekly curated top 10 models |
| **Compare** | `/compare` | `GET` | Head-to-head metrics diff |
| **Benchmarks**| `/benchmarks` | `GET` | Raw evaluations (MMLU, Arena, SWE) |
| **Health** | `/health` | `GET` | Live uptime, latency & DB status |
| **Master Sync**| `/sync` | `POST` | Pipeline sync (requires Admin Key) |
