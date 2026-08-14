import requests
import time
from django.conf import settings
from django.db import transaction
from django.utils.text import slugify
from llms.models import LLMModel, ModelBenchmark, Provider

def sync_artificial_analysis_data():
    """
    Ultra-fast Artificial Analysis Ingestion Service for RankLLMs Engine.
    Ingests LLMs, Text-to-Image, Image-Editing, Text-to-Video, and Text-to-Speech model benchmarks & Elo ratings.
    """
    api_key = getattr(settings, 'ARTIFICIAL_ANALYSIS_API_KEY', 'aa_DtsFXIHlTbHDWSJdfhNFKjlZfHKnAeBk')
    base_url = getattr(settings, 'ARTIFICIAL_ANALYSIS_API_URL', 'https://artificialanalysis.ai/api/v2')

    headers = {
        'x-api-key': api_key,
        'User-Agent': 'RankLLMs-Engine/1.0',
    }

    t0 = time.time()
    print("[Artificial Analysis Sync] Fetching catalog from Artificial Analysis API...")

    # 1. Fetch LLM Models Endpoint
    url = f"{base_url}/data/llms/models"
    models_list = []
    try:
        res = requests.get(url, headers=headers, timeout=15)
        res.raise_for_status()
        payload = res.json()
        models_list = payload.get('data', [])
    except Exception as e:
        print(f"[Artificial Analysis Sync] Warning fetching LLM models endpoint: {e}")

    print(f"[Artificial Analysis Sync] Received {len(models_list)} LLM models.")

    db_models = list(LLMModel.objects.all())
    existing_benchmarks = {b.model_id: b for b in ModelBenchmark.objects.all()}

    # Build smart lookup dictionaries
    lookup = {}
    for m in db_models:
        lookup[m.openrouter_id.lower().strip()] = m
        lookup[m.slug.lower().strip()] = m
        short_id = m.openrouter_id.split('/')[-1].lower().strip()
        lookup[short_id] = m
        clean_s = m.slug.replace('-', '').replace('_', '').lower().strip()
        lookup[clean_s] = m

    benchmarks_to_create = []
    benchmarks_to_update = []
    updated_count = 0

    for aa_model in models_list:
        aa_id = aa_model.get('id', '')
        aa_name = aa_model.get('name', '')
        aa_slug = aa_model.get('slug', '')
        evals = aa_model.get('evaluations', {}) or {}

        clean_aa_slug = aa_slug.lower().strip()
        clean_aa_id = aa_id.lower().strip()
        clean_aa_name = aa_name.lower().replace('-', '').replace('_', '').replace(' ', '')

        target_model = (
            lookup.get(clean_aa_slug) or
            lookup.get(clean_aa_id) or
            lookup.get(clean_aa_name)
        )

        if target_model:
            bm = existing_benchmarks.get(target_model.id)
            is_new = False
            if not bm:
                bm = ModelBenchmark(model=target_model)
                is_new = True

            intel = evals.get('artificial_analysis_intelligence_index')
            coding = evals.get('artificial_analysis_coding_index')
            tps = aa_model.get('median_output_tokens_per_second')
            ttft = aa_model.get('median_time_to_first_token_seconds')

            has_changes = False

            if intel is not None:
                bm.intelligence_index = float(intel)
                has_changes = True
            if coding is not None:
                bm.coding_index = float(coding)
                has_changes = True
            if tps is not None:
                bm.tokens_per_second = float(tps)
                has_changes = True
            if ttft is not None:
                bm.time_to_first_token = float(ttft)
                has_changes = True

            if has_changes:
                if is_new:
                    benchmarks_to_create.append(bm)
                else:
                    benchmarks_to_update.append(bm)
                updated_count += 1

    # 2. Fetch Media Endpoints
    media_endpoints = [
        ('/data/media/text-to-image', 'image'),
        ('/data/media/image-editing', 'image'),
        ('/data/media/text-to-video', 'video'),
        ('/data/media/image-to-video', 'video'),
        ('/data/media/text-to-speech', 'audio'),
    ]

    media_synced = 0
    provider_cache = {p.slug: p for p in Provider.objects.all()}
    existing_openrouter_ids = set(LLMModel.objects.values_list('openrouter_id', flat=True))

    media_models_to_create = []
    media_benchmarks_to_create = []

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

        if benchmarks_to_create:
            ModelBenchmark.objects.bulk_create(benchmarks_to_create, ignore_conflicts=True)
        if benchmarks_to_update:
            ModelBenchmark.objects.bulk_update(
                benchmarks_to_update,
                fields=['intelligence_index', 'coding_index', 'tokens_per_second', 'time_to_first_token'],
                batch_size=100
            )

    print(f"[Artificial Analysis Sync] Completed sync in {time.time()-t0:.2f}s. LLM Matched: {updated_count}, Media Created: {media_synced}.")
    return True
