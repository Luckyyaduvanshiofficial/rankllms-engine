import sys
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import requests
from django.conf import settings
from django.utils.text import slugify

sys.stdout.reconfigure(line_buffering=True)
from llms.models import Provider, ModelsDevModel, LLMModel, ModelSpecification, ModelPricing


def _parse_date(value):
    if not value:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    try:
        return datetime.strptime(str(value)[:10], '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None


def _to_decimal(value, default='0'):
    try:
        return Decimal(str(value if value is not None else default))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


def sync_models_dev_catalog():
    """
    Ingests the free public models.dev catalog (https://models.dev/api.json)
    into the dedicated `modelsdev` table, creates missing Providers, and
    lightly enriches matching LLMModel / spec / pricing rows.
    """
    api_url = getattr(settings, 'MODELS_DEV_API_URL', 'https://models.dev/api.json')
    print(f'[models.dev Sync] Fetching catalog from {api_url}...')

    try:
        res = requests.get(api_url, headers={'User-Agent': 'RankLLMs-Engine/1.0'}, timeout=30)
        res.raise_for_status()
        data = res.json()
    except Exception as e:
        print(f'[models.dev Sync] Failed to fetch catalog: {e}')
        return {'created': 0, 'updated': 0, 'providers': 0, 'error': str(e)}

    if not isinstance(data, dict):
        print('[models.dev Sync] Unexpected payload shape (expected object keyed by provider).')
        return {'created': 0, 'updated': 0, 'providers': 0, 'error': 'invalid_payload'}

    provider_cache = {p.slug.strip().lower(): p for p in Provider.objects.all()}
    new_providers = {}
    rows_to_create = []
    rows_to_update = []
    created = 0
    updated = 0

    for provider_slug, provider_payload in data.items():
        if not isinstance(provider_payload, dict):
            continue
        provider_name = provider_payload.get('name') or provider_slug.replace('-', ' ').title()
        clean_slug = slugify(provider_slug).lower() or slugify(provider_name).lower()
        if clean_slug not in provider_cache and clean_slug not in new_providers:
            new_providers[clean_slug] = Provider(
                slug=clean_slug,
                name=provider_name,
                website=provider_payload.get('doc') or None,
                description=f'{provider_name} AI Models (via models.dev)',
            )

        models_map = provider_payload.get('models') or {}
        for model_key, model_payload in models_map.items():
            if not isinstance(model_payload, dict):
                continue
            modelsdev_id = model_payload.get('id') or model_key
            if not modelsdev_id:
                continue

            limit = model_payload.get('limit') or {}
            cost = model_payload.get('cost') or {}
            row = ModelsDevModel(
                modelsdev_id=modelsdev_id,
                provider_slug=clean_slug,
                provider_name=provider_name,
                name=model_payload.get('name') or modelsdev_id.split('/')[-1],
                description=model_payload.get('description') or '',
                family=model_payload.get('family') or '',
                reasoning=bool(model_payload.get('reasoning')),
                tool_call=bool(model_payload.get('tool_call')),
                structured_output=bool(model_payload.get('structured_output')),
                temperature=bool(model_payload.get('temperature', True)),
                open_weights=bool(model_payload.get('open_weights')),
                release_date=_parse_date(model_payload.get('release_date')),
                last_updated=_parse_date(model_payload.get('last_updated')),
                modalities=model_payload.get('modalities') or {},
                context_length=int(limit.get('context') or 0),
                max_output_tokens=limit.get('output'),
                prompt_price_per_1m=_to_decimal(cost.get('input')),
                completion_price_per_1m=_to_decimal(cost.get('output')),
                cache_read_price_per_1m=(
                    _to_decimal(cost.get('cache_read')) if cost.get('cache_read') is not None else None
                ),
                status=model_payload.get('status') or '',
                raw_json=model_payload,
            )
            rows_to_create.append(row)
            created += 1

    if new_providers:
        Provider.objects.bulk_create(list(new_providers.values()), ignore_conflicts=True)
        provider_cache = {p.slug.strip().lower(): p for p in Provider.objects.all()}

    # Upsert modelsdev rows by modelsdev_id
    existing = {r.modelsdev_id: r for r in ModelsDevModel.objects.all()}
    final_create = []
    final_update = []
    for row in rows_to_create:
        prev = existing.get(row.modelsdev_id)
        if not prev:
            final_create.append(row)
        else:
            prev.provider_slug = row.provider_slug
            prev.provider_name = row.provider_name
            prev.name = row.name
            prev.description = row.description
            prev.family = row.family
            prev.reasoning = row.reasoning
            prev.tool_call = row.tool_call
            prev.structured_output = row.structured_output
            prev.temperature = row.temperature
            prev.open_weights = row.open_weights
            prev.release_date = row.release_date
            prev.last_updated = row.last_updated
            prev.modalities = row.modalities
            prev.context_length = row.context_length
            prev.max_output_tokens = row.max_output_tokens
            prev.prompt_price_per_1m = row.prompt_price_per_1m
            prev.completion_price_per_1m = row.completion_price_per_1m
            prev.cache_read_price_per_1m = row.cache_read_price_per_1m
            prev.status = row.status
            prev.raw_json = row.raw_json
            final_update.append(prev)
            updated += 1

    if final_create:
        ModelsDevModel.objects.bulk_create(final_create, batch_size=200)
    if final_update:
        ModelsDevModel.objects.bulk_update(
            final_update,
            fields=[
                'provider_slug', 'provider_name', 'name', 'description', 'family',
                'reasoning', 'tool_call', 'structured_output', 'temperature',
                'open_weights', 'release_date', 'last_updated', 'modalities',
                'context_length', 'max_output_tokens', 'prompt_price_per_1m',
                'completion_price_per_1m', 'cache_read_price_per_1m', 'status', 'raw_json',
            ],
            batch_size=200,
        )

    enriched = _enrich_main_catalog(provider_cache)

    summary = {
        'created': len(final_create),
        'updated': len(final_update),
        'providers': len(provider_cache),
        'enriched_models': enriched,
        'total_modelsdev': ModelsDevModel.objects.count(),
    }
    print(
        f"[models.dev Sync] Done: {summary['created']} created, {summary['updated']} updated, "
        f"{summary['enriched_models']} main-catalog enrichments."
    )
    return summary


def _enrich_main_catalog(provider_cache):
    """
    Fill empty fields on existing LLMModel rows from models.dev when openrouter_id
    or name matches. Does not overwrite non-zero / non-empty values.
    """
    md_rows = list(ModelsDevModel.objects.all())
    if not md_rows:
        return 0

    lookup = {}
    for row in md_rows:
        lookup[row.modelsdev_id.lower()] = row
        short = row.modelsdev_id.split('/')[-1].lower()
        lookup.setdefault(short, row)
        lookup.setdefault(row.name.lower().replace(' ', '-'), row)

    models = list(LLMModel.objects.all())
    specs_to_create = []
    specs_to_update = []
    pricing_to_create = []
    pricing_to_update = []
    models_to_update = []
    enriched = 0

    existing_specs = {s.model_id: s for s in ModelSpecification.objects.all()}
    existing_pricing = {p.model_id: p for p in ModelPricing.objects.all()}

    for m in models:
        key = (m.openrouter_id or '').lower().strip()
        md = lookup.get(key) or lookup.get(key.split('/')[-1]) or lookup.get(m.slug.lower())
        if not md:
            continue

        changed = False
        if not m.description and md.description:
            m.description = md.description
            changed = True
        if md.open_weights and not m.is_open_weight:
            m.is_open_weight = True
            changed = True
        if changed:
            models_to_update.append(m)
            enriched += 1

        sp = existing_specs.get(m.id)
        if not sp:
            if md.context_length or md.max_output_tokens:
                specs_to_create.append(ModelSpecification(
                    model=m,
                    context_length=md.context_length or 0,
                    max_completion_tokens=md.max_output_tokens,
                    modality=','.join((md.modalities or {}).get('input') or []) or '',
                    is_multimodal=len((md.modalities or {}).get('input') or []) > 1
                    or 'image' in ((md.modalities or {}).get('input') or []),
                    supports_vision='image' in ((md.modalities or {}).get('input') or []),
                    supports_tools=md.tool_call,
                    supports_json_schema=md.structured_output,
                ))
        else:
            spec_changed = False
            if not sp.context_length and md.context_length:
                sp.context_length = md.context_length
                spec_changed = True
            if sp.max_completion_tokens is None and md.max_output_tokens:
                sp.max_completion_tokens = md.max_output_tokens
                spec_changed = True
            if not sp.supports_tools and md.tool_call:
                sp.supports_tools = True
                spec_changed = True
            if not sp.supports_json_schema and md.structured_output:
                sp.supports_json_schema = True
                spec_changed = True
            if spec_changed:
                specs_to_update.append(sp)

        pr = existing_pricing.get(m.id)
        if not pr:
            if md.prompt_price_per_1m or md.completion_price_per_1m:
                pricing_to_create.append(ModelPricing(
                    model=m,
                    prompt_price_per_token=(md.prompt_price_per_1m / Decimal('1000000')),
                    completion_price_per_token=(md.completion_price_per_1m / Decimal('1000000')),
                    prompt_price_per_1m=md.prompt_price_per_1m,
                    completion_price_per_1m=md.completion_price_per_1m,
                ))
        else:
            price_changed = False
            if (not pr.prompt_price_per_1m) and md.prompt_price_per_1m:
                pr.prompt_price_per_1m = md.prompt_price_per_1m
                pr.prompt_price_per_token = md.prompt_price_per_1m / Decimal('1000000')
                price_changed = True
            if (not pr.completion_price_per_1m) and md.completion_price_per_1m:
                pr.completion_price_per_1m = md.completion_price_per_1m
                pr.completion_price_per_token = md.completion_price_per_1m / Decimal('1000000')
                price_changed = True
            if price_changed:
                pricing_to_update.append(pr)

    if models_to_update:
        LLMModel.objects.bulk_update(models_to_update, fields=['description', 'is_open_weight'], batch_size=100)
    if specs_to_create:
        ModelSpecification.objects.bulk_create(specs_to_create, batch_size=100)
    if specs_to_update:
        ModelSpecification.objects.bulk_update(
            specs_to_update,
            fields=['context_length', 'max_completion_tokens', 'supports_tools', 'supports_json_schema'],
            batch_size=100,
        )
    if pricing_to_create:
        ModelPricing.objects.bulk_create(pricing_to_create, batch_size=100)
    if pricing_to_update:
        ModelPricing.objects.bulk_update(
            pricing_to_update,
            fields=['prompt_price_per_token', 'completion_price_per_token', 'prompt_price_per_1m', 'completion_price_per_1m'],
            batch_size=100,
        )

    return enriched
