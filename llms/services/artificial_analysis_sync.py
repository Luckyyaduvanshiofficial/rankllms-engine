"""Ingest verified Artificial Analysis model metadata and evaluations."""

from collections import defaultdict
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils.text import slugify

from llms.models import (
    LLMModel,
    ModelBenchmark,
    ModelPricing,
    ModelSpecification,
    Provider,
)
from llms.services.artificial_analysis_client import fetch_language_models
from llms.services.merge_rankindex import identity_key, normalize_provider
from llms.services.rankllms_calculator import normalize_percentage
from llms.services.source_http import UpstreamSourceError


def _number(value, *, maximum=None):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if result < 0 or result == float('inf') or result != result:
        return None
    if maximum is not None and result > maximum:
        return None
    return result


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


def _first_value(mapping, *keys):
    for key in keys:
        if mapping.get(key) is not None:
            return mapping[key]
    return None


def _modalities_for_direction(value):
    if isinstance(value, dict):
        return [str(name) for name, enabled in value.items() if enabled is True]
    if isinstance(value, list):
        return [str(name) for name in value]
    return []


def _creator(model):
    creator = model.get('model_creator') or model.get('creator') or {}
    if not isinstance(creator, dict):
        creator = {}
    creator_name = creator.get('name') or model.get('creator_name') or 'Independent'
    creator_slug = creator.get('slug') or model.get('creator_slug') or slugify(creator_name) or 'independent'
    provider_slug = normalize_provider(creator_slug) or slugify(creator_name) or 'independent'
    return creator_name, provider_slug


def _model_identity_index(models):
    index = defaultdict(list)
    for model in models:
        provider = normalize_provider(model.provider.slug)
        for value in (model.openrouter_id, model.slug):
            key = identity_key(provider, value)
            if key and model not in index[key]:
                index[key].append(model)
    return index


def _slug_for_new_model(provider_slug, model_slug, used_slugs):
    base = slugify(f'{provider_slug}-{model_slug}') or 'model'
    slug = base[:250]
    suffix = 1
    while slug in used_slugs:
        ending = f'-{suffix}'
        slug = f'{base[:250-len(ending)]}{ending}'
        suffix += 1
    used_slugs.add(slug)
    return slug


def sync_artificial_analysis_data(models_list=None):
    """Fetch, validate, and atomically upsert AA language model records.

    The API's measured indices and telemetry are retained as published. No
    score is inferred from another benchmark, a model name, or a license.
    """
    models_list = models_list if models_list is not None else fetch_language_models()
    prepared = []
    seen = {}
    for item in models_list:
        aa_id = item.get('id') or item.get('slug')
        if not aa_id:
            continue
        aa_slug = item.get('slug') or aa_id
        normalized = str(aa_slug).strip().casefold()
        source_id = str(aa_id).strip()
        if normalized in seen:
            if seen[normalized] != source_id:
                raise UpstreamSourceError(
                    'artificial_analysis',
                    f'Artificial Analysis returned multiple records for slug {aa_slug}; explicit variant mapping is required. Existing data was kept.',
                )
            continue
        seen[normalized] = source_id
        creator_name, creator_slug = _creator(item)
        prepared.append((item, str(aa_id), str(aa_slug), creator_name, creator_slug))
    if not prepared:
        raise UpstreamSourceError(
            'artificial_analysis',
            'Artificial Analysis returned no valid model records; existing data was kept.',
        )

    with transaction.atomic():
        provider_cache = {provider.slug: provider for provider in Provider.objects.all()}
        new_providers = {}
        for _item, _aa_id, _slug, creator_name, provider_slug in prepared:
            if provider_slug not in provider_cache and provider_slug not in new_providers:
                new_providers[provider_slug] = Provider(
                    slug=provider_slug,
                    name=creator_name,
                    description=f'{creator_name} AI Models',
                )
        if new_providers:
            Provider.objects.bulk_create(list(new_providers.values()), ignore_conflicts=True)
            provider_cache = {provider.slug: provider for provider in Provider.objects.all()}

        db_models = list(LLMModel.objects.select_related('provider').all())
        identity_index = _model_identity_index(db_models)
        used_slugs = set(LLMModel.objects.values_list('slug', flat=True))
        new_rows = []
        matched_models = {}
        ambiguous_matches = 0

        for item, aa_id, aa_slug, creator_name, provider_slug in prepared:
            keys = {
                identity_key(provider_slug, aa_slug),
                identity_key(provider_slug, aa_id),
            } - {''}
            candidates = {candidate for key in keys for candidate in identity_index.get(key, [])}
            if len(candidates) == 1:
                target = next(iter(candidates))
                matched_models[aa_slug] = target
                continue
            if len(candidates) > 1:
                ambiguous_matches += 1

            open_id = f'aa/{provider_slug}/{aa_slug}'
            if len(open_id) > 200:
                open_id = f'aa/{provider_slug}/{slugify(aa_slug)[:130]}'
            new_rows.append(LLMModel(
                openrouter_id=open_id,
                slug=_slug_for_new_model(provider_slug, aa_slug, used_slugs),
                name=item.get('name') or aa_slug,
                provider=provider_cache[provider_slug],
                category='llm',
                description=item.get('description') or '',
                is_open_weight=(
                    bool((item.get('licensing') or {}).get('is_open_weights'))
                    if (item.get('licensing') or {}).get('is_open_weights') is not None
                    else None
                ),
                raw_json=item,
            ))

        if new_rows:
            LLMModel.objects.bulk_create(new_rows, ignore_conflicts=True, batch_size=200)

        # Resolve newly inserted AA-only rows and refresh map IDs.
        db_models = list(LLMModel.objects.select_related('provider').all())
        identity_index = _model_identity_index(db_models)
        models_by_aa_slug = {}
        for item, aa_id, aa_slug, _creator_name, provider_slug in prepared:
            if aa_slug in matched_models:
                models_by_aa_slug[aa_slug] = matched_models[aa_slug]
                continue
            keys = {
                identity_key(provider_slug, aa_slug),
                identity_key(provider_slug, aa_id),
            } - {''}
            candidates = {candidate for key in keys for candidate in identity_index.get(key, [])}
            if len(candidates) == 1:
                models_by_aa_slug[aa_slug] = next(iter(candidates))

        spec_map = {row.model_id: row for row in ModelSpecification.objects.all()}
        pricing_map = {row.model_id: row for row in ModelPricing.objects.all()}
        existing_benchmarks = {row.model_id: row for row in ModelBenchmark.objects.all()}
        benchmark_map = dict(existing_benchmarks)
        specs_to_create, specs_to_update = [], []
        prices_to_create, prices_to_update = [], []
        benchmarks_to_create, benchmarks_to_update = [], []
        matched_count = 0
        matched_model_ids = set()

        for item, _aa_id, aa_slug, _creator_name, _provider_slug in prepared:
            model = models_by_aa_slug.get(aa_slug)
            if model is None:
                continue
            matched_count += 1
            matched_model_ids.add(model.pk)
            evaluations = item.get('evaluations') if isinstance(item.get('evaluations'), dict) else {}
            pricing_data = item.get('pricing') if isinstance(item.get('pricing'), dict) else {}
            specs_data = item.get('specs') if isinstance(item.get('specs'), dict) else {}
            limit_data = item.get('limits') if isinstance(item.get('limits'), dict) else {}
            performance = item.get('performance') if isinstance(item.get('performance'), dict) else {}

            context = item.get('context_window_tokens') or item.get('context_length') or specs_data.get('context_window') or limit_data.get('context')
            max_output = item.get('max_output_tokens') or specs_data.get('max_output_tokens') or limit_data.get('output')
            if context is not None or max_output is not None:
                spec = spec_map.get(model.pk)
                if spec is None:
                    spec = ModelSpecification(model=model)
                    spec_map[model.pk] = spec
                    specs_to_create.append(spec)
                else:
                    specs_to_update.append(spec)
                if context is not None:
                    try:
                        spec.context_length = int(context)
                    except (TypeError, ValueError):
                        pass
                if max_output is not None:
                    try:
                        spec.max_completion_tokens = int(max_output)
                    except (TypeError, ValueError):
                        pass
                modalities = item.get('modalities') or specs_data.get('modalities') or {}
                if isinstance(modalities, dict):
                    in_modalities = _modalities_for_direction(modalities.get('input'))
                    out_modalities = _modalities_for_direction(modalities.get('output'))
                    if in_modalities or out_modalities:
                        spec.modality = '+'.join(in_modalities) + '->' + '+'.join(out_modalities)
                        spec.is_multimodal = len(in_modalities) > 1 or any(x in in_modalities for x in ('image', 'audio', 'video'))
                        spec.supports_vision = 'image' in in_modalities
                        spec.supports_audio = 'audio' in in_modalities or 'audio' in out_modalities

            prompt = _decimal(_first_value(
                pricing_data,
                'price_1m_input_tokens',
                'prompt_price_per_1m',
                'prompt_token_cost_per_million',
            ))
            completion = _decimal(_first_value(
                pricing_data,
                'price_1m_output_tokens',
                'completion_price_per_1m',
                'completion_token_cost_per_million',
            ))
            if prompt is not None or completion is not None:
                price = pricing_map.get(model.pk)
                if price is None:
                    price = ModelPricing(model=model)
                    pricing_map[model.pk] = price
                    prices_to_create.append(price)
                else:
                    prices_to_update.append(price)
                if prompt is not None:
                    price.prompt_price_per_1m = prompt
                    price.prompt_price_per_token = prompt / Decimal('1000000')
                if completion is not None:
                    price.completion_price_per_1m = completion
                    price.completion_price_per_token = completion / Decimal('1000000')

            assignments = {
                'intelligence_index': _number(_first_value(evaluations, 'artificial_analysis_intelligence_index', 'intelligence_index'), maximum=100),
                'coding_index': _number(_first_value(evaluations, 'artificial_analysis_coding_index', 'coding_index'), maximum=100),
                'agentic_index': _number(_first_value(evaluations, 'artificial_analysis_agentic_index', 'agentic_index'), maximum=100),
                'math_index': _number(_first_value(evaluations, 'artificial_analysis_math_index', 'math_index'), maximum=100),
                'swe_bench_score': normalize_percentage(_first_value(evaluations, 'swe_bench_resolved', 'swe_bench')),
                'human_eval_score': normalize_percentage(evaluations.get('human_eval')),
                'mmlu_score': normalize_percentage(_first_value(evaluations, 'mmlu', 'mmlu_pro')),
                'tokens_per_second': _number(_first_value(item, 'median_output_tokens_per_second') or performance.get('median_output_tokens_per_second')),
                'time_to_first_token': _number(_first_value(item, 'median_time_to_first_token_seconds') or performance.get('median_time_to_first_token_seconds')),
                'arena_elo': None,
            }
            bm = benchmark_map.get(model.pk)
            if bm is None:
                if not any(value is not None for value in assignments.values()):
                    continue
                bm = ModelBenchmark(model=model)
                benchmark_map[model.pk] = bm
                benchmarks_to_create.append(bm)
            else:
                # Clear legacy inferred values first. The current AA snapshot
                # below repopulates only fields explicitly measured by AA.
                for field in (
                    'intelligence_index', 'coding_index', 'agentic_index', 'math_index',
                    'swe_bench_score', 'human_eval_score', 'mmlu_score', 'arena_elo',
                    'tokens_per_second', 'time_to_first_token',
                ):
                    setattr(bm, field, None)
                benchmarks_to_update.append(bm)
            for field, value in assignments.items():
                if value is not None:
                    setattr(bm, field, value)

        # Older releases filled every missing model with name-based estimates
        # and fabricated ELO/SWE values. A successful complete AA catalog
        # refresh invalidates those unsupported leftovers for non-AA models.
        llm_model_ids = set(LLMModel.objects.filter(category='llm').values_list('pk', flat=True))
        for model_id, bm in existing_benchmarks.items():
            if model_id not in llm_model_ids or model_id in matched_model_ids:
                continue
            changed = False
            for field in (
                'intelligence_index', 'coding_index', 'agentic_index', 'math_index',
                'swe_bench_score', 'human_eval_score', 'mmlu_score', 'arena_elo',
                'tokens_per_second', 'time_to_first_token',
            ):
                if getattr(bm, field) is not None:
                    setattr(bm, field, None)
                    changed = True
            if changed:
                benchmarks_to_update.append(bm)

        if specs_to_create:
            ModelSpecification.objects.bulk_create(specs_to_create, ignore_conflicts=True, batch_size=200)
        if specs_to_update:
            ModelSpecification.objects.bulk_update(
                specs_to_update,
                fields=['context_length', 'max_completion_tokens', 'modality', 'is_multimodal', 'supports_vision', 'supports_audio'],
                batch_size=200,
            )
        if prices_to_create:
            ModelPricing.objects.bulk_create(prices_to_create, ignore_conflicts=True, batch_size=200)
        if prices_to_update:
            ModelPricing.objects.bulk_update(
                prices_to_update,
                fields=['prompt_price_per_token', 'completion_price_per_token', 'prompt_price_per_1m', 'completion_price_per_1m'],
                batch_size=200,
            )
        if benchmarks_to_create:
            ModelBenchmark.objects.bulk_create(benchmarks_to_create, ignore_conflicts=True, batch_size=200)
        if benchmarks_to_update:
            ModelBenchmark.objects.bulk_update(
                benchmarks_to_update,
                fields=['intelligence_index', 'coding_index', 'agentic_index', 'math_index', 'swe_bench_score', 'human_eval_score', 'mmlu_score', 'arena_elo', 'tokens_per_second', 'time_to_first_token'],
                batch_size=200,
            )

    return {
        'models_fetched': len(prepared),
        'models_matched_or_added': matched_count,
        'models_added': len(new_rows),
        'ambiguous_matches': ambiguous_matches,
        'records_updated': matched_count,
    }
