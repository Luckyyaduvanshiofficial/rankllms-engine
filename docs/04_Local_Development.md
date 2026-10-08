# 💻 Local Development & Command Line Reference

This guide explains how to set up, test, debug, and run data synchronization commands locally.

---

## 🛠️ Prerequisites

- **Python 3.12+**
- **Git**
- **PostgreSQL** for production (Neon is supported). Local development and tests can use SQLite.

---

## 🚀 Step-by-Step Setup

```bash
# 1. Clone repo
git clone https://github.com/Luckyyaduvanshiofficial/rankllms-engine.git
cd rankllms-engine

# 2. Virtual Environment
python -m venv venv

# Windows activate:
.\venv\Scripts\activate

# Linux/macOS activate:
source venv/bin/activate

# 3. Dependencies
pip install -r requirements.txt

# 4. Environment
cp .env.example .env
```

---

## 📜 Available Django Management Commands

RankLLMs Engine includes specialized CLI management commands for data ingestion and backfill:

### 1. `python manage.py sync_all`
**Unified Master Pipeline Command**. Runs:
1. `sync_openrouter_models()` (Catalog & Pricing)
2. `sync_models_dev_catalog()` (models.dev provider/model metadata)
3. `sync_artificial_analysis_data()` (LLM Benchmarks & Media Arena ELO)
4. Atomic merge of validated source snapshots into `rankindex`.

```bash
python manage.py sync_all
```

### 2. `python manage.py sync_openrouter`
Runs OpenRouter model catalog & token-usage analytics ingestion only.
```bash
python manage.py sync_openrouter
```

### 3. `python manage.py sync_models_dev`
Runs models.dev catalog sync only (free public JSON — no API key).
```bash
python manage.py sync_models_dev
```

### 4. `python manage.py sync_artificial_analysis`
Runs Artificial Analysis benchmark ratings and media model sync only.
```bash
python manage.py sync_artificial_analysis
```

### 5. `python manage.py fill_nulls`
Reports missing catalog records without filling or estimating values.
```bash
python manage.py fill_nulls
```

The Settings page at `/settings/data-sync/` is the recommended manual control surface. It requires a Django staff account and includes normal sync, provider-specific sync, dry-run, source settings, history, and integrity counts.

### Test checks (isolated SQLite)

```bash
DJANGO_SETTINGS_MODULE=config.test_settings python manage.py check
DJANGO_SETTINGS_MODULE=config.test_settings python manage.py makemigrations --check --dry-run
DJANGO_SETTINGS_MODULE=config.test_settings python manage.py test
```

---

## 🧪 Testing DB & Query Verification

You can inspect database models interactively using Django shell:

```bash
python manage.py shell
```

```python
from llms.models import LLMModel, ModelSpecification, ModelBenchmark

# Count models
print("Total Models:", LLMModel.objects.count())

# Query top 5 coding models
top_coding = LLMModel.objects.select_related('benchmark').order_by('-benchmark__coding_index')[:5]
for m in top_coding:
    print(f"{m.name}: {m.benchmark.coding_index} (TPS: {m.benchmark.tokens_per_second})")
```
