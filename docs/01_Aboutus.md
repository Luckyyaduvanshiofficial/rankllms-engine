# 🚀 About RankLLMs Engine

> **High-Performance LLM & Multi-Modal Leaderboard Data API Engine**  
> Powering [RankLLMs.com](https://rankllms.com) with real-time benchmarks, transparent scoring, and automated AI catalog aggregation.

---

## 🌟 Mission & Overview

**RankLLMs Engine** is a backend for aggregating, normalizing, and publishing model metadata, prices, and third-party benchmark results across OpenRouter, Artificial Analysis, and models.dev. Catalog size changes as upstream sources change; this README does not promise a hardcoded model count.

The engine powers high-speed REST APIs and pre-calculated datasets for:
- 📊 **Comprehensive AI Leaderboards** sorted by the proprietary **RankLLMs Index**.
- 🔓 **Open-LLM Leaderboards** tracking open-weights models and license compliance.
- ⚖️ **Dynamic Side-by-Side Model Comparisons** (specs, pricing, benchmarks, context windows).
- 🏆 **Weekly Top 10 Charts** across coding, reasoning, value, and open-source categories.
- 🎴 **Live Model Cards API** for fetching a limited set of current catalog records.
- 📈 **Token Usage & Task Classification Market Share** analytics.

---

## 🛠️ Technology Stack & Infrastructure

- **Language & Framework**: Python 3.12+ with **Django 6.x**
- **API Layer**: **Django Ninja** (Powered by Pydantic v2 schemas for high-speed serialization, OpenAPI/Swagger docs, and strict type safety)
- **Database**: PostgreSQL through `DATABASE_URL` (Neon supported); SQLite for isolated local tests
- **Automated Scheduling**: **APScheduler** can queue syncs every configured interval; Render is set to six hours while its instance is awake
- **Developer Studio / Dashboard**: Built-in interactive light-themed developer portal served directly from `/`

---

## 🏛️ High-Level System Architecture

```
  +------------+       +-----------------------+       +-------------+
  | OpenRouter |       | Artificial Analysis   |       | models.dev  |
  | catalog +  |       | language + media API  |       | catalog     |
  | Data API   |       +-----------+-----------+       +------+------+
  +-----+------+                   |                          |
        +--------------------------+--------------------------+
                                   v
                       validated source snapshots
                                   v
                    provider-scoped ID matching
                                   v
            canonical rankindex + source provenance
                       /                    \
                      v                      v
             Django Ninja API          server-rendered UI
```

---

## 📐 Scoring Methodology: The RankLLMs Index

The **RankLLMs Index** is a transparent, composite score calculated to reflect real-world model capability:

$$\text{RankLLMs Index} = \frac{0.35I + 0.30C + 0.15A + 0.10G + 0.10T}{\text{sum of weights for available signals}}$$

Where:
- **$I$ (Intelligence Index - 35%)**, **$C$ (Coding Index - 30%)**, and **$A$ (Agentic Index - 15%)** use the published 0–100 Artificial Analysis indices.
- **$G$ (GPQA Diamond - 10%)** and **$T$ (TerminalBench Hard or v2.1 - 10%)** are converted from fractions to percentages when needed.
- Missing metrics are excluded and the remaining weights are renormalized. Price, speed, context, and Arena ELO do not contribute to this composite. No benchmark score is inferred from a model name.
- All benchmark data is credited to its source; RankLLMs does not claim to have run third-party evaluations.

---

## 🔌 API Endpoints Catalog

All API endpoints are available under the `/api/v1/` prefix:

| Endpoint | Method | Tag / Category | Description |
| :--- | :---: | :--- | :--- |
| `/api/v1/models` | `GET` | **Models Catalog** | Full catalog with filtering (provider, modality, license, max price, context size) & search |
| `/api/v1/models/{identifier}` | `GET` | **Models Catalog** | Detailed specs, pricing, and benchmarks for a specific model slug or ID |
| `/api/v1/models/cards` | `GET` | **Model Cards API** | Live catalog cards with tags, nullable pricing, and available specs |
| `/api/v1/leaderboard` | `GET` | **Legacy LLM Leaderboard** | Source benchmark leaderboard; accepts supported metric sort fields |
| `/api/v1/leaderboard/rankindex` | `GET` | **Canonical Leaderboard** | Merged RankLLMs composite snapshot and provenance |
| `/api/v1/leaderboard/open-weights`| `GET` | **Open-LLM** | Leaderboard dedicated exclusively to open-weight/open-source models |
| `/api/v1/compare` | `GET` | **Comparison** | Side-by-side comparison between 2 to 5 models with metric winners |
| `/api/v1/top-10` | `GET` | **Top 10 Rankings** | Curated weekly rankings across 5 categories with rank deltas |
| `/api/v1/benchmarks` | `GET` | **Benchmarks** | Benchmarks dataset with `rankllms_index`, coding, and SWE-bench |
| `/api/v1/apps` | `GET` | **Analytics & Usage**| Top AI applications ranked by real-world token consumption |
| `/api/v1/task-share` | `GET` | **Analytics & Usage**| Market share distribution across AI task categories |
| `/api/v1/keys/generate` | `POST` | **Staff only** | Issue a key (returned once); keys do not currently enforce read quotas |
| `/api/v1/keys` | `GET` | **Staff only** | List key metadata with masked previews |
| `/api/v1/sync` | `POST` | **Staff only** | Queue a background full source sync; requires session + CSRF |
| `/settings/data-sync/` | `GET/POST` | **Staff only** | Source status, manual sync, dry run, safe settings, history, integrity |
| `/api/v1/health` | `GET` | **System** | Service and database health check status |

---

## 🗃️ Key Datasets & Exports

The `data/top_200_models.json` and `.ts` files are historical static exports and are not used by the Django API or UI. Use the live API and `rankindex` snapshot for current values.

---

## 💻 Local Development & Operation

### Run Local Server
```bash
# Activate environment
.\venv\Scripts\activate

# Run migrations & start server
python manage.py migrate
python manage.py runserver
```

- **Interactive Portal**: `http://127.0.0.1:8000/`
- **Swagger Documentation**: `http://127.0.0.1:8000/api/v1/docs`

### Manual Data Pipeline Trigger
```bash
python manage.py sync_all
```

---

## 👥 Credits & Acknowledgments

- **Organization**: [LuckyLabs](https://github.com/Luckyyaduvanshiofficial)
- **Project**: RankLLMs Engine
- **Product**: [rankllms.com](https://rankllms.com)
- **Maintainer**: [CodaiPro](https://codaipro.com)
- **License**: MIT

### Data sources we thank

| Source | What we use | Link |
| :--- | :--- | :--- |
| **OpenRouter** | Model catalog, pricing, unified benchmarks, usage rankings | [openrouter.ai](https://openrouter.ai) |
| **Artificial Analysis** | Intelligence, coding, agentic indices & telemetry | [artificialanalysis.ai](https://artificialanalysis.ai) |
| **models.dev** | Provider + model metadata (context, cost, capabilities) | [models.dev](https://models.dev) |
| **RankLLMs** | Product, leaderboards, and community | [rankllms.com](https://rankllms.com) |
| **CodaiPro** | Engineering, hosting, and open-source sponsorship | [codaipro.com](https://codaipro.com) |

See also the [User Guide](../USER_GUIDE.md) for free API usage.
