# 📘 RankLLMs Engine — User Guide (Free API)

**RankLLMs Engine** is a **free** REST API for AI model leaderboards, pricing, and benchmarks.  
Powering **[rankllms.com](https://rankllms.com)** · Open source by **[CodaiPro](https://codaipro.com)**.

- **Base URL (production):** `https://api.rankllms.com/api/v1`
- **Base URL (local):** `http://127.0.0.1:8000/api/v1`
- **Swagger UI:** `https://api.rankllms.com/api/v1/docs`
- **OpenAPI JSON:** `https://api.rankllms.com/api/v1/openapi.json`
- **AI Agent guide:** [docs/00_AI_AGENT_GUIDE.md](docs/00_AI_AGENT_GUIDE.md)

**No API key is required** for core read endpoints. Free tier is intended for production apps and personal projects.

---

## 🔑 Quick examples

### 1. Leaderboard (top models by intelligence)

```bash
curl "https://api.rankllms.com/api/v1/leaderboard?limit=10&dedup=true"
```

Sort options: `intelligence` (legacy default), `rankllms_index` (canonical composite), `coding`, `swe_bench`, `agentic`, `context`, `cost`.

```bash
curl "https://api.rankllms.com/api/v1/leaderboard?sort_by=coding&limit=5&dedup=true"
```

### 2. Search & filter models

```bash
# Free + open-weight vision models under $1 / 1M prompt tokens
curl "https://api.rankllms.com/api/v1/models?is_open_weight=true&supports_vision=true&max_prompt_price_1m=1.00&dedup=true&limit=5"
```

Useful query params: `search`, `provider`, `is_open_weight`, `is_free`, `supports_vision`, `supports_tools`, `max_prompt_price_1m`, `min_context`, `ordering`, `limit`, `offset`.

### 3. Model detail

```bash
curl "https://api.rankllms.com/api/v1/models/claude-3-7-sonnet"
```

### 4. Compare two models

```bash
curl "https://api.rankllms.com/api/v1/compare?model_a=claude-3-7-sonnet&model_b=gpt-4o"
```

### 5. Providers catalog

```bash
curl "https://api.rankllms.com/api/v1/providers"
```

### 6. Health check

```bash
curl "https://api.rankllms.com/api/v1/health"
```

---

## 🐍 Python example

```python
import requests

BASE = "https://api.rankllms.com/api/v1"

res = requests.get(f"{BASE}/leaderboard", params={"limit": 5, "dedup": True}, timeout=15)
res.raise_for_status()
for row in res.json().get("rankings", []):
    print(row["rank"], row["name"], row.get("intelligence_index"))
```

---

## 🟨 JavaScript / Node example

```js
const BASE = "https://api.rankllms.com/api/v1";

const res = await fetch(`${BASE}/leaderboard?limit=5&dedup=true`);
const data = await res.json();
console.log(data.rankings);
```

---

## 📊 Key endpoints

| Endpoint | Method | Description |
| :--- | :---: | :--- |
| `/health` | GET | Service status & record counts |
| `/providers` | GET | All AI providers |
| `/models` | GET | Search / filter / paginate model catalog |
| `/models/{slug}` | GET | Full specs, pricing, benchmarks |
| `/models/cards` | GET | Up to 500 model cards |
| `/leaderboard` | GET | Ranked leaderboard |
| `/leaderboard/open-weights` | GET | Open-source / open-weight only |
| `/compare` | GET | Side-by-side comparison |
| `/benchmarks` | GET | Benchmark matrix |
| `/top-10` | GET | Weekly top 10 categories |
| `/apps` | GET | Top AI apps by token usage |
| `/task-share` | GET | Task classification market share |
| `/sync` | POST | Queue a full sync (Django staff session + CSRF required; returns 202) |

Full parameter tables: [docs/02_API_Reference.md](docs/02_API_Reference.md).

---

## 🧩 Data sources (acknowledgments)

We thank and credit:

- **[OpenRouter](https://openrouter.ai)** — model catalog, pricing, unified benchmarks
- **[Artificial Analysis](https://artificialanalysis.ai)** — independent intelligence, capability, benchmark, performance, and pricing data
- **[models.dev](https://models.dev)** — provider & model metadata
- **[RankLLMs](https://rankllms.com)** — product & leaderboards
- **[CodaiPro](https://codaipro.com)** — open-source maintenance

---

## ❓ FAQ

**Is this free?**  
Yes. Core leaderboard and catalog endpoints are free for personal and production use.

**Do I need an API key?**  
No for standard read endpoints. API-key administration is staff-only. Generated keys are not currently used to enforce public request quotas.

**How fresh is the data?**  
Render queues the master pipeline every 6 hours while its instance is awake. Free Render instances sleep while idle. Staff can run all sources or one source at `/settings/data-sync/`; a dry run previews the same pipeline and rolls back all writes. `POST /api/v1/sync` requires a staff session and CSRF token.

**Can I self-host?**  
Yes — see [docs/03_Deployment_Guide.md](docs/03_Deployment_Guide.md) and the [Dockerfile](Dockerfile).

---

MIT licensed. Built for [rankllms.com](https://rankllms.com) by [CodaiPro](https://codaipro.com).
