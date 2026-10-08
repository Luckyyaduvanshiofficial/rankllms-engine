"""Validated replacement of the source-specific snapshot tables."""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from math import isfinite

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.text import slugify

from llms.models import AABench, AAModel, ORBench, ORModel
from llms.services.artificial_analysis_client import MEDIA_ENDPOINTS, fetch_language_models, fetch_media_models
from llms.services.source_http import fetch_json, reject_suspicious_shrink, require_list


def _decimal(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not result.is_finite() or result < 0:
        return None
    return result


def _number(value, *, maximum=None):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not isfinite(number) or number < 0 or (maximum is not None and number > maximum):
        return None
    return number


def _first_value(mapping, *keys):
    for key in keys:
        if mapping.get(key) is not None:
            return mapping[key]
    return None


def _positive_int(value):
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if result > 0 else None


def _source_date(value):
    if not value:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _normalise_modalities(value):
    if not isinstance(value, dict):
        return value if isinstance(value, list) else {}
    normalized = {}
    for direction in ('input', 'output'):
        modalities = value.get(direction) or {}
        if isinstance(modalities, dict):
            normalized[direction] = [name for name, enabled in modalities.items() if enabled is True]
        elif isinstance(modalities, list):
            normalized[direction] = modalities
    return normalized


def _upsert_source_snapshot(model_class, rows, key_field):
    """Upsert a validated source snapshot and keep last-seen time separate from changes."""
    identity = key_field if callable(key_field) else lambda row: getattr(row, key_field)
    existing = {identity(row): row for row in model_class.objects.all()}
    data_fields = [
        field.name for field in model_class._meta.concrete_fields
        if field.name not in {'id', 'updated_at', 'last_verified_at'}
    ]
    now = timezone.now()
    new_rows, update_rows = [], []
    incoming_keys = set()
    changed_count = unchanged_count = 0
    for incoming in rows:
        key = identity(incoming)
        incoming_keys.add(key)
        current = existing.get(key)
        incoming.last_verified_at = now
        if current is None:
            new_rows.append(incoming)
            continue
        changed = any(getattr(current, field) != getattr(incoming, field) for field in data_fields)
        if changed:
            changed_count += 1
            for field in data_fields:
                setattr(current, field, getattr(incoming, field))
            current.updated_at = now
        else:
            unchanged_count += 1
        current.last_verified_at = now
        update_rows.append(current)
    update_fields = data_fields + ['updated_at', 'last_verified_at']
    if new_rows:
        model_class.objects.bulk_create(new_rows, batch_size=200)
    if update_rows:
        model_class.objects.bulk_update(update_rows, fields=update_fields, batch_size=200)
    stale_rows = []
    for key in set(existing) - incoming_keys:
        row = existing[key]
        if row.is_active:
            row.is_active = False
            row.updated_at = now
            stale_rows.append(row)
    if stale_rows:
        model_class.objects.bulk_update(stale_rows, fields=['is_active', 'updated_at'], batch_size=200)
    stale_count = len(set(existing) - incoming_keys)
    return len(new_rows), changed_count, unchanged_count, stale_count


def _media_modalities(endpoint):
    if endpoint.endswith('text-to-image/models/free'):
        return {'input': ['text'], 'output': ['image']}
    if endpoint.endswith('image-editing/models/free'):
        return {'input': ['text', 'image'], 'output': ['image']}
    if endpoint.endswith('text-to-video/models/free'):
        return {'input': ['text'], 'output': ['video']}
    if endpoint.endswith('image-to-video/models/free'):
        return {'input': ['image'], 'output': ['video']}
    if endpoint.endswith('text-to-video-audio/models/free'):
        return {'input': ['text'], 'output': ['video', 'audio']}
    if endpoint.endswith('image-to-video-audio/models/free'):
        return {'input': ['image'], 'output': ['video', 'audio']}
    if endpoint.endswith('text-to-speech/models/free'):
        return {'input': ['text'], 'output': ['audio']}
    if endpoint.endswith('speech-to-speech/models/free'):
        return {'input': ['audio'], 'output': ['audio']}
    if endpoint.endswith('speech-to-text/models/free'):
        return {'input': ['audio'], 'output': ['text']}
    if endpoint.endswith('music/instrumental/models/free') or endpoint.endswith('music/with-vocals/models/free'):
        return {'input': ['text'], 'output': ['audio']}
    return {}


def _media_pricing(item):
    for field, unit in (
        ('price_per_1k_images', '1k images'),
        ('price_per_minute', 'minute'),
        ('price_per_1m_characters', '1m characters'),
    ):
        value = _decimal(item.get(field))
        if value is not None:
            return value, unit
    return None, ''


def sync_openrouter_tables(models_data=None, benchmarks_data=None, *, benchmarks_checked=False):
    """Refresh OpenRouter catalog and, when authenticated, benchmark snapshots."""
    api_key = getattr(settings, 'OPENROUTER_API_KEY', '') or ''
    headers = {'User-Agent': 'RankLLMs-Engine/1.0'}
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'

    if models_data is None:
        models_payload = fetch_json('openrouter', 'https://openrouter.ai/api/v1/models', headers=headers)
    models_data = require_list(models_payload, source='openrouter', path=('data',))
    malformed_models = sum(
        1 for item in models_data
        if not isinstance(item, dict) or not isinstance(item.get('id'), str) or not item.get('id').strip()
    )
    if malformed_models > max(0, int(len(models_data) * 0.1)):
        from llms.services.source_http import UpstreamSourceError
        raise UpstreamSourceError('openrouter', 'Too many OpenRouter model records are missing valid IDs; existing data was kept.')
    elif not isinstance(models_data, list) or not models_data:
        from llms.services.source_http import UpstreamSourceError
        raise UpstreamSourceError('openrouter', 'OpenRouter returned an empty catalog snapshot; existing data was kept.')
    model_rows = []
    seen_ids = set()
    for item in models_data:
        if not isinstance(item, dict) or not item.get('id'):
            continue
        model_id = str(item['id']).strip()
        if model_id.casefold() in seen_ids:
            continue
        seen_ids.add(model_id.casefold())
        pricing = item.get('pricing') if isinstance(item.get('pricing'), dict) else {}
        raw_prompt = _decimal(pricing.get('prompt'))
        raw_completion = _decimal(pricing.get('completion'))
        architecture = item.get('architecture') if isinstance(item.get('architecture'), dict) else {}
        top_provider = item.get('top_provider') if isinstance(item.get('top_provider'), dict) else {}
        model_rows.append(ORModel(
            openrouter_id=model_id,
            name=item.get('name') or model_id,
            canonical_slug=item.get('canonical_slug') or '',
            author=model_id.split('/', 1)[0] if '/' in model_id else '',
            description=item.get('description') or '',
            context_length=int(item['context_length']) if item.get('context_length') else None,
            prompt_price_per_1m=raw_prompt * Decimal('1000000') if raw_prompt is not None else None,
            completion_price_per_1m=raw_completion * Decimal('1000000') if raw_completion is not None else None,
            is_free=(raw_prompt == 0 and raw_completion == 0)
                if raw_prompt is not None and raw_completion is not None else None,
            architecture=architecture,
            top_provider=top_provider,
            pricing=pricing,
            raw_json=item,
        ))
    if not model_rows:
        from llms.services.source_http import UpstreamSourceError
        raise UpstreamSourceError('openrouter', 'OpenRouter returned no valid model records; existing data was kept.')
    reject_suspicious_shrink(
        'openrouter', len(model_rows), ORModel.objects.filter(is_active=True).count()
    )

    benchmark_rows = None
    benchmark_warning = ''
    if not benchmarks_checked and api_key:
        benchmark_payload = fetch_json(
            'openrouter', 'https://openrouter.ai/api/v1/benchmarks', headers=headers
        )
        benchmark_data = require_list(benchmark_payload, source='openrouter', path=('data',))
    elif benchmarks_checked and benchmarks_data is not None:
        benchmark_data = benchmarks_data
        if not isinstance(benchmark_data, list) or not benchmark_data:
            from llms.services.source_http import UpstreamSourceError
            raise UpstreamSourceError('openrouter', 'OpenRouter benchmarks returned an empty snapshot; existing data was kept.')
    elif not benchmarks_checked and not api_key:
        benchmark_data = None
        benchmark_warning = 'OPENROUTER_API_KEY is not configured; authenticated data endpoints were not fetched.'
    else:
        benchmark_data = None
        benchmark_warning = 'OpenRouter benchmarks could not be refreshed; the previous benchmark snapshot was kept.'

    if benchmark_data is not None:
        malformed_benchmarks = sum(
            1 for item in benchmark_data
            if not isinstance(item, dict) or not (item.get('model_permaslug') or item.get('slug'))
        )
        if benchmark_data and malformed_benchmarks > max(0, int(len(benchmark_data) * 0.1)):
            from llms.services.source_http import UpstreamSourceError
            raise UpstreamSourceError('openrouter', 'Too many OpenRouter benchmark rows are missing model IDs; existing data was kept.')
        benchmark_rows = []
        for item in benchmark_data:
            if not isinstance(item, dict):
                continue
            model_id = item.get('model_permaslug') or item.get('slug')
            if not model_id:
                continue
            benchmark_rows.append(ORBench(
                model_permaslug=str(model_id),
                display_name=item.get('display_name') or str(model_id),
                source=item.get('source') or 'unknown',
                benchmark_type=item.get('benchmark_type') or '',
                accuracy=_number(item.get('accuracy')),
                primary_score=_number(item.get('primary_score')),
                primary_metric=item.get('primary_metric') or '',
                elo=_number(item.get('elo')),
                win_rate=_number(item.get('win_rate')),
                category=item.get('category') or '',
                arena=item.get('arena') or '',
                intelligence_index=_number(item.get('intelligence_index')),
                coding_index=_number(item.get('coding_index')),
                agentic_index=_number(item.get('agentic_index')),
                avg_cost_per_task=_number(item.get('avg_cost_per_task')),
                total_tasks=int(item['total_tasks']) if item.get('total_tasks') is not None else None,
                tournament_stats=item.get('tournament_stats') or {},
                pricing=item.get('pricing') or {},
                source_url=item.get('source_url') or '',
                last_run_timestamp=parse_datetime(item['last_run_timestamp']) if item.get('last_run_timestamp') else None,
                raw_json=item,
            ))
        if not benchmark_rows:
            from llms.services.source_http import UpstreamSourceError
            raise UpstreamSourceError('openrouter', 'OpenRouter benchmarks returned no valid records; existing data was kept.')
        reject_suspicious_shrink(
            'openrouter benchmarks', len(benchmark_rows), ORBench.objects.filter(is_active=True).count()
        )
    with transaction.atomic():
        model_diff = _upsert_source_snapshot(ORModel, model_rows, 'openrouter_id')
        benchmark_diff = None
        if benchmark_rows is not None:
            benchmark_diff = _upsert_source_snapshot(
                ORBench,
                benchmark_rows,
                lambda row: (row.model_permaslug, row.source, row.benchmark_type, row.category, row.arena, row.primary_metric),
            )

    return {
        'models_fetched': len(model_rows),
        'models_added': model_diff[0],
        'models_updated': model_diff[1],
        'models_unchanged': model_diff[2],
        'models_stale': model_diff[3],
        'records_skipped': max(0, len(models_data) - len(model_rows)),
        'benchmarks_fetched': len(benchmark_rows) if benchmark_rows is not None else 0,
        'benchmarks_added': benchmark_diff[0] if benchmark_diff else 0,
        'benchmarks_updated': benchmark_diff[1] if benchmark_diff else 0,
        'benchmarks_unchanged': benchmark_diff[2] if benchmark_diff else 0,
        'benchmarks_stale': benchmark_diff[3] if benchmark_diff else 0,
        'benchmarks_preserved': benchmark_rows is None,
        'warning': benchmark_warning,
    }


def sync_artificial_analysis_tables(models=None):
    """Upsert AA language and Free-tier media snapshots, retaining last-seen times."""
    models = models if models is not None else fetch_language_models()
    media_datasets = fetch_media_models()
    aa_models, aa_benches = [], []
    seen_language_slugs = {}
    seen_media_slugs = {}
    skipped = 0
    language_path = getattr(settings, 'ARTIFICIAL_ANALYSIS_MODELS_PATH', 'language/models/free')

    def score(evaluations, *keys):
        for key in keys:
            value = _number(evaluations.get(key), maximum=100)
            if value is not None:
                return value
        return None

    for item in models:
        original_slug = item.get('slug') or item.get('id')
        if not original_slug:
            skipped += 1
            continue
        source_id = str(item.get('id') or original_slug).strip()
        slug_key = str(original_slug).casefold()
        if slug_key in seen_language_slugs:
            if seen_language_slugs[slug_key] != source_id:
                from llms.services.source_http import UpstreamSourceError
                raise UpstreamSourceError(
                    'artificial_analysis',
                    f'Artificial Analysis returned multiple records for slug {original_slug}; explicit variant mapping is required. Existing data was kept.',
                )
            skipped += 1
            continue
        seen_language_slugs[slug_key] = source_id
        creator = item.get('model_creator') or item.get('creator') or {}
        if not isinstance(creator, dict):
            creator = {}
        creator_name = creator.get('name') or item.get('creator_name') or 'Independent'
        creator_slug = creator.get('slug') or item.get('creator_slug') or slugify(creator_name)
        pricing = item.get('pricing') or {}
        specs = item.get('specs') or {}
        limits = item.get('limits') or {}
        performance = item.get('performance') or {}
        evaluations = item.get('evaluations') or {}
        if not isinstance(evaluations, dict):
            evaluations = {}
        prompt_price = _decimal(_first_value(pricing, 'price_1m_input_tokens', 'prompt_price_per_1m'))
        completion_price = _decimal(_first_value(pricing, 'price_1m_output_tokens', 'completion_price_per_1m'))
        cache_hit_price = _decimal(pricing.get('price_1m_cache_hit_tokens'))
        cache_write_price = _decimal(pricing.get('price_1m_cache_write_tokens'))
        context = _first_value(item, 'context_window_tokens', 'context_length') or specs.get('context_window') or limits.get('context')
        max_output = item.get('max_output_tokens') or specs.get('max_output_tokens') or limits.get('output')
        name = item.get('name') or str(original_slug)
        modalities = _normalise_modalities(item.get('modalities') or specs.get('modalities') or {})
        aa_models.append(AAModel(
            slug=str(original_slug),
            source_id=source_id,
            source_slug=str(original_slug),
            source_endpoint=language_path,
            name=name,
            creator_name=creator_name,
            creator_slug=creator_slug,
            release_date=_source_date(item.get('release_date')),
            model_type=item.get('model_type') or item.get('type') or 'llm',
            context_window=int(context) if context is not None else None,
            max_output_tokens=int(max_output) if max_output is not None else None,
            prompt_price_per_1m=prompt_price,
            completion_price_per_1m=completion_price,
            cache_hit_price_per_1m=cache_hit_price,
            cache_write_price_per_1m=cache_write_price,
            modalities=modalities,
            raw_json=item,
        ))
        aa_benches.append(AABench(
            model_slug=str(original_slug),
            source_id=source_id,
            source_slug=str(original_slug),
            source_endpoint=language_path,
            model_name=name,
            creator_name=creator_name,
            intelligence_index=score(evaluations, 'artificial_analysis_intelligence_index', 'intelligence_index'),
            coding_index=score(evaluations, 'artificial_analysis_coding_index', 'coding_index'),
            agentic_index=score(evaluations, 'artificial_analysis_agentic_index', 'agentic_index'),
            finance_and_accounting_index=score(evaluations, 'artificial_analysis_finance_and_accounting_index'),
            strategy_and_ops_index=score(evaluations, 'artificial_analysis_strategy_and_ops_index'),
            legal_index=score(evaluations, 'artificial_analysis_legal_index'),
            healthcare_and_medical_index=score(evaluations, 'artificial_analysis_healthcare_and_medical_index'),
            engineering_index=score(evaluations, 'artificial_analysis_engineering_index'),
            economics_index=score(evaluations, 'artificial_analysis_economics_index'),
            math_index=score(evaluations, 'artificial_analysis_math_index', 'math_index'),
            terminalbench_hard=score(evaluations, 'terminalbench_hard'),
            terminalbench_v2_1=score(evaluations, 'terminalbench_v2_1'),
            gpqa=score(evaluations, 'gpqa_diamond', 'gpqa'),
            mmlu_pro=score(evaluations, 'mmlu_pro', 'mmmu_pro'),
            hle=score(evaluations, 'hle'),
            livecodebench=score(evaluations, 'livecodebench'),
            scicode=score(evaluations, 'scicode'),
            math_500=score(evaluations, 'math_500'),
            aime=score(evaluations, 'aime'),
            aime_25=score(evaluations, 'aime_25'),
            ifbench=score(evaluations, 'ifbench'),
            lcr=score(evaluations, 'aa_lcr', 'lcr'),
            tau2=score(evaluations, 'tau2_telecom', 'tau2'),
            tau_banking=score(evaluations, 'tau_banking'),
            tokens_per_second=_number(item.get('median_output_tokens_per_second', performance.get('median_output_tokens_per_second'))),
            time_to_first_token=_number(item.get('median_time_to_first_token_seconds', performance.get('median_time_to_first_token_seconds'))),
            time_to_first_answer_token=_number(performance.get('median_time_to_first_answer_token_seconds')),
            end_to_end_response_time=_number(performance.get('median_end_to_end_response_time_seconds')),
            raw_json=item,
        ))

    media_count = 0
    for endpoint, (category, rows) in media_datasets.items():
        for item in rows:
            original_slug = item.get('slug') or item.get('id')
            if not original_slug:
                skipped += 1
                continue
            source_id = str(item.get('id') or original_slug).strip()
            base = slugify(f'{category}-{endpoint.replace("/", "-")}-{original_slug}')[:250] or slugify(source_id)[:250]
            storage_slug = base
            if storage_slug in seen_media_slugs:
                if seen_media_slugs[storage_slug] != source_id:
                    from llms.services.source_http import UpstreamSourceError
                    raise UpstreamSourceError('artificial_analysis', 'Duplicate media identity requires explicit mapping; previous data was kept.')
                skipped += 1
                continue
            seen_media_slugs[storage_slug] = source_id
            creator = item.get('model_creator') or {}
            creator_name = creator.get('name') if isinstance(creator, dict) else None
            creator_name = creator_name or 'Independent'
            media_category = 'audio' if category == 'music' else category
            modalities = _media_modalities(endpoint)
            price, price_unit = _media_pricing(item)
            name = item.get('name') or str(original_slug)
            aa_models.append(AAModel(
                slug=storage_slug,
                source_id=source_id,
                source_slug=str(original_slug),
                source_endpoint=endpoint,
                name=name,
                creator_name=creator_name,
                creator_slug=slugify(creator_name),
                release_date=_source_date(item.get('release_date')),
                model_type=media_category,
                modalities=modalities,
                raw_json=item,
            ))
            aa_benches.append(AABench(
                model_slug=storage_slug,
                source_id=source_id,
                source_slug=str(original_slug),
                source_endpoint=endpoint,
                model_name=name,
                creator_name=creator_name,
                elo=_number(item.get('elo')),
                confidence_interval=_number(item.get('ci_95')),
                samples=_positive_int(item.get('samples')),
                price_per_unit=price,
                price_unit=price_unit,
                raw_json=item,
            ))
            media_count += 1

    language_models = sum(1 for row in aa_models if row.source_endpoint == language_path)
    if not language_models:
        from llms.services.source_http import UpstreamSourceError
        raise UpstreamSourceError('artificial_analysis', 'Artificial Analysis returned no language models; existing source rows were kept.')
    reject_suspicious_shrink(
        'artificial_analysis',
        language_models,
        AAModel.objects.filter(is_active=True, model_type='llm').count(),
    )

    with transaction.atomic():
        models_diff = _upsert_source_snapshot(AAModel, aa_models, 'slug')
        benchmarks_diff = _upsert_source_snapshot(AABench, aa_benches, 'model_slug')

    return {
        'models_fetched': len(aa_models),
        'language_models_fetched': language_models,
        'media_models_fetched': media_count,
        'models_added': models_diff[0],
        'models_updated': models_diff[1],
        'models_unchanged': models_diff[2],
        'stale_models_preserved': models_diff[3],
        'records_skipped': skipped,
        'benchmarks_fetched': len(aa_benches),
        'benchmarks_added': benchmarks_diff[0],
        'benchmarks_updated': benchmarks_diff[1],
        'benchmarks_unchanged': benchmarks_diff[2],
        'stale_benchmarks_preserved': benchmarks_diff[3],
    }


def sync_all_dedicated_tables(sources=None):
    """Compatibility helper used by older commands; each source commits atomically."""
    selected = set(sources or ('openrouter', 'artificial_analysis'))
    summary = {}
    if 'openrouter' in selected:
        summary['openrouter'] = sync_openrouter_tables()
    if 'artificial_analysis' in selected:
        summary['artificial_analysis'] = sync_artificial_analysis_tables()
    return summary
