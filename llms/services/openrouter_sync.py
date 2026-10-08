import unicodedata
from datetime import datetime, timezone
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone as django_timezone
from django.utils.text import slugify
from llms.models import (
    Provider, LLMModel, ModelSpecification, ModelPricing,
    ModelBenchmark, BenchmarkSnapshot, PricingHistory, DailyModelRanking, AppRanking, TaskClassification
)
from llms.services.source_http import UpstreamSourceError, fetch_json, require_list
from llms.services.sync_dedicated_tables import sync_openrouter_tables


def _optional_decimal(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (TypeError, ValueError, ArithmeticError):
        return None
    if not parsed.is_finite() or parsed < 0:
        return None
    return parsed


def _optional_int(value):
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if parsed > 0 else None


def _optional_score(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if 0 <= parsed <= 100 else None

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

def fetch_openrouter_snapshot():
    """Fetch and validate the OpenRouter catalog and configured data feeds."""
    api_key = getattr(settings, 'OPENROUTER_API_KEY', '')

    headers = {'User-Agent': 'RankLLMs-Engine/1.0'}
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'

    print("[OpenRouter Sync] Fetching catalog and authenticated datasets...")
    models_payload = fetch_json(
        'openrouter',
        getattr(settings, 'OPENROUTER_API_URL', 'https://openrouter.ai/api/v1/models'),
        headers=headers,
    )
    models_data = require_list(models_payload, source='openrouter', path=('data',))
    total_models_received = len(models_data)
    malformed_models = sum(
        1 for item in models_data
        if not isinstance(item, dict) or not isinstance(item.get('id'), str) or not item.get('id').strip()
    )
    if malformed_models > max(0, int(len(models_data) * 0.1)):
        raise UpstreamSourceError('openrouter', 'Too many OpenRouter model records are missing valid IDs; existing data was kept.')
    models_data = [
        item for item in models_data
        if isinstance(item, dict) and isinstance(item.get('id'), str) and item.get('id').strip()
    ]

    warnings = []
    benchmarks_data = []
    benchmarks_snapshot_valid = False
    app_rankings_data = []
    task_classifications_data = []
    if api_key:
        optional_endpoints = (
            ('benchmarks', 'https://openrouter.ai/api/v1/benchmarks', ('data',)),
            ('app_rankings', 'https://openrouter.ai/api/v1/datasets/app-rankings', ('data',)),
            ('task_classifications', 'https://openrouter.ai/api/v1/classifications/task', ('data', 'classifications')),
        )
        for label, url, path in optional_endpoints:
            try:
                payload = fetch_json('openrouter', url, headers=headers)
                rows = require_list(payload, source='openrouter', path=path, allow_empty=True)
                if label == 'benchmarks':
                    benchmarks_data = rows
                    benchmarks_snapshot_valid = True
                elif label == 'app_rankings':
                    app_rankings_data = rows
                else:
                    task_classifications_data = rows
            except UpstreamSourceError as exc:
                warnings.append(f'{label}: {exc}')
                print(f"[OpenRouter Sync] {label} warning: {exc}")
    else:
        warnings.append('OPENROUTER_API_KEY missing; authenticated datasets were preserved.')


    return {
        'models_data': models_data,
        'total_models_received': total_models_received,
        'api_key': api_key,
        'benchmarks_data': benchmarks_data,
        'benchmarks_snapshot_valid': benchmarks_snapshot_valid,
        'app_rankings_data': app_rankings_data,
        'task_classifications_data': task_classifications_data,
        'warnings': warnings,
    }


def sync_openrouter_models(snapshot=None):
    """Fetch upstream data before opening the atomic database write phase."""
    snapshot = snapshot if snapshot is not None else fetch_openrouter_snapshot()
    return _sync_openrouter_snapshot(**snapshot)


@transaction.atomic
def _sync_openrouter_snapshot(
    *,
    models_data,
    total_models_received,
    api_key,
    benchmarks_data,
    benchmarks_snapshot_valid,
    app_rankings_data,
    task_classifications_data,
    warnings,
):
    benchmark_map = {}
    for b in benchmarks_data:
        if not isinstance(b, dict):
            continue
        permaslug = b.get('model_permaslug')
        if permaslug and b.get('source') == 'artificial-analysis':
            benchmark_map[permaslug.lower()] = b

    now_dt = django_timezone.now()
    created_count = 0
    updated_count = 0
    processed_ids = set()

    print(f"[OpenRouter Sync] Processing {len(models_data)} models...")

    # Phase 1: Providers (Bulk)
    provider_cache = {p.slug.strip().lower(): p for p in Provider.objects.all()}
    new_providers = {}
    for item in models_data:
        openrouter_id = item.get('id')
        if not openrouter_id:
            continue
        raw_provider = openrouter_id.split('/')[0] if '/' in openrouter_id else 'unknown'
        provider_slug = slugify(raw_provider).lower()
        if provider_slug not in provider_cache and provider_slug not in new_providers:
            provider_name = PROVIDER_NAME_MAPPING.get(raw_provider.lower(), raw_provider.replace('-', ' ').title())
            new_providers[provider_slug] = Provider(
                slug=provider_slug,
                name=provider_name,
                description=f'{provider_name} AI Models'
            )

    if new_providers:
        Provider.objects.bulk_create(list(new_providers.values()), ignore_conflicts=True)
        provider_cache = {p.slug.strip().lower(): p for p in Provider.objects.all()}

    # Phase 2: LLMModel Upserts
    existing_models = {m.openrouter_id.lower().strip(): m for m in LLMModel.objects.all()}
    used_slugs = set(LLMModel.objects.values_list('slug', flat=True))

    models_to_create = []
    models_to_update = []
    model_payloads = []
    deactivated_count = 0

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

        architecture = item.get('architecture') if isinstance(item.get('architecture'), dict) else {}
        modality = architecture.get('modality') or ''
        modality_parts = modality.lower().replace('->', '+').split('+') if modality else []
        output_modality = modality.lower().split('->')[-1] if modality else ''
        explicit_category = str(item.get('category') or item.get('type') or '').lower()
        if explicit_category in {'llm', 'image', 'video', 'audio', 'embedding'}:
            category = explicit_category
        elif 'embedding' in output_modality:
            category = 'embedding'
        elif 'video' in output_modality:
            category = 'video'
        elif 'image' in output_modality:
            category = 'image'
        elif 'audio' in output_modality:
            category = 'audio'
        else:
            category = 'llm'

        source_name = item.get('name') or openrouter_id_clean
        source_description = item.get('description')
        created_timestamp = item.get('created')
        created_at_openrouter = None
        if created_timestamp:
            try:
                created_at_openrouter = datetime.fromtimestamp(created_timestamp, tz=timezone.utc)
            except (TypeError, ValueError, OverflowError, OSError):
                pass

        pricing = item.get('pricing') if isinstance(item.get('pricing'), dict) else {}
        prompt_token_price = _optional_decimal(pricing.get('prompt'))
        completion_token_price = _optional_decimal(pricing.get('completion'))
        image_price = _optional_decimal(pricing.get('image'))
        request_price = _optional_decimal(pricing.get('request'))

        prompt_1m = (
            (prompt_token_price * Decimal('1000000')).quantize(Decimal('0.000001'))
            if prompt_token_price is not None else None
        )
        completion_1m = (
            (completion_token_price * Decimal('1000000')).quantize(Decimal('0.000001'))
            if completion_token_price is not None else None
        )
        is_free = (
            prompt_1m == Decimal('0') and completion_1m == Decimal('0')
            if prompt_1m is not None and completion_1m is not None else None
        )

        is_open_weight = None
        license_type = ''

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
                name=source_name,
                provider=provider,
                category=category,
                description=source_description or '',
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
            name = source_name if item.get('name') else model_obj.name
            description = source_description if source_description is not None else model_obj.description
            changed = any((
                model_obj.name != name,
                model_obj.provider_id != getattr(provider, 'pk', None),
                model_obj.description != description,
                model_obj.category != category,
                model_obj.is_free != is_free,
                model_obj.raw_json != item,
            ))
            model_obj.name = name
            model_obj.provider = provider
            model_obj.description = description
            model_obj.category = category
            model_obj.is_free = is_free
            model_obj.is_active = True
            model_obj.raw_json = item
            model_obj.last_synced_at = now_dt
            model_obj.updated_at = now_dt
            models_to_update.append(model_obj)
            if changed:
                updated_count += 1

        b_info = benchmark_map.get(openrouter_key) or {}

        top_provider = item.get('top_provider') if isinstance(item.get('top_provider'), dict) else {}
        model_payloads.append({
            'openrouter_key': openrouter_key,
            'context_length': _optional_int(item.get('context_length')),
            'max_completion_tokens': _optional_int(top_provider.get('max_completion_tokens')),
            'modality': modality,
            'tokenizer': architecture.get('tokenizer') or '',
            'instruct_type': architecture.get('instruct_type'),
            'is_multimodal': (len(set(modality_parts)) > 1) if modality else None,
            'supports_vision': ('image' in modality_parts) if modality else None,
            'supports_audio': ('audio' in modality_parts) if modality else None,
            'supports_tools': None,
            'category': category,
            'prompt_token_price': prompt_token_price,
            'completion_token_price': completion_token_price,
            'image_price': image_price,
            'request_price': request_price,
            'prompt_1m': prompt_1m,
            'completion_1m': completion_1m,
            'intel_idx': _optional_score(b_info.get('intelligence_index')),
            'code_idx': _optional_score(b_info.get('coding_index')),
            'agent_idx': _optional_score(b_info.get('agentic_index')),
        })

    # Models absent from a complete, validated OpenRouter catalog are soft-
    # deactivated. AA-only rows use the reserved `aa/` source-ID namespace.
    for model_key, model_obj in existing_models.items():
        if model_key in processed_ids or model_key.startswith('aa/') or not model_obj.is_active:
            continue
        model_obj.is_active = False
        model_obj.updated_at = now_dt
        models_to_update.append(model_obj)
        deactivated_count += 1

    if models_to_create:
        LLMModel.objects.bulk_create(models_to_create, batch_size=100)
    if models_to_update:
        LLMModel.objects.bulk_update(models_to_update, fields=['name', 'provider', 'description', 'category', 'is_free', 'is_active', 'raw_json', 'last_synced_at', 'updated_at'], batch_size=100)

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
            sp = ModelSpecification(
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
            )
            specs_to_create.append(sp)
            existing_specs[model_obj.id] = sp
        else:
            sp.context_length = p['context_length']
            sp.max_completion_tokens = p['max_completion_tokens']
            sp.modality = p['modality']
            sp.tokenizer = p['tokenizer']
            sp.instruct_type = p['instruct_type']
            sp.is_multimodal = p['is_multimodal']
            sp.supports_vision = p['supports_vision']
            sp.supports_audio = p['supports_audio']
            specs_to_update.append(sp)

        # Pricing
        pr = existing_pricing.get(model_obj.id)
        if not pr:
            pr = ModelPricing(
                model=model_obj,
                prompt_price_per_token=p['prompt_token_price'],
                completion_price_per_token=p['completion_token_price'],
                image_price=p['image_price'],
                request_price=p['request_price'],
                prompt_price_per_1m=p['prompt_1m'],
                completion_price_per_1m=p['completion_1m'],
            )
            pricing_to_create.append(pr)
            existing_pricing[model_obj.id] = pr
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
            if any(p[field] is not None for field in ('intel_idx', 'code_idx', 'agent_idx')):
                bm = ModelBenchmark(
                    model=model_obj,
                    intelligence_index=p['intel_idx'],
                    coding_index=p['code_idx'],
                    agentic_index=p['agent_idx'],
                    swe_bench_score=None,
                    arena_elo=None,
                )
                benchmarks_to_create.append(bm)
                existing_benchmarks[model_obj.id] = bm
        else:
            if benchmarks_snapshot_valid:
                bm.intelligence_index = p['intel_idx']
                bm.coding_index = p['code_idx']
                bm.agentic_index = p['agent_idx']
                bm.swe_bench_score = None
                bm.arena_elo = None
            else:
                if p['intel_idx'] is not None:
                    bm.intelligence_index = p['intel_idx']
                if p['code_idx'] is not None:
                    bm.coding_index = p['code_idx']
                if p['agent_idx'] is not None:
                    bm.agentic_index = p['agent_idx']
            benchmarks_to_update.append(bm)

    if specs_to_create:
        ModelSpecification.objects.bulk_create(specs_to_create, batch_size=100)
    if specs_to_update:
        ModelSpecification.objects.bulk_update(specs_to_update, fields=['context_length', 'max_completion_tokens', 'modality', 'tokenizer', 'instruct_type', 'is_multimodal', 'supports_vision', 'supports_audio'], batch_size=100)

    if pricing_to_create:
        ModelPricing.objects.bulk_create(pricing_to_create, batch_size=100)
    if pricing_to_update:
        ModelPricing.objects.bulk_update(pricing_to_update, fields=['prompt_price_per_token', 'completion_price_per_token', 'image_price', 'request_price', 'prompt_price_per_1m', 'completion_price_per_1m'], batch_size=100)

    if benchmarks_to_create:
        ModelBenchmark.objects.bulk_create(benchmarks_to_create, batch_size=100)
    if benchmarks_to_update:
        ModelBenchmark.objects.bulk_update(benchmarks_to_update, fields=['intelligence_index', 'coding_index', 'agentic_index', 'swe_bench_score', 'arena_elo'], batch_size=100)

    analytics_added = analytics_updated = analytics_unchanged = analytics_skipped = 0

    # Process App Rankings
    for app in app_rankings_data:
        if not isinstance(app, dict):
            analytics_skipped += 1
            continue
        app_id = app.get('app_id')
        if app_id:
            try:
                app_id = int(app_id)
            except (TypeError, ValueError, OverflowError):
                analytics_skipped += 1
                continue
            defaults = {
                'app_name': app.get('app_name', 'Unknown'),
                'rank': app.get('rank', 999),
                'total_tokens': int(app.get('total_tokens', 0) or 0),
                'total_requests': int(app.get('total_requests', 0) or 0),
            }
            previous = AppRanking.objects.filter(app_id=app_id).values(
                'app_name', 'rank', 'total_tokens', 'total_requests'
            ).first()
            AppRanking.objects.update_or_create(
                app_id=app_id,
                defaults=defaults,
            )
            if previous is None:
                analytics_added += 1
            elif any(previous.get(key) != value for key, value in defaults.items()):
                analytics_updated += 1
            else:
                analytics_unchanged += 1
        else:
            analytics_skipped += 1

    # Process Task Classifications
    for tc in task_classifications_data:
        if not isinstance(tc, dict):
            analytics_skipped += 1
            continue
        tag = tc.get('tag')
        if tag:
            defaults = {
                'display_name': tc.get('display_name', tag),
                'macro_category': tc.get('macro_category', ''),
                'usage_share': float(tc.get('usage_share', 0.0) or 0.0),
                'token_share': float(tc.get('token_share', 0.0) or 0.0),
                'top_models_share': tc.get('models', []),
            }
            previous = TaskClassification.objects.filter(tag=tag).values(
                'display_name', 'macro_category', 'usage_share', 'token_share', 'top_models_share'
            ).first()
            TaskClassification.objects.update_or_create(
                tag=tag,
                defaults=defaults,
            )
            if previous is None:
                analytics_added += 1
            elif any(previous.get(key) != value for key, value in defaults.items()):
                analytics_updated += 1
            else:
                analytics_unchanged += 1
        else:
            analytics_skipped += 1

    raw_summary = sync_openrouter_tables(
        models_data=models_data,
        benchmarks_data=benchmarks_data if benchmarks_snapshot_valid else None,
        benchmarks_checked=bool(api_key),
    )
    if raw_summary.get('warning'):
        warnings.append(raw_summary['warning'])

    summary = {
        'total_fetched': total_models_received,
        'total_processed': len(model_payloads),
        'created': created_count,
        'updated': updated_count,
        'removed': deactivated_count,
        'unchanged': max(0, len(model_payloads) - created_count - updated_count),
        'skipped': max(0, total_models_received - len(model_payloads)),
        'total_providers': len(provider_cache),
        'analytics_records_fetched': len(app_rankings_data) + len(task_classifications_data),
        'analytics_records_added': analytics_added,
        'analytics_records_updated': analytics_updated,
        'analytics_records_unchanged': analytics_unchanged,
        'analytics_records_skipped': analytics_skipped,
        'warnings': warnings,
        'raw_tables': raw_summary,
    }

    print(f"[OpenRouter Sync] Completed successfully: {created_count} created, {updated_count} updated.")
    return summary
