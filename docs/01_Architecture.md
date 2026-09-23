# 🏗️ Architecture & Data Schema Guide

## Overview

RankLLMs Engine is built on a high-throughput, bulk-optimized data architecture designed to aggregate AI model capabilities, pricing, live throughput/latency, and usage rankings into a unified PostgreSQL database.

---

## 🏛️ System Architecture Diagram

```
 +-------------------------+       +------------------------------------+
 |  OpenRouter API Catalog |       |  Artificial Analysis Data API v2   |
 |  (Models + Analytics)   |       |  (LLM Benchmarks + Media Rating)   |
 +------------+------------+       +-----------------+------------------+
              |                                      |
              v                                      v
    [ openrouter_sync.py ]                [ artificial_analysis_sync.py ]
    (Catalog & App Rankings)              (Intelligence, Coding & Media)
              |                                      |
              +-------------------+------------------+
                                  |
                                  v
                        [ fill_nulls.py ]
                        (Backfills missing specs,
                         pricing & benchmarks)
                                  |
                                  v
                    +---------------------------+
                    |  Neon PostgreSQL Database |
                    +-------------+-------------+
                                  |
                                  v
                    +---------------------------+
                    | Django Ninja REST API v1  |
                    |   (High-Speed Endpoints)  |
                    +---------------------------+
```

---

## 🗄️ Database Schema & Models

### 1. `Provider`
Represents AI model creators and host providers (e.g. OpenAI, Anthropic, Google, DeepSeek, Meta).
- `name`: Provider display name.
- `slug`: Unique slug identifier (e.g. `openai`, `anthropic`).
- `description`: Overview description.
- `website_url`: Provider homepage.

### 2. `LLMModel`
Core model registry entity containing base classification and parameters.
- `openrouter_id`: Unique provider/model path (e.g. `anthropic/claude-3.7-sonnet`).
- `slug`: Clean URL slug (e.g. `claude-3-7-sonnet`).
- `name`: Model display name.
- `provider`: ForeignKey to `Provider`.
- `category`: `llm`, `image`, `video`, `embedding`, `audio`.
- `is_open_weight`: Boolean for open-weight/open-source models (Llama, DeepSeek, Qwen).
- `is_free`: Boolean indicating free-tier availability.

### 3. `ModelSpecification` (1:1 with `LLMModel`)
Technical specifications and hardware parameters.
- `context_length`: Maximum context window tokens (e.g. `200000`, `1048576`).
- `max_completion_tokens`: Maximum output generation window.
- `modality`: Input/output modality (e.g. `text->text`, `text+image->text`).
- `is_multimodal`, `supports_vision`, `supports_audio`, `supports_tools`: Boolean flags.

### 4. `ModelPricing` (1:1 with `LLMModel`)
Granular pricing normalized per 1 Million tokens in USD.
- `prompt_price_per_1m`: Prompt input price per 1M tokens (e.g. `$3.00`).
- `completion_price_per_1m`: Completion output price per 1M tokens (e.g. `$15.00`).
- `prompt_price_per_token`: Raw per-token Decimal.
- `completion_price_per_token`: Raw per-token Decimal.

### 5. `ModelBenchmark` (1:1 with `LLMModel`)
Evaluations, speed metrics, and Elo ratings.
- `intelligence_index`: Artificial Analysis Intelligence Index score (e.g. `78.0`).
- `coding_index`: Artificial Analysis Coding Index score (e.g. `76.5`).
- `agentic_index`: Function calling & tool use performance score.
- `tokens_per_second`: Live output throughput speed (tokens/sec).
- `time_to_first_token`: Initial latency response time (seconds).
- `arena_elo`: Media arena Elo rating (for image/video models).

### 6. `AppRanking` & `TaskClassification`
Analytics tracking real-world application usage:
- `AppRanking`: Top 50 AI applications ranked by monthly token consumption.
- `TaskClassification`: Task distribution percentages (Code Generation, Debugging, Workflow Execution, Multi-Turn Chat).

---

## ⚙️ Data Pipeline Synchronization (`sync_all`)

The `run_master_sync()` pipeline executes in six fault-tolerant bulk steps:

1. **Step 1: OpenRouter Sync (`openrouter_sync.py`)**
   - Fetches 410+ models from OpenRouter catalog.
   - Bulk inserts/updates `LLMModel`, `ModelSpecification`, `ModelPricing`, and provider relationships.
   - Ingests top app rankings and task shares.

2. **Step 2: models.dev Sync (`models_dev_sync.py`)**
   - Fetches free public catalog from `https://models.dev/api.json` (200+ providers, 8000+ models).
   - Bulk inserts/updates dedicated `modelsdev` table and creates missing `Provider` rows.
   - Lightly enriches matching main-catalog models (description, open-weight flag, context, pricing, tool/JSON capabilities).

3. **Step 3: Artificial Analysis Ingestion (`artificial_analysis_sync.py`)**
   - Fetches official benchmark evaluations from Artificial Analysis Data API (`/data/llms/models`).
   - Fetches media ratings for text-to-image, image-editing, text-to-video, and text-to-speech endpoints.
   - Bulk enriches matched database models with exact `intelligence_index`, `coding_index`, and `tokens_per_second` metrics.

4. **Step 4: Dedicated Raw Tables (`sync_dedicated_tables.py`)**
   - Ingests as-is source rows into `ormodels`, `orbench`, `aamodels`, and `aabanch`.
   - These four tables are the raw inputs for the merge and are browsable at `/ormodels`, `/orbench`, `/aamodels`, `/aabanch`.

5. **Step 5: Intelligent Null Backfill (`fill_nulls.py`)**
   - Scans all database models for any missing specifications, pricing, or benchmarks.
   - Uses context length heuristics, modality tags, and intelligence score interpolation to ensure **100% of models are fully populated**.

6. **Step 6: Merge into `rankindex` (`merge_rankindex.py`)**
   - Normalizes and joins the four source tables into the unified `rankindex` table.
   - Computes the composite **RankLLMs Index** plus overall/coding/reasoning/value ranks.
   - Serves the product-facing source-of-truth page at `/rankllms` (alias `/rankindex`) and `GET /api/v1/rankindex`.

---

## 🙏 Acknowledgments & Data Sources

| Source | Role | Link |
| :--- | :--- | :--- |
| OpenRouter | Model catalog, pricing, unified benchmarks | https://openrouter.ai |
| Artificial Analysis | Intelligence / coding / agentic indices | https://artificialanalysis.ai |
| models.dev | Provider & model metadata catalog | https://models.dev |
| RankLLMs | Product & leaderboards | https://rankllms.com |
| CodaiPro | Engineering & open-source maintenance | https://codaipro.com |
