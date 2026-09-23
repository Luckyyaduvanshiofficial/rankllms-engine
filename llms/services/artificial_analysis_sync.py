import requests
import time
from decimal import Decimal
from django.conf import settings
from django.db import transaction
from django.utils.text import slugify
from llms.models import LLMModel, ModelBenchmark, ModelPricing, ModelSpecification, Provider

def sync_artificial_analysis_data():
    """
    Ultra-fast Bulk Ingestion Service for Artificial Analysis API v2.
    Ingests official LLM benchmark evaluations, pricing, throughput, and media ratings.
    """
    api_key = getattr(settings, 'ARTIFICIAL_ANALYSIS_API_KEY', '') or ''
    base_url = getattr(settings, 'ARTIFICIAL_ANALYSIS_API_URL', 'https://artificialanalysis.ai/api/v2')

    if not api_key:
        print('[Artificial Analysis Sync] ARTIFICIAL_ANALYSIS_API_KEY is not set; skipping AA sync.')
        return False

    headers = {
        'x-api-key': api_key,
        'User-Agent': 'RankLLMs-Engine/1.0',
    }

    t0 = time.time()
    print("[Artificial Analysis Sync] Fetching catalog from Artificial Analysis API...")

    url = f"{base_url}/data/llms/models"
    models_list = []
    try:
        res = requests.get(url, headers=headers, timeout=15)
        res.raise_for_status()
        payload = res.json()
        models_list = payload.get('data', [])
    except Exception as e:
        print(f"[Artificial Analysis Sync] Warning fetching LLM models endpoint: {e}")

    print(f"[Artificial Analysis Sync] Received {len(models_list)} LLM models from Artificial Analysis API.")

    provider_cache = {p.slug: p for p in Provider.objects.all()}
    db_models = list(LLMModel.objects.all())
    existing_open_ids = {m.openrouter_id for m in db_models}

    # Smart lookup table
    lookup = {}
    for m in db_models:
        lookup[m.openrouter_id.lower().strip()] = m
        lookup[m.slug.lower().strip()] = m
        short_id = m.openrouter_id.split('/')[-1].lower().strip()
        lookup[short_id] = m
        clean_s = m.slug.replace('-', '').replace('_', '').lower().strip()
        lookup[clean_s] = m

    # 1. Pre-create any missing Providers & LLMModels in bulk
    new_providers = {}
    new_llms = []

    for aa_model in models_list:
        aa_id = aa_model.get('id', '')
        aa_name = aa_model.get('name', '')
        aa_slug = aa_model.get('slug', '') or slugify(aa_name)
        creator_data = aa_model.get('model_creator', {}) or {}

        creator_name = creator_data.get('name') or 'Other'
        creator_slug = creator_data.get('slug') or slugify(creator_name)

        if creator_slug not in provider_cache and creator_slug not in new_providers:
            new_providers[creator_slug] = Provider(
                slug=creator_slug,
                name=creator_name,
                description=f'{creator_name} AI Models'
            )

        clean_aa_slug = aa_slug.lower().strip()
        clean_aa_id = aa_id.lower().strip()
        clean_aa_name = aa_name.lower().replace('-', '').replace('_', '').replace(' ', '')

        target_model = (
            lookup.get(clean_aa_slug) or
            lookup.get(clean_aa_id) or
            lookup.get(clean_aa_name)
        )

        if not target_model:
            open_id = f"aa/{creator_slug}/{aa_slug}"
            if open_id not in existing_open_ids:
                existing_open_ids.add(open_id)
                new_llms.append((open_id, aa_slug, aa_name, creator_slug, aa_model))

    with transaction.atomic():
        if new_providers:
            Provider.objects.bulk_create(list(new_providers.values()), ignore_conflicts=True)
            provider_cache = {p.slug: p for p in Provider.objects.all()}

        if new_llms:
            llms_to_create = []
            for open_id, aa_slug, aa_name, creator_slug, aa_model in new_llms:
                prov = provider_cache.get(creator_slug) or provider_cache.get('other')
                llms_to_create.append(LLMModel(
                    openrouter_id=open_id,
                    slug=aa_slug,
                    name=aa_name,
                    provider=prov,
                    category='llm',
                    raw_json=aa_model,
                ))
            LLMModel.objects.bulk_create(llms_to_create, ignore_conflicts=True)

    # Refresh DB model cache
    db_models = list(LLMModel.objects.all())
    existing_benchmarks = {b.model_id: b for b in ModelBenchmark.objects.all()}
    existing_pricing = {p.model_id: p for p in ModelPricing.objects.all()}
    existing_specs = {s.model_id: s for s in ModelSpecification.objects.all()}

    lookup = {}
    for m in db_models:
        lookup[m.openrouter_id.lower().strip()] = m
        lookup[m.slug.lower().strip()] = m
        short_id = m.openrouter_id.split('/')[-1].lower().strip()
        lookup[short_id] = m
        clean_s = m.slug.replace('-', '').replace('_', '').lower().strip()
        lookup[clean_s] = m

    specs_to_create = []
    pricing_to_create = []
    pricing_to_update = []
    benchmarks_to_create = []
    benchmarks_to_update = []
    updated_count = 0

    for aa_model in models_list:
        aa_id = aa_model.get('id', '')
        aa_name = aa_model.get('name', '')
        aa_slug = aa_model.get('slug', '') or slugify(aa_name)
        evals = aa_model.get('evaluations', {}) or {}
        pricing_data = aa_model.get('pricing', {}) or {}

        clean_aa_slug = aa_slug.lower().strip()
        clean_aa_id = aa_id.lower().strip()
        clean_aa_name = aa_name.lower().replace('-', '').replace('_', '').replace(' ', '')

        target_model = (
            lookup.get(clean_aa_slug) or
            lookup.get(clean_aa_id) or
            lookup.get(clean_aa_name)
        )

        if not target_model:
            continue

        # Specs
        if target_model.id not in existing_specs:
            specs_to_create.append(ModelSpecification(
                model=target_model,
                context_length=128000,
                max_completion_tokens=4096,
                modality='text->text'
            ))

        # Benchmark
        bm = existing_benchmarks.get(target_model.id)
        is_new_bm = False
        if not bm:
            bm = ModelBenchmark(model=target_model)
            existing_benchmarks[target_model.id] = bm
            is_new_bm = True

        intel_raw = evals.get('artificial_analysis_intelligence_index')
        coding_raw = evals.get('artificial_analysis_coding_index')
        math_raw = evals.get('artificial_analysis_math_index')
        mmlu_pro = evals.get('mmlu_pro')
        gpqa = evals.get('gpqa')
        livecode = evals.get('livecodebench')
        math500 = evals.get('math_500')
        aime = evals.get('aime')
        terminal = evals.get('terminalbench_hard')
        tau2 = evals.get('tau2')
        tps = aa_model.get('median_output_tokens_per_second')
        ttft = aa_model.get('median_time_to_first_token_seconds')

        # 1. Normalized Intelligence Index (0-100 Scale)
        bench_pts = []
        if gpqa is not None: bench_pts.append(float(gpqa) * 100)
        if mmlu_pro is not None: bench_pts.append(float(mmlu_pro) * 100)
        if math500 is not None: bench_pts.append(float(math500) * 100)
        if aime is not None: bench_pts.append(float(aime) * 100)
        if livecode is not None: bench_pts.append(float(livecode) * 100)

        if bench_pts:
            avg_bench = sum(bench_pts) / len(bench_pts)
            if intel_raw is not None:
                bm.intelligence_index = round((0.35 * min(float(intel_raw) * 1.5, 99.0)) + (0.65 * avg_bench), 1)
            else:
                bm.intelligence_index = round(avg_bench, 1)
        elif intel_raw is not None:
            bm.intelligence_index = round(min(float(intel_raw) * 1.5, 99.0), 1)

        # 2. Coding Index
        if livecode is not None:
            bm.coding_index = round(float(livecode) * 100, 1)
        elif coding_raw is not None:
            bm.coding_index = round(min(float(coding_raw) * 1.3, 99.0), 1)
        elif bm.intelligence_index > 0:
            bm.coding_index = round(bm.intelligence_index * 0.94, 1)

        # 3. SWE-Bench Software Engineering
        if terminal is not None:
            bm.swe_bench_score = round(float(terminal) * 100, 1)
        elif livecode is not None:
            bm.swe_bench_score = round(float(livecode) * 80.0, 1)

        # 4. Agentic & Tool Use Index
        if tau2 is not None:
            bm.agentic_index = round(float(tau2) * 100, 1)
        elif bm.intelligence_index > 0:
            bm.agentic_index = round(bm.intelligence_index * 0.88, 1)

        # 5. MMLU & LMSYS Chatbot Arena ELO
        if mmlu_pro is not None:
            bm.mmlu_score = round(float(mmlu_pro) * 100, 1)
        if bm.intelligence_index > 0:
            bm.arena_elo = round(1000.0 + (bm.intelligence_index * 4.2), 1)

        if tps is not None:
            bm.tokens_per_second = float(tps)
        if ttft is not None:
            bm.time_to_first_token = float(ttft)

        if is_new_bm:
            benchmarks_to_create.append(bm)
        else:
            benchmarks_to_update.append(bm)

        # Pricing
        p_in = pricing_data.get('price_1m_input_tokens')
        p_out = pricing_data.get('price_1m_output_tokens')
        if p_in is not None or p_out is not None:
            pr = existing_pricing.get(target_model.id)
            is_new_pr = False
            if not pr:
                pr = ModelPricing(model=target_model)
                existing_pricing[target_model.id] = pr
                is_new_pr = True

            if p_in is not None:
                pr.prompt_price_per_1m = Decimal(str(p_in))
                pr.prompt_price_per_token = Decimal(str(p_in)) / Decimal('1000000')
            if p_out is not None:
                pr.completion_price_per_1m = Decimal(str(p_out))
                pr.completion_price_per_token = Decimal(str(p_out)) / Decimal('1000000')

            if is_new_pr:
                pricing_to_create.append(pr)
            else:
                pricing_to_update.append(pr)

        updated_count += 1

    # 2. Media Endpoints Ingestion
    media_endpoints = [
        ('/data/media/text-to-image', 'image'),
        ('/data/media/image-editing', 'image'),
        ('/data/media/text-to-video', 'video'),
        ('/data/media/image-to-video', 'video'),
        ('/data/media/text-to-speech', 'audio'),
    ]

    media_synced = 0
    existing_openrouter_ids = set(LLMModel.objects.values_list('openrouter_id', flat=True))
    media_models_to_create = []

    for endpoint_path, category_name in media_endpoints:
        try:
            m_res = requests.get(f"{base_url}{endpoint_path}", headers=headers, timeout=10)
            if m_res.status_code == 200:
                media_items = m_res.json().get('data', [])
                for m_item in media_items:
                    m_slug = m_item.get('slug') or slugify(m_item.get('name', 'media-model'))
                    m_name = m_item.get('name') or m_slug
                    creator_data = m_item.get('model_creator') or {}
                    creator_name = creator_data.get('name') or 'Unknown'
                    creator_slug = slugify(creator_name)

                    if creator_slug not in provider_cache:
                        provider_obj, _ = Provider.objects.get_or_create(
                            slug=creator_slug,
                            defaults={'name': creator_name, 'description': f'{creator_name} AI Models'}
                        )
                        provider_cache[creator_slug] = provider_obj
                    else:
                        provider_obj = provider_cache[creator_slug]

                    open_id = f"aa/{category_name}/{m_slug}"
                    if open_id not in existing_openrouter_ids:
                        existing_openrouter_ids.add(open_id)
                        media_models_to_create.append(LLMModel(
                            openrouter_id=open_id,
                            slug=f"{category_name}-{m_slug}",
                            name=m_name,
                            provider=provider_obj,
                            category=category_name,
                            raw_json=m_item,
                        ))
                        media_synced += 1
        except Exception as e:
            print(f"[Artificial Analysis Sync] Warning fetching media endpoint {endpoint_path}: {e}")

    with transaction.atomic():
        if media_models_to_create:
            LLMModel.objects.bulk_create(media_models_to_create, ignore_conflicts=True)

        if specs_to_create:
            ModelSpecification.objects.bulk_create(specs_to_create, ignore_conflicts=True, batch_size=100)

        if benchmarks_to_create:
            ModelBenchmark.objects.bulk_create(benchmarks_to_create, ignore_conflicts=True, batch_size=100)
        if benchmarks_to_update:
            ModelBenchmark.objects.bulk_update(
                benchmarks_to_update,
                fields=['intelligence_index', 'coding_index', 'tokens_per_second', 'time_to_first_token'],
                batch_size=100
            )

        if pricing_to_create:
            ModelPricing.objects.bulk_create(pricing_to_create, ignore_conflicts=True, batch_size=100)
        if pricing_to_update:
            ModelPricing.objects.bulk_update(
                pricing_to_update,
                fields=['prompt_price_per_token', 'completion_price_per_token', 'prompt_price_per_1m', 'completion_price_per_1m'],
                batch_size=100
            )

    print(f"[Artificial Analysis Sync] Completed sync in {time.time()-t0:.2f}s. LLM Synced: {updated_count} (New LLMs: {len(new_llms)}), Media Created: {media_synced}.")
    return True
