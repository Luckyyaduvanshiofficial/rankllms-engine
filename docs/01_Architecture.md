# 🏗️ Architecture & Data Schema Guide

## Overview

RankLLMs Engine stores validated source snapshots and a canonical cross-source catalog in PostgreSQL. Public reads use the database snapshot; they do not call upstream APIs per visitor request.

---

## 🏛️ System Architecture Diagram

```
 +-------------------+    +----------------------+    +------------------+
 | OpenRouter        |    | Artificial Analysis  |    | models.dev       |
 | catalog + Data API|    | language + media API |    | model catalog    |
 +---------+---------+    +----------+-----------+    +--------+---------+
           |                         |                         |
           +-------------------------+-------------------------+
                                     v
                        validated source snapshots
                                     v
                     provider-scoped identity matching
                                     v
                  canonical rankindex + source provenance
                           /                    \
                          v                      v
                 Django Ninja API        server-rendered UI
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
- `context_length`: Maximum context window tokens when a source publishes one; otherwise null.
- `max_completion_tokens`: Maximum output generation window.
- `modality`: Input/output modality (e.g. `text->text`, `text+image->text`).
- `is_multimodal`, `supports_vision`, `supports_audio`, `supports_tools`: Nullable source-backed flags.

### 4. `ModelPricing` (1:1 with `LLMModel`)
Granular pricing normalized per 1 Million tokens in USD.
- `prompt_price_per_1m`: Prompt input price per 1M tokens in USD, or null when unknown.
- `completion_price_per_1m`: Completion output price per 1M tokens (e.g. `$15.00`).
- `prompt_price_per_token`: Raw per-token Decimal.
- `completion_price_per_token`: Raw per-token Decimal.

### 5. `ModelBenchmark` (1:1 with `LLMModel`)
Evaluations, speed metrics, and Elo ratings.
- `intelligence_index`: Artificial Analysis Intelligence Index (0–100) when reported.
- `coding_index`: Artificial Analysis Coding Index score (e.g. `76.5`).
- `agentic_index`: Artificial Analysis Agentic Index when reported; it is not inferred from tool-support flags.
- `tokens_per_second`: Live output throughput speed (tokens/sec).
- `time_to_first_token`: Initial latency response time (seconds).
- Missing benchmark values remain null. AA's documented Free media endpoints return route-specific ELO/confidence or task scores; they generally do not include pricing or sample counts. Those values are retained only when actually returned, alongside the source endpoint, in `AABench` and canonical `media_metrics`.

### 6. `AppRanking` & `TaskClassification`
Analytics tracking real-world application usage:
- `AppRanking`: Top 50 AI applications ranked by monthly token consumption.
- `TaskClassification`: Task distribution percentages (Code Generation, Debugging, Workflow Execution, Multi-Turn Chat).

---

## ⚙️ Data Pipeline Synchronization

The sync is source-scoped and preserves the last validated source snapshot when a fetch or schema check fails:

1. **Fetch** — OpenRouter (`/api/v1/models`, plus key-gated Data API datasets), Artificial Analysis (`/api/v2/language/models/free` by default, plus its documented free-tier media endpoints), and models.dev (`/api.json`). Requests use HTTPS host allowlists, bounded timeouts/retries, capped `Retry-After`, and schema checks.
2. **Source snapshots** — catalogs and benchmark records are upserted to `ormodels`, `orbench`, `aamodels`, `aabanch`, and `modelsdev`. Malformed/empty snapshots are rejected. Records missing from a validated response are marked inactive where retained, rather than silently erased.
3. **Normalization and matching** — provider-scoped IDs and explicit `canonical_model_id` values are preferred. Model versions and variant suffixes are retained. A source record with multiple possible matches is kept separate and reported as ambiguous.
4. **Enrichment** — fields are copied from sources only when known. Original IDs and raw JSON remain available in the canonical record. Pricing differences are recorded as merge conflicts with both source payloads retained.
5. **Ranking** — `rankindex` is rebuilt atomically from the valid source snapshots. Unknown components are omitted and remaining RankLLMs weights are renormalized; model-name estimates and synthetic ELO/SWE scores are not used.

The source tables are browsable at `/ormodels`, `/orbench`, `/aamodels`, `/aabanch`, and `/modelsdev`. The canonical snapshot is browsable at `/rankllms` and `/rankllms/models`, and exposed at `GET /api/v1/rankindex` and `GET /api/v1/leaderboard/rankindex`.

`python manage.py fill_nulls` remains as a compatibility command, but it is a **read-only completeness report**. It does not fill values. The staff-only `/settings/data-sync/` page stores sync history, source enable/timeout/retry settings, manual run status, previews, and a compact integrity report. Dry runs execute the same services inside one outer database transaction and roll back all writes.

Render enables the in-process scheduler at six hours. It runs only while the web instance is awake; Render free instances can sleep. Multi-instance deployments should use a single Render Cron Job or another external scheduler rather than enabling one scheduler per instance.

The AA Free language response includes Intelligence, Coding, Agentic, six Capability Indexes, four performance medians, and input/output/cache-hit/cache-write prices. RankLLMs stores those as nullable numeric fields and keeps the original response. Free pagination is requested with the `page` parameter; the API's response reports `pagination.has_more`/`total_pages`. Free media routes have different response metrics by task, so `media_metrics` preserves Speech-to-Text WER and Speech-to-Speech scores without treating them as ELO. See the [AA Data API docs](https://artificialanalysis.ai/data-api/docs) and [OpenAPI schema](https://artificialanalysis.ai/api/v2/openapi) for the upstream contract.

Artificial Analysis documents a shared Free-tier allowance of 100 requests per 24 hours. A complete sync calls eleven media routes plus each language-model page, so avoid repeated manual runs and check the captured rate-limit headers before increasing the six-hour schedule.

---

## 🙏 Acknowledgments & Data Sources

| Source | Role | Link |
| :--- | :--- | :--- |
| OpenRouter | Model catalog, pricing, unified benchmarks | https://openrouter.ai |
| Artificial Analysis | Independent language indices, benchmarks, media arena results, performance and pricing | https://artificialanalysis.ai |
| models.dev | Provider & model metadata catalog | https://models.dev |
| RankLLMs | Product & leaderboards | https://rankllms.com |
| CodaiPro | Engineering & open-source maintenance | https://codaipro.com |
