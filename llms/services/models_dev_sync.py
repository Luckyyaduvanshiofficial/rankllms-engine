from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from llms.models import Provider, ModelsDevModel, LLMModel, ModelSpecification, ModelPricing
from llms.services.merge_rankindex import identity_candidates, normalize_provider
from llms.services.source_http import fetch_json, reject_suspicious_shrink, require_mapping


def _parse_date(value):
    if not value:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    try:
        return datetime.strptime(str(value)[:10], '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None


def _to_decimal(value, default=None):
    if value is None:
        return default
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return default
    if not parsed.is_finite() or parsed < 0:
        return default
    return parsed


def fetch_models_dev_catalog():
    """Fetch and validate the public models.dev provider/model snapshot."""
    api_url = getattr(settings, 'MODELS_DEV_API_URL', 'https://models.dev/api.json')
    print(f'[models.dev Sync] Fetching catalog from {api_url}...')
    return require_mapping(
        fetch_json('models_dev', api_url, headers={'User-Agent': 'RankLLMs-Engine/1.0'}),
        source='models.dev',
    )


def sync_models_dev_catalog(snapshot=None):
    """Fetch upstream data before opening the atomic database write phase."""
    snapshot = snapshot if snapshot is not None else fetch_models_dev_catalog()
    return _sync_models_dev_snapshot(snapshot)


@transaction.atomic
def _sync_models_dev_snapshot(data):
    provider_cache = {p.slug.strip().lower(): p for p in Provider.objects.all()}
    new_providers = {}
    rows_to_create = []
    rows_to_update = []
    created = 0
    updated = 0
    unchanged = 0
    seen_model_ids = set()
    received = 0

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
            received += 1
            if not isinstance(model_payload, dict):
                continue
            modelsdev_id = model_payload.get('id') or model_key
            if not modelsdev_id:
                continue
            modelsdev_id = str(modelsdev_id).strip()
            if modelsdev_id.casefold() in seen_model_ids:
                continue
            seen_model_ids.add(modelsdev_id.casefold())

            limit = model_payload.get('limit') or {}
            cost = model_payload.get('cost') or {}
            row = ModelsDevModel(
                modelsdev_id=modelsdev_id,
                canonical_model_id=model_payload.get('canonical_model_id') or '',
                provider_slug=clean_slug,
                provider_name=provider_name,
                name=model_payload.get('name') or modelsdev_id.split('/')[-1],
                description=model_payload.get('description') or '',
                family=model_payload.get('family') or '',
                reasoning=bool(model_payload['reasoning']) if model_payload.get('reasoning') is not None else None,
                tool_call=bool(model_payload['tool_call']) if model_payload.get('tool_call') is not None else None,
                structured_output=bool(model_payload['structured_output']) if model_payload.get('structured_output') is not None else None,
                temperature=bool(model_payload['temperature']) if model_payload.get('temperature') is not None else None,
                open_weights=bool(model_payload['open_weights']) if model_payload.get('open_weights') is not None else None,
                release_date=_parse_date(model_payload.get('release_date')),
                last_updated=_parse_date(model_payload.get('last_updated')),
                modalities=model_payload.get('modalities') or {},
                context_length=int(limit['context']) if limit.get('context') is not None else None,
                max_output_tokens=int(limit['output']) if limit.get('output') is not None else None,
                prompt_price_per_1m=_to_decimal(cost.get('input')),
                completion_price_per_1m=_to_decimal(cost.get('output')),
                cache_read_price_per_1m=(
                    _to_decimal(cost.get('cache_read')) if cost.get('cache_read') is not None else None
                ),
                status=model_payload.get('status') or '',
                raw_json=model_payload,
                is_active=True,
                last_verified_at=timezone.now(),
            )
            rows_to_create.append(row)
            created += 1

    if not rows_to_create:
        from llms.services.source_http import UpstreamSourceError
        raise UpstreamSourceError('models_dev', 'models.dev returned no valid model records; existing data was kept.')
    reject_suspicious_shrink(
        'models_dev', len(rows_to_create), ModelsDevModel.objects.filter(is_active=True).count()
    )

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
            if prev.raw_json == row.raw_json:
                prev.is_active = True
                prev.last_verified_at = timezone.now()
                final_update.append(prev)
                unchanged += 1
                continue
            prev.provider_slug = row.provider_slug
            prev.canonical_model_id = row.canonical_model_id
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
            prev.is_active = True
            prev.last_verified_at = timezone.now()
            prev.updated_at = timezone.now()
            final_update.append(prev)
            updated += 1

    if final_create:
        ModelsDevModel.objects.bulk_create(final_create, batch_size=200)
    if final_update:
        ModelsDevModel.objects.bulk_update(
            final_update,
            fields=[
                'provider_slug', 'canonical_model_id', 'provider_name', 'name', 'description', 'family',
                'reasoning', 'tool_call', 'structured_output', 'temperature',
                'open_weights', 'release_date', 'last_updated', 'modalities',
                'context_length', 'max_output_tokens', 'prompt_price_per_1m',
                'completion_price_per_1m', 'cache_read_price_per_1m', 'status', 'raw_json',
                'is_active', 'last_verified_at', 'updated_at',
            ],
            batch_size=200,
        )

    stale_rows = ModelsDevModel.objects.filter(is_active=True).exclude(
        modelsdev_id__in=seen_model_ids
    )
    stale_count = stale_rows.count()
    stale_rows.update(is_active=False)

    enriched = _enrich_main_catalog(provider_cache)

    summary = {
        'models_fetched': received,
        'models_processed': len(rows_to_create),
        'created': len(final_create),
        'updated': len(final_update),
        'unchanged': unchanged,
        'records_skipped': max(0, received - len(rows_to_create)),
        'stale_preserved': stale_count,
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
    md_rows = list(ModelsDevModel.objects.filter(is_active=True))
    if not md_rows:
        return 0

    lookup = {}
    for row in md_rows:
        provider = normalize_provider(row.provider_slug)
        for key in identity_candidates(provider, row.modelsdev_id, row.canonical_model_id):
            lookup.setdefault(key, []).append(row)

    models = list(LLMModel.objects.select_related('provider').all())
    specs_to_create = []
    specs_to_update = []
    pricing_to_create = []
    pricing_to_update = []
    models_to_update = []
    enriched = 0

    existing_specs = {s.model_id: s for s in ModelSpecification.objects.all()}
    existing_pricing = {p.model_id: p for p in ModelPricing.objects.all()}

    for m in models:
        provider = normalize_provider(m.provider.slug if m.provider_id else '')
        candidates = set()
        for key in identity_candidates(provider, m.openrouter_id, m.slug):
            candidates.update(lookup.get(key, []))
        if len(candidates) != 1:
            continue
        md = next(iter(candidates))

        changed = False
        if not m.description and md.description:
            m.description = md.description
            changed = True
        raw_model = md.raw_json or {}
        if 'open_weights' in raw_model and raw_model['open_weights'] is not None:
            source_open_weight = bool(raw_model['open_weights'])
            if m.is_open_weight != source_open_weight:
                m.is_open_weight = source_open_weight
                changed = True
        if raw_model.get('license') and m.license != raw_model['license']:
            m.license = raw_model['license']
            changed = True
        if changed:
            models_to_update.append(m)
            enriched += 1

        sp = existing_specs.get(m.id)
        if not sp:
            if md.context_length or md.max_output_tokens:
                specs_to_create.append(ModelSpecification(
                    model=m,
                    context_length=md.context_length,
                    max_completion_tokens=md.max_output_tokens,
                    modality=','.join((md.modalities or {}).get('input') or []) or '',
                    is_multimodal=len((md.modalities or {}).get('input') or []) > 1
                    or 'image' in ((md.modalities or {}).get('input') or []),
                    supports_vision='image' in ((md.modalities or {}).get('input') or []),
                    supports_tools=md.tool_call,
                    supports_json_schema=md.structured_output,
                    supports_audio=(
                        'audio' in ((md.modalities or {}).get('input') or [])
                        or 'audio' in ((md.modalities or {}).get('output') or [])
                    ),
                ))
        else:
            spec_changed = False
            if not sp.context_length and md.context_length:
                sp.context_length = md.context_length
                spec_changed = True
            if sp.max_completion_tokens is None and md.max_output_tokens:
                sp.max_completion_tokens = md.max_output_tokens
                spec_changed = True
            if raw_model.get('tool_call') is not None and sp.supports_tools != md.tool_call:
                sp.supports_tools = md.tool_call
                spec_changed = True
            if raw_model.get('structured_output') is not None and sp.supports_json_schema != md.structured_output:
                sp.supports_json_schema = md.structured_output
                spec_changed = True
            modalities = md.modalities or {}
            if isinstance(modalities, dict):
                input_modalities = modalities.get('input') or []
                output_modalities = modalities.get('output') or []
                if input_modalities or output_modalities:
                    supports_vision = 'image' in input_modalities
                    supports_audio = 'audio' in input_modalities or 'audio' in output_modalities
                    is_multimodal = len(input_modalities) > 1 or supports_vision or supports_audio
                    if sp.supports_vision != supports_vision:
                        sp.supports_vision = supports_vision
                        spec_changed = True
                    if sp.supports_audio != supports_audio:
                        sp.supports_audio = supports_audio
                        spec_changed = True
                    if sp.is_multimodal != is_multimodal:
                        sp.is_multimodal = is_multimodal
                        spec_changed = True
                spec_changed = True
            if spec_changed:
                specs_to_update.append(sp)

        pr = existing_pricing.get(m.id)
        raw_cost = raw_model.get('cost') or {}
        input_known = 'input' in raw_cost and raw_cost.get('input') is not None
        output_known = 'output' in raw_cost and raw_cost.get('output') is not None
        if not pr:
            if input_known or output_known:
                pricing_to_create.append(ModelPricing(
                    model=m,
                    prompt_price_per_token=(md.prompt_price_per_1m / Decimal('1000000')) if md.prompt_price_per_1m is not None else None,
                    completion_price_per_token=(md.completion_price_per_1m / Decimal('1000000')) if md.completion_price_per_1m is not None else None,
                    prompt_price_per_1m=md.prompt_price_per_1m,
                    completion_price_per_1m=md.completion_price_per_1m,
                ))
        else:
            price_changed = False
            if input_known and pr.prompt_price_per_1m is None:
                pr.prompt_price_per_1m = md.prompt_price_per_1m
                pr.prompt_price_per_token = md.prompt_price_per_1m / Decimal('1000000')
                price_changed = True
            if output_known and pr.completion_price_per_1m is None:
                pr.completion_price_per_1m = md.completion_price_per_1m
                pr.completion_price_per_token = md.completion_price_per_1m / Decimal('1000000')
                price_changed = True
            if price_changed:
                pricing_to_update.append(pr)

    if models_to_update:
        LLMModel.objects.bulk_update(models_to_update, fields=['description', 'is_open_weight', 'license'], batch_size=100)
    if specs_to_create:
        ModelSpecification.objects.bulk_create(specs_to_create, batch_size=100)
    if specs_to_update:
        ModelSpecification.objects.bulk_update(
            specs_to_update,
            fields=['context_length', 'max_completion_tokens', 'supports_tools', 'supports_json_schema', 'supports_vision', 'supports_audio', 'is_multimodal'],
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
