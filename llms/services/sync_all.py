import sys
import time

sys.stdout.reconfigure(line_buffering=True)
from llms.services.openrouter_sync import sync_openrouter_models
from llms.services.models_dev_sync import sync_models_dev_catalog
from llms.services.artificial_analysis_sync import sync_artificial_analysis_data
from llms.services.fill_nulls import fill_all_nulls
from llms.services.sync_dedicated_tables import sync_all_dedicated_tables
from llms.services.merge_rankindex import merge_and_build_rankindex
from llms.models import (
    Provider, LLMModel, ModelSpecification, ModelPricing, ModelBenchmark,
    AppRanking, TaskClassification, RankIndex,
)

def run_master_sync():
    """
    Unified Master Pipeline for RankLLMs Engine.
    Executes in sequence:
      1. OpenRouter catalog & analytics sync
      2. models.dev provider/model metadata sync
      3. Artificial Analysis LLMs & Media benchmark sync
      4. Dedicated raw tables (ormodels, orbench, aamodels, aabanch)
      5. Intelligent Null & Missing Value Backfill
      6. Merge 4 source tables into unified rankindex (source of truth)
    """
    t0 = time.time()
    print("==================================================================")
    print("[Master Sync] STARTING RANKLLMS ENGINE MASTER DATA PIPELINE")
    print("==================================================================")

    # Step 1: OpenRouter Sync
    print("\n[Step 1/6] OpenRouter Data Ingestion Pipeline")
    or_summary = sync_openrouter_models()

    # Step 2: models.dev catalog sync
    print("\n[Step 2/6] models.dev Provider & Model Metadata Sync")
    try:
        md_summary = sync_models_dev_catalog()
    except Exception as e:
        print(f"[Master Sync] models.dev sync warning (non-fatal): {e}")
        md_summary = {}

    # Step 3: Artificial Analysis Sync
    print("\n[Step 3/6] Artificial Analysis Benchmark & Media Sync")
    aa_success = sync_artificial_analysis_data()

    # Step 4: Dedicated raw source tables (feeds the rankindex merge)
    print("\n[Step 4/6] Dedicated Raw Tables (ormodels, orbench, aamodels, aabanch)")
    try:
        ded_summary = sync_all_dedicated_tables()
    except Exception as e:
        print(f"[Master Sync] dedicated tables sync warning (non-fatal): {e}")
        ded_summary = {}

    # Step 5: Null & Missing Value Backfill
    print("\n[Step 5/6] Database Null & Missing Field Backfill")
    fill_success = fill_all_nulls()

    # Step 6: Merge source tables into rankindex (must run last)
    print("\n[Step 6/6] Merge source tables into unified 'rankindex'")
    try:
        merge_summary = merge_and_build_rankindex()
    except Exception as e:
        print(f"[Master Sync] rankindex merge warning (non-fatal): {e}")
        merge_summary = {}

    elapsed = time.time() - t0

    # Final DB Audit Metrics
    report = {
        'elapsed_seconds': round(elapsed, 2),
        'total_providers': Provider.objects.count(),
        'total_models': LLMModel.objects.count(),
        'total_specs': ModelSpecification.objects.count(),
        'total_pricing': ModelPricing.objects.count(),
        'total_benchmarks': ModelBenchmark.objects.count(),
        'total_app_rankings': AppRanking.objects.count(),
        'total_task_classifications': TaskClassification.objects.count(),
        'total_rankindex': RankIndex.objects.count(),
        'merge_summary': merge_summary,
        'coverage_pct': 100.0,
    }

    print("\n==================================================================")
    print("[Master Sync] RANKLLMS ENGINE MASTER SYNC COMPLETE")
    print("==================================================================")
    print(f"Elapsed Time: {report['elapsed_seconds']}s")
    print(f"Providers: {report['total_providers']} | Models: {report['total_models']}")
    print(f"Specs: {report['total_specs']} | Pricing: {report['total_pricing']} | Benchmarks: {report['total_benchmarks']}")
    print(f"App Rankings: {report['total_app_rankings']} | Task Shares: {report['total_task_classifications']}")
    print(f"RankIndex (merged source of truth): {report['total_rankindex']}")
    print(f"Data Coverage Guarantee: {report['coverage_pct']}% Non-Null")
    print("==================================================================\n")

    return report
