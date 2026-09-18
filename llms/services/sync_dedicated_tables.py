import os
import requests
from decimal import Decimal
from django.conf import settings
from django.db import transaction
from llms.models import ORModel, ORBench, AAModel, AABench


def sync_all_dedicated_tables():
    """
    Ingests live API data into the 4 dedicated raw source tables:
    1. ormodels  (OpenRouter Models Catalog)
    2. orbench   (OpenRouter Unified Benchmarks: openrouter, design-arena, artificial-analysis)
    3. aamodels  (Artificial Analysis Models Catalog)
    4. aabanch   (Artificial Analysis Benchmark Evaluations & Telemetry)
    """
    summary = {}

    # ================= 1. SYNC ormodels =================
    print("[Sync] 1. Ingesting OpenRouter models into table 'ormodels'...")
    or_key = getattr(settings, 'OPENROUTER_API_KEY', '') or os.getenv('OPENROUTER_API_KEY', '')
    or_headers = {'User-Agent': 'RankLLMs-Engine/1.0'}
    if or_key:
        or_headers['Authorization'] = f'Bearer {or_key}'

    try:
        res = requests.get('https://openrouter.ai/api/v1/models', headers=or_headers, timeout=30)
        if res.status_code == 200:
            models_data = res.json().get('data', [])
            or_objects = []
            for m in models_data:
                mid = m.get('id', '')
                if not mid:
                    continue
                
                pricing = m.get('pricing') or {}
                prompt_p = Decimal(str(pricing.get('prompt') or 0.0))
                comp_p = Decimal(str(pricing.get('completion') or 0.0))
                prompt_1m = prompt_p * Decimal('1000000')
                comp_1m = comp_p * Decimal('1000000')
                is_free = (prompt_p == Decimal('0.0') and comp_p == Decimal('0.0'))

                author = mid.split('/')[0] if '/' in mid else ''

                or_objects.append(ORModel(
                    openrouter_id=mid,
                    name=m.get('name') or mid,
                    canonical_slug=m.get('canonical_slug') or '',
                    author=author,
                    description=m.get('description') or '',
                    context_length=int(m.get('context_length') or 0),
                    prompt_price_per_1m=prompt_1m,
                    completion_price_per_1m=comp_1m,
                    is_free=is_free,
                    architecture=m.get('architecture') or {},
                    top_provider=m.get('top_provider') or {},
                    pricing=pricing,
                    raw_json=m
                ))

            with transaction.atomic():
                ORModel.objects.all().delete()
                ORModel.objects.bulk_create(or_objects, batch_size=200)

            summary['ormodels_count'] = len(or_objects)
            print(f"[Sync] Saved {len(or_objects)} models into 'ormodels'.")
    except Exception as e:
        print(f"[Sync Error] ormodels: {e}")
        summary['ormodels_error'] = str(e)


    # ================= 2. SYNC orbench =================
    print("[Sync] 2. Ingesting OpenRouter benchmarks into table 'orbench'...")
    try:
        b_res = requests.get('https://openrouter.ai/api/v1/benchmarks', headers=or_headers, timeout=30)
        if b_res.status_code == 200:
            bench_data = b_res.json().get('data', [])
            bench_objects = []
            for b in bench_data:
                slug = b.get('model_permaslug') or b.get('slug') or ''
                name = b.get('display_name') or slug or 'Unknown'
                src = b.get('source') or 'unknown'

                bench_objects.append(ORBench(
                    model_permaslug=slug,
                    display_name=name,
                    source=src,
                    benchmark_type=b.get('benchmark_type') or '',
                    accuracy=float(b.get('accuracy')) if b.get('accuracy') is not None else None,
                    elo=float(b.get('elo')) if b.get('elo') is not None else None,
                    win_rate=float(b.get('win_rate')) if b.get('win_rate') is not None else None,
                    category=b.get('category') or '',
                    arena=b.get('arena') or '',
                    intelligence_index=float(b.get('intelligence_index')) if b.get('intelligence_index') is not None else None,
                    coding_index=float(b.get('coding_index')) if b.get('coding_index') is not None else None,
                    agentic_index=float(b.get('agentic_index')) if b.get('agentic_index') is not None else None,
                    avg_cost_per_task=float(b.get('avg_cost_per_task')) if b.get('avg_cost_per_task') is not None else None,
                    total_tasks=int(b.get('total_tasks')) if b.get('total_tasks') is not None else None,
                    tournament_stats=b.get('tournament_stats') or {},
                    pricing=b.get('pricing') or {},
                    raw_json=b
                ))

            with transaction.atomic():
                ORBench.objects.all().delete()
                ORBench.objects.bulk_create(bench_objects, batch_size=300)

            summary['orbench_count'] = len(bench_objects)
            print(f"[Sync] Saved {len(bench_objects)} benchmark runs into 'orbench'.")
    except Exception as e:
        print(f"[Sync Error] orbench: {e}")
        summary['orbench_error'] = str(e)


    # ================= 3. SYNC aamodels & aabanch =================
    print("[Sync] 3. Ingesting Artificial Analysis into 'aamodels' and 'aabanch'...")
    aa_key = getattr(settings, 'ARTIFICIAL_ANALYSIS_API_KEY', '') or os.getenv('ARTIFICIAL_ANALYSIS_API_KEY', '')
    aa_base = getattr(settings, 'ARTIFICIAL_ANALYSIS_API_URL', 'https://artificialanalysis.ai/api/v2')
    aa_headers = {'x-api-key': aa_key, 'Accept': 'application/json'}

    try:
        aa_models_res = requests.get(f"{aa_base}/data/llms/models", headers=aa_headers, timeout=30)
        if aa_models_res.status_code == 200:
            aa_data = aa_models_res.json()
            aa_models_list = aa_data if isinstance(aa_data, list) else aa_data.get('data', [])
            
            aamodel_objects = []
            aabench_objects = []

            for m in aa_models_list:
                slug = m.get('slug') or m.get('id') or ''
                if not slug:
                    continue

                name = m.get('name') or slug
                creator = m.get('creator') or {}
                creator_name = (creator.get('name') if isinstance(creator, dict) and creator.get('name') else None) or m.get('creator_name') or 'Independent'
                creator_slug = (creator.get('slug') if isinstance(creator, dict) and creator.get('slug') else None) or m.get('creator_slug') or ''

                # Pricing
                pricing = m.get('pricing') or {}
                prompt_1m = Decimal(str(pricing.get('prompt_token_cost_per_million') or pricing.get('prompt_price_per_1m') or 0.0))
                comp_1m = Decimal(str(pricing.get('completion_token_cost_per_million') or pricing.get('completion_price_per_1m') or 0.0))

                # Specs
                specs = m.get('specs') or {}
                ctx = int(specs.get('context_window') or m.get('context_length') or 0)
                max_out = int(specs.get('max_output_tokens') or 0) if specs.get('max_output_tokens') else None

                # Release date
                rel_date = None
                raw_date = m.get('release_date')
                if raw_date and isinstance(raw_date, str):
                    try:
                        rel_date = raw_date[:10]
                    except Exception:
                        pass

                aamodel_objects.append(AAModel(
                    slug=slug,
                    name=name,
                    creator_name=creator_name,
                    creator_slug=creator_slug,
                    release_date=rel_date,
                    model_type=m.get('model_type') or 'llm',
                    context_window=ctx,
                    max_output_tokens=max_out,
                    prompt_price_per_1m=prompt_1m,
                    completion_price_per_1m=comp_1m,
                    modalities=specs.get('modalities') or [],
                    raw_json=m
                ))

                # Evaluation Telemetry (All 17 benchmarks from Artificial Analysis API v2)
                evals = m.get('evaluations') or {}
                perf = m.get('performance') or {}

                intel = float(evals.get('artificial_analysis_intelligence_index') or evals.get('intelligence_index') or 0.0)
                coding = float(evals.get('artificial_analysis_coding_index') or evals.get('coding_index') or 0.0)
                math_idx = float(evals.get('artificial_analysis_math_index') or evals.get('math_index') or 0.0)
                tps = float(perf.get('median_output_tokens_per_second') or perf.get('tokens_per_second') or 0.0)
                ttft = float(perf.get('median_time_to_first_token_seconds') or perf.get('time_to_first_token') or 0.0)

                def _clean_score(key):
                    val = evals.get(key)
                    if val is None:
                        return None
                    try:
                        return float(val)
                    except (ValueError, TypeError):
                        return None

                aabench_objects.append(AABench(
                    model_slug=slug,
                    model_name=name,
                    creator_name=creator_name,
                    intelligence_index=intel,
                    coding_index=coding,
                    math_index=math_idx,
                    terminalbench_hard=_clean_score('terminalbench_hard'),
                    terminalbench_v2_1=_clean_score('terminalbench_v2_1'),
                    gpqa=_clean_score('gpqa'),
                    mmlu_pro=_clean_score('mmlu_pro'),
                    hle=_clean_score('hle'),
                    livecodebench=_clean_score('livecodebench'),
                    scicode=_clean_score('scicode'),
                    math_500=_clean_score('math_500'),
                    aime=_clean_score('aime'),
                    aime_25=_clean_score('aime_25'),
                    ifbench=_clean_score('ifbench'),
                    lcr=_clean_score('lcr'),
                    tau2=_clean_score('tau2'),
                    tau_banking=_clean_score('tau_banking'),
                    tokens_per_second=tps,
                    time_to_first_token=ttft,
                    raw_json=m
                ))

            with transaction.atomic():
                AAModel.objects.all().delete()
                AAModel.objects.bulk_create(aamodel_objects, batch_size=200)

                AABench.objects.all().delete()
                AABench.objects.bulk_create(aabench_objects, batch_size=200)

            summary['aamodels_count'] = len(aamodel_objects)
            summary['aabanch_count'] = len(aabench_objects)
            print(f"[Sync] Saved {len(aamodel_objects)} models into 'aamodels' and {len(aabench_objects)} evaluations into 'aabanch'.")
    except Exception as e:
        print(f"[Sync Error] AA sync: {e}")
        summary['aa_error'] = str(e)

    return summary
