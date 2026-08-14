import sys
import requests
import unicodedata
from datetime import datetime, timezone
from decimal import Decimal

sys.stdout.reconfigure(line_buffering=True)
from django.conf import settings
from django.db import transaction
from django.utils import timezone as django_timezone
from django.utils.text import slugify
from llms.models import (
    Provider, LLMModel, ModelSpecification, ModelPricing,
    ModelBenchmark, BenchmarkSnapshot, PricingHistory, DailyModelRanking, AppRanking, TaskClassification
)

PROVIDER_NAME_MAPPING = {
    'openai': 'OpenAI',
    'anthropic': 'Anthropic',
    'google': 'Google',
    'meta-llama': 'Meta Llama',
    'deepseek': 'DeepSeek',
    'mistralai': 'Mistral AI',
    'cohere': 'Cohere',
    'qwen': 'Qwen (Alibaba)',
    'amazon': 'Amazon Bedrock',
    'nvidia': 'NVIDIA',
    'microsoft': 'Microsoft',
    'ai21': 'AI21 Labs',
    'perplexity': 'Perplexity AI',
    'databricks': 'Databricks',
    'nousresearch': 'Nous Research',
    '01-ai': '01.AI',
}

OPEN_WEIGHT_KEYWORDS = [
    'deepseek', 'llama', 'qwen', 'mistral', 'gemma', 'nous', '01-ai',
    'phi', 'starcoder', 'codellama', 'yi', 'vicuna', 'openchat'
]


def sync_openrouter_models():
    """
    Ultra-fast OpenRouter Sync Service for RankLLMs Engine using Bulk Operations.
    Ensures 100% of LLMModels have corresponding ModelSpecification, ModelPricing, and ModelBenchmark records.
    """
    api_key = getattr(settings, 'OPENROUTER_API_KEY', '')

    headers = {'User-Agent': 'RankLLMs-Engine/1.0'}
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'

    print("[OpenRouter Sync] Fetching catalog and analytics endpoints...")

    models_res = requests.get('https://openrouter.ai/api/v1/models', headers=headers, timeout=30)
    models_res.raise_for_status()
    models_data = models_res.json().get('data', [])

    benchmarks_data = []
    try:
        b_res = requests.get('https://openrouter.ai/api/v1/benchmarks', headers=headers, timeout=15)
        if b_res.status_code == 200:
            benchmarks_data = b_res.json().get('data', [])
    except Exception as e:
        print(f"[OpenRouter Sync] Benchmark fetch warning: {e}")

    app_rankings_data = []
    try:
        app_res = requests.get('https://openrouter.ai/api/v1/datasets/app-rankings', headers=headers, timeout=15)
        if app_res.status_code == 200:
            app_rankings_data = app_res.json().get('data', [])
    except Exception as e:
        print(f"[OpenRouter Sync] App rankings fetch warning: {e}")

    task_classifications_data = []
    try:
        tc_res = requests.get('https://openrouter.ai/api/v1/classifications/task', headers=headers, timeout=15)
        if tc_res.status_code == 200:
            task_classifications_data = tc_res.json().get('data', {}).get('classifications', [])
    except Exception as e:
        print(f"[OpenRouter Sync] Task classification fetch warning: {e}")

    benchmark_map = {}
    for b in benchmarks_data:
        permaslug = b.get('model_permaslug')
        if permaslug:
            benchmark_map[permaslug.lower()] = b

    now_dt = django_timezone.now()
    created_count = 0
    updated_count = 0
    processed_ids = set()

    print(f"[OpenRouter Sync] Processing {len(models_data)} models...")

    # Phase 1: Providers
    provider_cache = {p.slug.strip().lower(): p for p in Provider.objects.all()}
    for item in models_data:
        openrouter_id = item.get('id')
        if not openrouter_id:
            continue
        raw_provider = openrouter_id.split('/')[0] if '/' in openrouter_id else 'unknown'
        provider_slug = slugify(raw_provider).lower()
        if provider_slug not in provider_cache:
            provider_name = PROVIDER_NAME_MAPPING.get(raw_provider.lower(), raw_provider.replace('-', ' ').title())
            provider, _ = Provider.objects.get_or_create(
                slug=provider_slug,
                defaults={'name': provider_name, 'description': f'{provider_name} LLMs'}
            )
            provider_cache[provider_slug] = provider

    # Phase 2: LLMModel Upserts
    existing_models = {m.openrouter_id.lower().strip(): m for m in LLMModel.objects.all()}
    used_slugs = set(LLMModel.objects.values_list('slug', flat=True))

    models_to_create = []
    models_to_update = []
    model_payloads = []

    for item in models_data:
        openrouter_id = item.get('id')
        if not openrouter_id:
            continue

        openrouter_id_clean = unicodedata.normalize('NFKC', str(openrouter_id)).strip()
        openrouter_key = openrouter_id_clean.lower()
        if openrouter_key in processed_ids:
            continue
        processed_ids.add(openrouter_key)

        raw_provider = openrouter_id_clean.split('/')[0] if '/' in openrouter_id_clean else 'unknown'
        provider_slug = slugify(raw_provider).lower()
        provider = provider_cache.get(provider_slug)

        name = item.get('name') or openrouter_id_clean
        description = item.get('description', '')
        created_timestamp = item.get('created')
        created_at_openrouter = None
        if created_timestamp:
            try:
                created_at_openrouter = datetime.fromtimestamp(created_timestamp, tz=timezone.utc)
            except Exception:
                pass

        pricing = item.get('pricing') or {}
        try:
            prompt_token_price = Decimal(str(pricing.get('prompt', '0') or '0'))
        except Exception:
            prompt_token_price = Decimal('0')
        try:
            completion_token_price = Decimal(str(pricing.get('completion', '0') or '0'))
        except Exception:
            completion_token_price = Decimal('0')
        try:
            image_price = Decimal(str(pricing.get('image', '0') or '0'))
        except Exception:
            image_price = Decimal('0')
        try:
            request_price = Decimal(str(pricing.get('request', '0') or '0'))
        except Exception:
            request_price = Decimal('0')

        prompt_1m = (prompt_token_price * Decimal('1000000')).quantize(Decimal('0.000001'))
        completion_1m = (completion_token_price * Decimal('1000000')).quantize(Decimal('0.000001'))
        is_free = (prompt_1m == Decimal('0')) and (completion_1m == Decimal('0'))

        is_open_weight = any(k in openrouter_key for k in OPEN_WEIGHT_KEYWORDS)
        license_type = 'Open Weight / Open Source' if is_open_weight else 'Proprietary'

        base_slug = slugify(openrouter_id_clean.replace('/', '-'))
        model_obj = existing_models.get(openrouter_key)

        if not model_obj:
            clean_slug = base_slug
            counter = 1
            while clean_slug in used_slugs:
                clean_slug = f"{base_slug}-{counter}"
                counter += 1
            used_slugs.add(clean_slug)

            model_obj = LLMModel(
                openrouter_id=openrouter_id_clean,
                slug=clean_slug,
                name=name,
                provider=provider,
                category='llm',
                description=description,
                is_open_weight=is_open_weight,
                license=license_type,
                is_active=True,
                is_free=is_free,
                created_at_openrouter=created_at_openrouter,
                raw_json=item,
            )
            models_to_create.append(model_obj)
            created_count += 1
        else:
            model_obj.name = name
            model_obj.provider = provider
            model_obj.description = description
            model_obj.is_open_weight = is_open_weight
            model_obj.is_free = is_free
            model_obj.raw_json = item
            models_to_update.append(model_obj)
            updated_count += 1

        b_info = benchmark_map.get(openrouter_key) or {}

        model_payloads.append({
            'openrouter_key': openrouter_key,
            'context_length': item.get('context_length', 0) or 0,
            'max_completion_tokens': (item.get('top_provider') or {}).get('max_completion_tokens'),
            'modality': (item.get('architecture') or {}).get('modality', '') or '',
            'tokenizer': (item.get('architecture') or {}).get('tokenizer', '') or '',
            'instruct_type': (item.get('architecture') or {}).get('instruct_type'),
            'is_multimodal': 'image' in ((item.get('architecture') or {}).get('modality', '') or '').lower(),
            'supports_vision': 'image' in ((item.get('architecture') or {}).get('modality', '') or '').lower() or 'vision' in description.lower(),
            'supports_audio': 'audio' in ((item.get('architecture') or {}).get('modality', '') or '').lower(),
            'supports_tools': 'tool' in description.lower() or 'function' in description.lower(),
            'prompt_token_price': prompt_token_price,
            'completion_token_price': completion_token_price,
            'image_price': image_price,
            'request_price': request_price,
            'prompt_1m': prompt_1m,
            'completion_1m': completion_1m,
            'intel_idx': float(b_info.get('intelligence_index') or 0.0),
            'code_idx': float(b_info.get('coding_index') or 0.0),
            'agent_idx': float(b_info.get('agentic_index') or 0.0),
        })

    if models_to_create:
        LLMModel.objects.bulk_create(models_to_create, batch_size=100)
    if models_to_update:
        LLMModel.objects.bulk_update(models_to_update, fields=['name', 'provider', 'description', 'is_open_weight', 'is_free', 'raw_json'], batch_size=100)

    # Re-fetch models dict with populated IDs
    all_models = {m.openrouter_id.lower().strip(): m for m in LLMModel.objects.all()}

    existing_specs = {s.model_id: s for s in ModelSpecification.objects.all()}
    existing_pricing = {p.model_id: p for p in ModelPricing.objects.all()}
    existing_benchmarks = {b.model_id: b for b in ModelBenchmark.objects.all()}

    specs_to_create = []
    specs_to_update = []
    pricing_to_create = []
    pricing_to_update = []
    benchmarks_to_create = []
    benchmarks_to_update = []

    for p in model_payloads:
        model_obj = all_models.get(p['openrouter_key'])
        if not model_obj:
            continue

        # Spec
        sp = existing_specs.get(model_obj.id)
        if not sp:
            specs_to_create.append(ModelSpecification(
                model=model_obj,
                context_length=p['context_length'],
                max_completion_tokens=p['max_completion_tokens'],
                modality=p['modality'],
                tokenizer=p['tokenizer'],
                instruct_type=p['instruct_type'],
                is_multimodal=p['is_multimodal'],
                supports_vision=p['supports_vision'],
                supports_audio=p['supports_audio'],
                supports_tools=p['supports_tools'],
            ))
        else:
            sp.context_length = p['context_length']
            sp.max_completion_tokens = p['max_completion_tokens']
            sp.modality = p['modality']
            sp.tokenizer = p['tokenizer']
            sp.instruct_type = p['instruct_type']
            sp.is_multimodal = p['is_multimodal']
            sp.supports_vision = p['supports_vision']
            sp.supports_audio = p['supports_audio']
            sp.supports_tools = p['supports_tools']
            specs_to_update.append(sp)

        # Pricing
        pr = existing_pricing.get(model_obj.id)
        if not pr:
            pricing_to_create.append(ModelPricing(
                model=model_obj,
                prompt_price_per_token=p['prompt_token_price'],
                completion_price_per_token=p['completion_token_price'],
                image_price=p['image_price'],
                request_price=p['request_price'],
                prompt_price_per_1m=p['prompt_1m'],
                completion_price_per_1m=p['completion_1m'],
            ))
        else:
            pr.prompt_price_per_token = p['prompt_token_price']
            pr.completion_price_per_token = p['completion_token_price']
            pr.image_price = p['image_price']
            pr.request_price = p['request_price']
            pr.prompt_price_per_1m = p['prompt_1m']
            pr.completion_price_per_1m = p['completion_1m']
            pricing_to_update.append(pr)

        # Benchmark
        bm = existing_benchmarks.get(model_obj.id)
        if not bm:
            benchmarks_to_create.append(ModelBenchmark(
                model=model_obj,
                intelligence_index=p['intel_idx'],
                coding_index=p['code_idx'],
                agentic_index=p['agent_idx'],
            ))
        else:
            if p['intel_idx'] > 0:
                bm.intelligence_index = p['intel_idx']
            if p['code_idx'] > 0:
                bm.coding_index = p['code_idx']
            if p['agent_idx'] > 0:
                bm.agentic_index = p['agent_idx']
            benchmarks_to_update.append(bm)

    if specs_to_create:
        ModelSpecification.objects.bulk_create(specs_to_create, batch_size=100)
    if specs_to_update:
        ModelSpecification.objects.bulk_update(specs_to_update, fields=['context_length', 'max_completion_tokens', 'modality', 'tokenizer', 'instruct_type', 'is_multimodal', 'supports_vision', 'supports_audio', 'supports_tools'], batch_size=100)

    if pricing_to_create:
        ModelPricing.objects.bulk_create(pricing_to_create, batch_size=100)
    if pricing_to_update:
        ModelPricing.objects.bulk_update(pricing_to_update, fields=['prompt_price_per_token', 'completion_price_per_token', 'image_price', 'request_price', 'prompt_price_per_1m', 'completion_price_per_1m'], batch_size=100)

    if benchmarks_to_create:
        ModelBenchmark.objects.bulk_create(benchmarks_to_create, batch_size=100)
    if benchmarks_to_update:
        ModelBenchmark.objects.bulk_update(benchmarks_to_update, fields=['intelligence_index', 'coding_index', 'agentic_index'], batch_size=100)

    # Process App Rankings
    for app in app_rankings_data:
        app_id = app.get('app_id')
        if app_id:
            AppRanking.objects.update_or_create(
                app_id=app_id,
                defaults={
                    'app_name': app.get('app_name', 'Unknown'),
                    'rank': app.get('rank', 999),
                    'total_tokens': int(app.get('total_tokens', 0) or 0),
                    'total_requests': int(app.get('total_requests', 0) or 0),
                }
            )

    # Process Task Classifications
    for tc in task_classifications_data:
        tag = tc.get('tag')
        if tag:
            TaskClassification.objects.update_or_create(
                tag=tag,
                defaults={
                    'display_name': tc.get('display_name', tag),
                    'macro_category': tc.get('macro_category', ''),
                    'usage_share': float(tc.get('usage_share', 0.0) or 0.0),
                    'token_share': float(tc.get('token_share', 0.0) or 0.0),
                    'top_models_share': tc.get('models', []),
                }
            )

    summary = {
        'total_fetched': len(models_data),
        'created': created_count,
        'updated': updated_count,
        'total_providers': len(provider_cache),
    }

    print(f"[OpenRouter Sync] Completed successfully: {created_count} created, {updated_count} updated.")
    return summary
