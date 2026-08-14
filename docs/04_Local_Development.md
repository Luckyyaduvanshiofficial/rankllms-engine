# 💻 Local Development & Command Line Reference

This guide explains how to set up, test, debug, and run data synchronization commands locally.

---

## 🛠️ Prerequisites

- **Python 3.12+**
- **Git**
- **Neon PostgreSQL Database** (or local PostgreSQL 15+)

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
2. `sync_artificial_analysis_data()` (LLM Benchmarks & Media Arena ELO)
3. `fill_all_nulls()` (Intelligent backfill for 100% data coverage)

```bash
python manage.py sync_all
```

### 2. `python manage.py sync_openrouter`
Runs OpenRouter model catalog & token-usage analytics ingestion only.
```bash
python manage.py sync_openrouter
```

### 3. `python manage.py sync_artificial_analysis`
Runs Artificial Analysis benchmark ratings and media model sync only.
```bash
python manage.py sync_artificial_analysis
```

### 4. `python manage.py fill_nulls`
Runs database-wide null and missing field backfill only.
```bash
python manage.py fill_nulls
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
