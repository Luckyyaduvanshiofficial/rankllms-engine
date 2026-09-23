# 🚀 About RankLLMs Engine

> **High-Performance LLM & Multi-Modal Leaderboard Data API Engine**  
> Powering [RankLLMs.com](https://rankllms.com) with real-time benchmarks, transparent scoring, and automated AI catalog aggregation.

---

## 🌟 Mission & Overview

**RankLLMs Engine** is a specialized, production-ready backend engine designed to aggregate, normalize, score, and rank **760+ AI models** (Large Language Models, Image Generation, Video Generation, and Audio/Speech models) across **120+ AI providers** (including OpenAI, Anthropic, Google, Meta, DeepSeek, Qwen, Mistral, xAI, Cohere, and more).

The engine powers high-speed REST APIs and pre-calculated datasets for:
- 📊 **Comprehensive AI Leaderboards** sorted by the proprietary **RankLLMs Index**.
- 🔓 **Open-LLM Leaderboards** tracking open-weights models and license compliance.
- ⚖️ **Dynamic Side-by-Side Model Comparisons** (specs, pricing, benchmarks, context windows).
- 🏆 **Weekly Top 10 Charts** across coding, reasoning, value, and open-source categories.
- 🎴 **Top 200 Curated Model Cards** ready for frontend direct imports (`.json` and `.ts`).
- 📈 **Token Usage & Task Classification Market Share** analytics.

---

## 🛠️ Technology Stack & Infrastructure

- **Language & Framework**: Python 3.12+ with **Django 6.0**
- **API Layer**: **Django Ninja** (Powered by Pydantic v2 schemas for high-speed serialization, OpenAPI/Swagger docs, and strict type safety)
- **Database**: **Neon Serverless PostgreSQL** with connection pooling and SSL encryption
- **Automated Scheduling**: **APScheduler** background daemon executing automated data synchronization every 6 hours
- **Developer Studio / Dashboard**: Built-in interactive light-themed developer portal served directly from `/`

---

## 🏛️ High-Level System Architecture

```
 +-------------------------+       +------------------------------------+
 |  OpenRouter API Catalog |       |  Artificial Analysis Data API v2   |
 |  (Models + Analytics)   |       |  (LLM Benchmarks + Intelligence)   |
 +------------+------------+       +-----------------+------------------+
              |                                      |
              v                                      v
    [ openrouter_sync.py ]                [ artificial_analysis_sync.py ]
    (Catalog & App Rankings)              (Direct Benchmark Ingestion)
              |                                      |
              +-------------------+------------------+
                                  |
                                  v
                        [ fill_nulls.py ]
                        (Backfill specs, pricing & fallback scores)
                                  |
                                  v
                        [ deduplication.py ]
                        (Filter redundant variant endpoints down
                         to ~200 curated unique core models)
                                  |
                                  v
                        [ rankllms_calculator.py ]
                        (Compute official RankLLMs Index)
                                  |
                                  v
                    +---------------------------+
                    |  Neon PostgreSQL Database |
                    +-------------+-------------+
                                  |
            +---------------------+---------------------+
            |                                           |
            v                                           v
+---------------------------+               +---------------------------+
| Django Ninja REST API v1  |               | Static Model Cards Export |
|   (/api/v1/* Endpoints)   |               |   (/data/top_200_models)  |
+---------------------------+               +---------------------------+
```

---

## 📐 Scoring Methodology: The RankLLMs Index

The **RankLLMs Index** is a transparent, composite score calculated to reflect real-world model capability:

$$\text{RankLLMs Index} = 0.40 \cdot I + 0.25 \cdot C + 0.15 \cdot A + 0.10 \cdot S + 0.10 \cdot E$$

Where:
- **$I$ (Intelligence Index - 40%)**: Composite reasoning, knowledge, and problem-solving index.
- **$C$ (Coding Index - 25%)**: Software engineering, syntax, logic, and code generation score.
- **$A$ (Agentic Index - 15%)**: Tool use, function calling, structured output adherence, and multi-step planning.
- **$S$ (SWE-Bench Resolved % - 10%)**: Real-world GitHub issue resolution benchmark.
- **$E$ (Arena ELO Normalized - 10%)**: LMSYS Chatbot Arena human preference score ($\text{Normalized} = \frac{\text{ELO} - 1000}{5}$).

---

## 🔌 API Endpoints Catalog

All API endpoints are available under the `/api/v1/` prefix:

| Endpoint | Method | Tag / Category | Description |
| :--- | :---: | :--- | :--- |
| `/api/v1/models` | `GET` | **Models Catalog** | Full catalog with filtering (provider, modality, license, max price, context size) & search |
| `/api/v1/models/{identifier}` | `GET` | **Models Catalog** | Detailed specs, pricing, and benchmarks for a specific model slug or ID |
| `/api/v1/models/cards` | `GET` | **Static Cards API** | Curated Top 200 Model Cards with tags, pricing, and specs |
| `/api/v1/leaderboard` | `GET` | **LLM Leaderboard** | Full leaderboard ranked by RankLLMs Index / Intelligence Index |
| `/api/v1/leaderboard/open-weights`| `GET` | **Open-LLM** | Leaderboard dedicated exclusively to open-weight/open-source models |
| `/api/v1/compare` | `GET` | **Comparison** | Side-by-side comparison between 2 to 5 models with metric winners |
| `/api/v1/top-10` | `GET` | **Top 10 Rankings** | Curated weekly rankings across 5 categories with rank deltas |
| `/api/v1/benchmarks` | `GET` | **Benchmarks** | Benchmarks dataset with `rankllms_index`, coding, and SWE-bench |
| `/api/v1/apps` | `GET` | **Analytics & Usage**| Top AI applications ranked by real-world token consumption |
| `/api/v1/task-share` | `GET` | **Analytics & Usage**| Market share distribution across AI task categories |
| `/api/v1/keys/generate` | `POST` | **API Key Manager**| Generate API keys for frontend/client application access |
| `/api/v1/keys` | `GET` | **API Key Manager**| List and manage active API keys |
| `/api/v1/sync` | `POST` | **Data Pipeline** | Trigger immediate asynchronous master data sync |
| `/api/v1/health` | `GET` | **System** | Service and database health check status |

---

## 🗃️ Key Datasets & Exports

Located in [`data/`](file:///C:/Users/pc/Documents/LuckyLabs/rankllms-engine/data/):
- **[`top_200_models.json`](file:///C:/Users/pc/Documents/LuckyLabs/rankllms-engine/data/top_200_models.json)**: Normalized, deduplicated JSON dataset of the top 200 AI models.
- **[`top_200_models.ts`](file:///C:/Users/pc/Documents/LuckyLabs/rankllms-engine/data/top_200_models.ts)**: TypeScript typed interface `ModelCard` and typed array for instant frontend import.

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
