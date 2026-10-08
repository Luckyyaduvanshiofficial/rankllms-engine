"""Conservative, source-attributed merge into the public canonical catalog."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import defaultdict
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils.text import slugify

from llms.models import AABench, AAModel, ModelsDevModel, ORBench, ORModel, RankIndex
from llms.services.rankllms_calculator import calculate_rankllms_index, normalize_percentage


PROVIDER_ALIASES = {
    'meta': 'meta-llama',
    'meta-llama': 'meta-llama',
    'mistral': 'mistralai',
    'mistralai': 'mistralai',
    'alibaba': 'qwen',
    'alibaba-cloud': 'qwen',
    'qwen': 'qwen',
    'xai': 'x-ai',
    'x-ai': 'x-ai',
    'google-ai': 'google',
}


def normalize_slug(value: str) -> str:
    """Normalize spelling while retaining provider path tail and model version.

    Unlike the old implementation, this does not erase dates, version numbers,
    or variant suffixes. It is used only as one part of a provider-scoped key.
    """
    if not value:
        return ''
    normalized = unicodedata.normalize('NFKC', str(value)).strip().casefold()
    normalized = normalized.rsplit('/', 1)[-1]
    return re.sub(r'[^a-z0-9]+', '-', normalized).strip('-')


def normalize_provider(value: str) -> str:
    if not value:
        return ''
    token = slugify(unicodedata.normalize('NFKC', str(value))).casefold()
    return PROVIDER_ALIASES.get(token, token)


def identity_key(provider: str, identifier: str) -> str:
    model_token = normalize_slug(identifier)
    provider_token = normalize_provider(provider)
    if not provider_token or not model_token:
        return ''
    return f'{provider_token}::{model_token}'


def _source_keys(provider: str, *identifiers: str) -> set[str]:
    return {key for key in (identity_key(provider, item) for item in identifiers) if key}


def _provider_from_id(identifier: str, fallback: str = '') -> str:
    if '/' in (identifier or ''):
        return identifier.split('/', 1)[0]
    return fallback


def identity_candidates(provider: str, *identifiers: str) -> set[str]:
    """Return scoped identities, honoring an explicit provider path in an ID."""
    keys = set()
    for identifier in identifiers:
        if not identifier:
            continue
        keys.update(_source_keys(provider, identifier))
        explicit_provider = _provider_from_id(identifier)
        if explicit_provider:
            keys.update(_source_keys(explicit_provider, identifier))
    return keys


def _positive_int(*values):
    for value in values:
        try:
            parsed = int(value)
        except (TypeError, ValueError, OverflowError):
            continue
        if parsed > 0:
            return parsed
    return None


def _safe_decimal(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not parsed.is_finite() or parsed < 0:
        return None
    return parsed


def _has_price_fields(raw, input_fields, output_fields):
    if not isinstance(raw, dict):
        return False
    return any(key in raw and raw[key] is not None for key in input_fields) or any(
        key in raw and raw[key] is not None for key in output_fields
    )


def _price_values(or_model=None, aa_model=None, md_model=None):
    """Return source-priority price and explicit-known/free flags."""
    candidates = []
    if or_model:
        raw = or_model.raw_json or {}
        price = raw.get('pricing') or {}
        if _has_price_fields(price, ('prompt',), ('completion',)):
            input_per_token = _safe_decimal(price.get('prompt'))
            output_per_token = _safe_decimal(price.get('completion'))
            candidates.append((
                'openrouter',
                input_per_token * Decimal('1000000') if input_per_token is not None else None,
                output_per_token * Decimal('1000000') if output_per_token is not None else None,
            ))
    if aa_model:
        raw = aa_model.raw_json or {}
        price = raw.get('pricing') or {}
        in_keys = ('price_1m_input_tokens', 'prompt_price_per_1m', 'prompt_token_cost_per_million')
        out_keys = ('price_1m_output_tokens', 'completion_price_per_1m', 'completion_token_cost_per_million')
        if _has_price_fields(price, in_keys, out_keys):
            candidates.append((
                'artificial-analysis',
                _safe_decimal(next((price.get(k) for k in in_keys if k in price), None)),
                _safe_decimal(next((price.get(k) for k in out_keys if k in price), None)),
            ))
    if md_model:
        raw = md_model.raw_json or {}
        cost = raw.get('cost') or {}
        if _has_price_fields(cost, ('input',), ('output',)):
            candidates.append((
                'models.dev', _safe_decimal(cost.get('input')), _safe_decimal(cost.get('output'))
            ))
    if not candidates:
        return None, None, None, []

    selected_source, input_price, output_price = candidates[0]
    conflicts = []
    for source, candidate_input, candidate_output in candidates[1:]:
        if (candidate_input, candidate_output) != (input_price, output_price):
            conflicts.append({
                'field': 'pricing',
                'selected_source': selected_source,
                'compared_source': source,
                'selected': [str(input_price) if input_price is not None else None,
                             str(output_price) if output_price is not None else None],
                'compared': [str(candidate_input) if candidate_input is not None else None,
                             str(candidate_output) if candidate_output is not None else None],
            })
    free = (
        input_price == Decimal('0') and output_price == Decimal('0')
        if input_price is not None and output_price is not None
        else None
    )
    return input_price, output_price, free, conflicts


def _raw_eval(aa_model, benchmark, key, column):
    raw = (aa_model.raw_json if aa_model else {}) or {}
    evaluations = raw.get('evaluations') or {}
    if not isinstance(evaluations, dict):
        evaluations = {}
    value = evaluations.get(key)
    if value is None and benchmark:
        benchmark_raw = benchmark.raw_json or {}
        benchmark_evaluations = benchmark_raw.get('evaluations') or {}
        if isinstance(benchmark_evaluations, dict):
            value = benchmark_evaluations.get(key)
    if value is not None:
        return value
    if benchmark:
        value = getattr(benchmark, column, None)
        # Dedicated AA benchmark columns historically defaulted to zero. Treat
        # zero as unknown unless the source payload explicitly reported it.
        if value not in (None, 0, 0.0):
            return value
    return None


def _index_value(aa_model, benchmark, key, column):
    value = _raw_eval(aa_model, benchmark, key, column)
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if 0 <= number <= 100 else None


def _first_non_empty(*values):
    return next((value for value in values if value not in (None, '', [], {})), None)


def _modalities(*values):
    for value in values:
        if not isinstance(value, dict):
            continue
        input_values = value.get('input')
        output_values = value.get('output')
        if isinstance(input_values, dict):
            input_values = [name for name, enabled in input_values.items() if enabled is True]
        if isinstance(output_values, dict):
            output_values = [name for name, enabled in output_values.items() if enabled is True]
        if isinstance(input_values, list) or isinstance(output_values, list):
            return list(input_values or []), list(output_values or [])
    return [], []


def _openrouter_modality(or_model):
    if not or_model:
        return [], []
    modality = ((or_model.architecture or {}).get('modality') or '').lower()
    if '->' not in modality:
        return ([modality] if modality else []), []
    input_text, output_text = modality.split('->', 1)
    split = lambda part: [value.strip() for value in re.split(r'[+,/]', part) if value.strip()]
    return split(input_text), split(output_text)


def _explicit_open_weight(md_model, aa_model=None):
    raw = (md_model.raw_json if md_model else {}) or {}
    if 'open_weights' in raw and raw['open_weights'] is not None:
        return bool(raw['open_weights'])
    aa_raw = (aa_model.raw_json if aa_model else {}) or {}
    licensing = aa_raw.get('licensing') or {}
    if isinstance(licensing, dict) and licensing.get('is_open_weights') is not None:
        return bool(licensing['is_open_weights'])
    return None


def _explicit_boolean(raw, key):
    if isinstance(raw, dict) and key in raw and raw[key] is not None:
        return bool(raw[key])
    return None


def _enrich_from_modelsdev(row, model):
    """Fill canonical gaps from a unique models.dev identity match."""
    enriched = _build_row(
        provider_slug=_source_provider(model, 'models.dev'),
        provider_name=getattr(model, 'provider_name', ''),
        name=model.name,
        canonical_source_id=model.modelsdev_id,
        modelsdev_model=model,
    )
    row['aliases'] = _make_aliases(*row['aliases'], model.modelsdev_id, model.canonical_model_id)
    row['modelsdev_id'] = model.modelsdev_id
    row['sources'] = list(dict.fromkeys(row['sources'] + ['models.dev']))
    row['raw_data']['models_dev'] = enriched['raw_data']['models_dev']
    for field in (
        'family', 'version', 'status', 'license', 'description', 'category',
        'input_modalities', 'output_modalities', 'is_open_weight', 'reasoning',
        'tool_call', 'structured_output', 'context_length', 'max_output_tokens',
        'prompt_price_per_1m', 'completion_price_per_1m', 'is_free',
    ):
        current = row.get(field)
        value = enriched.get(field)
        is_empty = current in (None, '', [], {})
        if is_empty and value not in (None, '', [], {}):
            row[field] = value
    if row['prompt_price_per_1m'] is not None and row['completion_price_per_1m'] is not None:
        row['is_free'] = (
            row['prompt_price_per_1m'] == Decimal('0')
            and row['completion_price_per_1m'] == Decimal('0')
        )


def _ambiguous_match(keys, index):
    matches = set()
    for key in keys:
        matches.update(index.get(key, []))
    if len(matches) == 1:
        return next(iter(matches)), False
    return None, len(matches) > 1


def _make_aliases(*ids):
    return list(dict.fromkeys(str(value).strip() for value in ids if value))


def _build_row(*, provider_slug, provider_name, name, canonical_source_id,
               openrouter_model=None, aa_model=None, aa_bench=None,
               modelsdev_model=None, or_benchmarks=None):
    or_benchmarks = or_benchmarks or []
    or_raw = (openrouter_model.raw_json if openrouter_model else {}) or {}
    aa_raw = (aa_model.raw_json if aa_model else {}) or {}
    md_raw = (modelsdev_model.raw_json if modelsdev_model else {}) or {}

    aa_evaluations = aa_raw.get('evaluations') or {}
    if not isinstance(aa_evaluations, dict):
        aa_evaluations = {}
    aa_performance = aa_raw.get('performance') or {}
    if not isinstance(aa_performance, dict):
        aa_performance = {}
    intelligence = _index_value(
        aa_model, aa_bench, 'artificial_analysis_intelligence_index', 'intelligence_index'
    )
    coding = _index_value(
        aa_model, aa_bench, 'artificial_analysis_coding_index', 'coding_index'
    )
    agentic = _index_value(
        aa_model, aa_bench, 'artificial_analysis_agentic_index', 'agentic_index'
    )
    capability_indexes = {
        'finance_and_accounting_index': _index_value(
            aa_model, aa_bench,
            'artificial_analysis_finance_and_accounting_index',
            'finance_and_accounting_index',
        ),
        'strategy_and_ops_index': _index_value(
            aa_model, aa_bench,
            'artificial_analysis_strategy_and_ops_index',
            'strategy_and_ops_index',
        ),
        'legal_index': _index_value(
            aa_model, aa_bench,
            'artificial_analysis_legal_index',
            'legal_index',
        ),
        'healthcare_and_medical_index': _index_value(
            aa_model, aa_bench,
            'artificial_analysis_healthcare_and_medical_index',
            'healthcare_and_medical_index',
        ),
        'engineering_index': _index_value(
            aa_model, aa_bench,
            'artificial_analysis_engineering_index',
            'engineering_index',
        ),
        'economics_index': _index_value(
            aa_model, aa_bench,
            'artificial_analysis_economics_index',
            'economics_index',
        ),
    }
    math_index = _index_value(
        aa_model, aa_bench, 'artificial_analysis_math_index', 'math_index'
    )

    gpqa_raw = _raw_eval(aa_model, aa_bench, 'gpqa', 'gpqa')
    terminal_raw = _raw_eval(aa_model, aa_bench, 'terminalbench_hard', 'terminalbench_hard')
    if terminal_raw is None:
        terminal_raw = _raw_eval(aa_model, aa_bench, 'terminalbench_v2_1', 'terminalbench_v2_1')
    gpqa = normalize_percentage(gpqa_raw)
    terminalbench = normalize_percentage(terminal_raw)
    metric_conflicts = []

    # OpenRouter's unified feed contains source-specific records. Only use the
    # Artificial Analysis index shape for indices and only a GPQA record for
    # the GPQA field; arbitrary accuracy values are not interchangeable.
    for record in or_benchmarks:
        if record.source == 'artificial-analysis':
            raw = record.raw_json or {}
            candidate_intelligence = _index_value_from_raw(
                raw.get('intelligence_index', record.intelligence_index)
            )
            candidate_coding = _index_value_from_raw(raw.get('coding_index', record.coding_index))
            candidate_agentic = _index_value_from_raw(raw.get('agentic_index', record.agentic_index))
            for field, current, candidate in (
                ('intelligence_index', intelligence, candidate_intelligence),
                ('coding_index', coding, candidate_coding),
                ('agentic_index', agentic, candidate_agentic),
            ):
                if current is not None and candidate is not None and abs(current - candidate) > 0.01:
                    metric_conflicts.append({
                        'field': field,
                        'selected_source': 'artificial-analysis',
                        'compared_source': 'openrouter:artificial-analysis',
                        'selected': current,
                        'compared': candidate,
                    })
            if intelligence is None:
                intelligence = candidate_intelligence
            if coding is None:
                coding = candidate_coding
            if agentic is None:
                agentic = candidate_agentic
        if record.source == 'openrouter' and record.benchmark_type == 'gpqa_diamond':
            raw = record.raw_json or {}
            candidate = raw.get('accuracy', record.accuracy)
            candidate_gpqa = normalize_percentage(candidate)
            if gpqa is not None and candidate_gpqa is not None and abs(gpqa - candidate_gpqa) > 0.01:
                metric_conflicts.append({
                    'field': 'gpqa_diamond',
                    'selected_source': 'artificial-analysis',
                    'compared_source': 'openrouter',
                    'selected': gpqa,
                    'compared': candidate_gpqa,
                })
            if gpqa is None:
                gpqa = candidate_gpqa

    if gpqa is None and aa_evaluations.get('gpqa_diamond') is not None:
        gpqa = normalize_percentage(aa_evaluations.get('gpqa_diamond'))

    input_price, output_price, is_free, price_conflicts = _price_values(
        openrouter_model, aa_model, modelsdev_model
    )
    md_cost = (md_raw.get('cost') or {})
    md_limit = (md_raw.get('limit') or {})
    aa_pricing = (aa_raw.get('pricing') or {})
    aa_specs = (aa_raw.get('specs') or {})
    or_top_provider = (or_raw.get('top_provider') or {})

    context_length = _positive_int(
        getattr(modelsdev_model, 'context_length', None),
        md_limit.get('context'),
        getattr(aa_model, 'context_window', None),
        aa_specs.get('context_window'),
        aa_raw.get('context_window_tokens'),
        getattr(openrouter_model, 'context_length', None),
        or_raw.get('context_length'),
    )
    max_output_tokens = _positive_int(
        getattr(modelsdev_model, 'max_output_tokens', None),
        md_limit.get('output'),
        getattr(aa_model, 'max_output_tokens', None),
        aa_specs.get('max_output_tokens'),
        or_top_provider.get('max_completion_tokens'),
    )

    md_modalities = md_raw.get('modalities') or (getattr(modelsdev_model, 'modalities', None) or {})
    aa_modalities = aa_raw.get('modalities') or aa_specs.get('modalities') or {}
    input_modalities, output_modalities = _modalities(md_modalities, aa_modalities)
    if not input_modalities and not output_modalities:
        input_modalities, output_modalities = _openrouter_modality(openrouter_model)

    creator_slug = _first_non_empty(
        getattr(modelsdev_model, 'provider_slug', ''),
        getattr(aa_model, 'creator_slug', ''),
        getattr(openrouter_model, 'author', ''),
        provider_slug,
    ) or provider_slug
    provider = _first_non_empty(
        getattr(modelsdev_model, 'provider_name', ''),
        getattr(aa_model, 'creator_name', ''),
        provider_name,
    ) or provider_slug

    modelsdev_id = getattr(modelsdev_model, 'modelsdev_id', '') if modelsdev_model else ''
    canonical_model_id = getattr(modelsdev_model, 'canonical_model_id', '') if modelsdev_model else ''
    aa_slug = (getattr(aa_model, 'source_slug', '') or getattr(aa_model, 'slug', '')) if aa_model else ''
    aa_storage_slug = getattr(aa_model, 'slug', '') if aa_model else ''
    aa_source_id = getattr(aa_model, 'source_id', '') if aa_model else ''
    aa_source_endpoint = getattr(aa_model, 'source_endpoint', '') if aa_model else ''
    aa_source_alias = f'{aa_source_endpoint}#{aa_source_id}' if aa_source_endpoint and aa_source_id else aa_source_id
    openrouter_id = getattr(openrouter_model, 'openrouter_id', '') if openrouter_model else ''
    sources = []
    if openrouter_model:
        sources.append('openrouter')
    if aa_model or aa_bench:
        sources.append('artificial-analysis')
    if modelsdev_model:
        sources.append('models.dev')
    if any(record.source == 'design-arena' for record in or_benchmarks):
        sources.append('design-arena')

    arena_records = [record for record in or_benchmarks if record.source == 'design-arena']
    arena_records.sort(key=lambda record: record.elo or float('-inf'), reverse=True)
    arena = arena_records[0] if arena_records else None
    arena_raw = (arena.raw_json if arena else {}) or {}
    aa_benchmark_raw = (aa_bench.raw_json if aa_bench else {}) or {}

    row = {
        'canonical_slug': canonical_source_id,
        'name': name,
        'provider': provider,
        'provider_slug': normalize_provider(creator_slug),
        'author_slug': creator_slug,
        'openrouter_id': openrouter_id,
        'aa_slug': aa_slug,
        'modelsdev_id': modelsdev_id,
        'family': _first_non_empty(
            getattr(modelsdev_model, 'family', ''), md_raw.get('family'), aa_raw.get('family')
        ) or '',
        'version': _first_non_empty(md_raw.get('version'), aa_raw.get('version')) or '',
        'aliases': _make_aliases(openrouter_id, aa_source_alias, aa_storage_slug, modelsdev_id, canonical_model_id),
        'category': _first_non_empty(
            getattr(modelsdev_model, 'model_type', ''),
            getattr(aa_model, 'model_type', ''),
            aa_raw.get('model_type'),
            getattr(openrouter_model, 'category', ''),
        ) or 'llm',
        'status': _first_non_empty(getattr(modelsdev_model, 'status', ''), md_raw.get('status')) or '',
        'license': _first_non_empty(md_raw.get('license'), aa_raw.get('license')) or '',
        'description': _first_non_empty(
            or_raw.get('description'), aa_raw.get('description'), md_raw.get('description')
        ) or '',
        'release_date': _first_non_empty(
            getattr(aa_model, 'release_date', None),
            getattr(modelsdev_model, 'release_date', None),
            md_raw.get('release_date'),
            aa_raw.get('release_date'),
        ),
        'last_verified_at': _latest_source_timestamp(
            getattr(openrouter_model, 'updated_at', None),
            getattr(aa_model, 'last_verified_at', None) or getattr(aa_model, 'updated_at', None),
            getattr(aa_bench, 'last_verified_at', None) or getattr(aa_bench, 'updated_at', None),
            getattr(modelsdev_model, 'last_verified_at', None) or getattr(modelsdev_model, 'updated_at', None),
        ),
        'input_modalities': input_modalities,
        'output_modalities': output_modalities,
        'media_metrics': {
            'elo': getattr(aa_bench, 'elo', None),
            'confidence_interval': getattr(aa_bench, 'confidence_interval', None),
            'samples': getattr(aa_bench, 'samples', None),
            'price_per_unit': str(aa_bench.price_per_unit) if aa_bench and aa_bench.price_per_unit is not None else None,
            'price_unit': getattr(aa_bench, 'price_unit', ''),
            'bba_score': aa_benchmark_raw.get('bba_score'),
            'fdb_score': aa_benchmark_raw.get('fdb_score'),
            'tau_voice_score': aa_benchmark_raw.get('tau_voice_score'),
            'aa_wer_index': aa_benchmark_raw.get('aa_wer_index'),
            'source_endpoint': getattr(aa_bench, 'source_endpoint', ''),
        } if aa_bench and (aa_bench.source_endpoint or '').startswith('media/') else {},
        'is_open_weight': _explicit_open_weight(modelsdev_model, aa_model),
        'is_free': is_free,
        'reasoning': _first_non_empty(
            _explicit_boolean(md_raw, 'reasoning'),
            _explicit_boolean(aa_raw, 'reasoning_model'),
        ),
        'tool_call': _explicit_boolean(md_raw, 'tool_call'),
        'structured_output': _explicit_boolean(md_raw, 'structured_output'),
        'rankllms_index': None,
        'rank_overall': None,
        'rank_coding': None,
        'rank_reasoning': None,
        'rank_value': None,
        'intelligence_index': intelligence,
        'coding_index': coding,
        'agentic_index': agentic,
        **capability_indexes,
        'math_index': math_index,
        'terminalbench_hard': normalize_percentage(terminal_raw),
        'terminalbench_v2_1': normalize_percentage(
            _raw_eval(aa_model, aa_bench, 'terminalbench_v2_1', 'terminalbench_v2_1')
        ),
        'gpqa_diamond': gpqa,
        'mmlu_pro': normalize_percentage(_raw_eval(aa_model, aa_bench, 'mmlu_pro', 'mmlu_pro')),
        'hle': normalize_percentage(_raw_eval(aa_model, aa_bench, 'hle', 'hle')),
        'livecodebench': normalize_percentage(_raw_eval(aa_model, aa_bench, 'livecodebench', 'livecodebench')),
        'scicode': normalize_percentage(_raw_eval(aa_model, aa_bench, 'scicode', 'scicode')),
        'math_500': normalize_percentage(_raw_eval(aa_model, aa_bench, 'math_500', 'math_500')),
        'aime_25': normalize_percentage(_raw_eval(aa_model, aa_bench, 'aime_25', 'aime_25')),
        'design_arena_elo': arena_raw.get('elo', getattr(arena, 'elo', None)) if arena else None,
        'design_arena_win_rate': normalize_percentage(
            arena_raw.get('win_rate', getattr(arena, 'win_rate', None))
        ) if arena else None,
        'ifbench': normalize_percentage(_raw_eval(aa_model, aa_bench, 'ifbench', 'ifbench')),
        'lcr': normalize_percentage(_raw_eval(aa_model, aa_bench, 'lcr', 'lcr')),
        'tau2': normalize_percentage(_raw_eval(aa_model, aa_bench, 'tau2', 'tau2')),
        'tau_banking': normalize_percentage(_raw_eval(aa_model, aa_bench, 'tau_banking', 'tau_banking')),
        'context_length': context_length,
        'max_output_tokens': max_output_tokens,
        'prompt_price_per_1m': input_price,
        'completion_price_per_1m': output_price,
        'aa_cache_hit_price_per_1m': _safe_decimal(
            aa_pricing.get('price_1m_cache_hit_tokens', getattr(aa_model, 'cache_hit_price_per_1m', None))
        ),
        'aa_cache_write_price_per_1m': _safe_decimal(
            aa_pricing.get('price_1m_cache_write_tokens', getattr(aa_model, 'cache_write_price_per_1m', None))
        ),
        'tokens_per_second': _source_number(
            aa_raw.get('median_output_tokens_per_second'),
            aa_performance.get('median_output_tokens_per_second'),
            getattr(aa_bench, 'tokens_per_second', None),
        ),
        'time_to_first_token': _source_number(
            aa_raw.get('median_time_to_first_token_seconds'),
            aa_performance.get('median_time_to_first_token_seconds'),
            getattr(aa_bench, 'time_to_first_token', None),
        ),
        'time_to_first_answer_token': _source_number(
            aa_performance.get('median_time_to_first_answer_token_seconds'),
            getattr(aa_bench, 'time_to_first_answer_token', None),
        ),
        'end_to_end_response_time': _source_number(
            aa_performance.get('median_end_to_end_response_time_seconds'),
            getattr(aa_bench, 'end_to_end_response_time', None),
        ),
        'has_openrouter': bool(openrouter_model),
        'has_artificial_analysis': bool(aa_model or aa_bench),
        'has_design_arena': bool(arena),
        'sources': list(dict.fromkeys(sources)),
        'raw_data': {
            'openrouter': or_raw or None,
            'artificial_analysis': aa_raw or None,
            'artificial_analysis_benchmarks': (aa_bench.raw_json if aa_bench else None),
            'artificial_analysis_endpoint': getattr(aa_model, 'source_endpoint', '') if aa_model else '',
            'openrouter_benchmarks': [record.raw_json for record in or_benchmarks],
            'models_dev': md_raw or None,
        },
        '_price_conflicts': price_conflicts,
        '_metric_conflicts': metric_conflicts,
    }
    row['rankllms_index'] = calculate_rankllms_index(components={
        'intelligence_index': intelligence,
        'coding_index': coding,
        'agentic_index': agentic,
        'gpqa_diamond': gpqa,
        'terminalbench': (
            row['terminalbench_hard']
            if row['terminalbench_hard'] is not None
            else row['terminalbench_v2_1']
        ),
    })
    return row


def _index_value_from_raw(value):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if 0 <= number <= 100 else None


def _source_number(*values):
    for value in values:
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            continue
        if number >= 0 and number != float('inf'):
            return number
    return None


def _latest_source_timestamp(*values):
    available = [value for value in values if value is not None]
    return max(available) if available else None


def _match_openrouter(provider, identifiers, index):
    return _ambiguous_match(identity_candidates(provider, *identifiers), index)


def _source_provider(model, source):
    if source == 'openrouter':
        return _provider_from_id(model.openrouter_id, model.author)
    if source == 'artificial-analysis':
        return getattr(model, 'creator_slug', '') or getattr(model, 'creator_name', '')
    return getattr(model, 'provider_slug', '') or getattr(model, 'provider_name', '')


def merge_and_build_rankindex():
    """Build a fresh, conservative canonical snapshot and replace atomically."""
    or_models = list(ORModel.objects.filter(is_active=True))
    or_benches = list(ORBench.objects.filter(is_active=True))
    aa_models = list(AAModel.objects.filter(is_active=True))
    aa_benches = list(AABench.objects.filter(is_active=True))
    md_models = list(ModelsDevModel.objects.filter(is_active=True))

    if not (or_models or aa_models or md_models):
        return {'status': 'skipped', 'reason': 'No validated source snapshot is available.'}

    or_index = defaultdict(list)
    for model in or_models:
        provider = _source_provider(model, 'openrouter')
        keys = _source_keys(provider, model.openrouter_id)
        for key in keys:
            or_index[key].append(model)

    aa_or_matches = {}
    ambiguous = []
    matched_or_ids = set()
    matched_aa_ids = set()
    for model in aa_models:
        provider = _source_provider(model, 'artificial-analysis')
        matched, is_ambiguous = _match_openrouter(provider, (model.slug,), or_index)
        aa_or_matches[model.pk] = matched
        if matched:
            matched_or_ids.add(matched.pk)
            matched_aa_ids.add(model.pk)
        if is_ambiguous:
            ambiguous.append({
                'source': 'artificial-analysis',
                'source_id': model.slug,
                'candidate_openrouter_ids': sorted(
                    candidate.openrouter_id
                    for candidate in set(
                        candidate
                        for key in _source_keys(provider, model.slug)
                        for candidate in or_index.get(key, [])
                    )
                ),
            })

    aa_bench_by_slug = {bench.model_slug: bench for bench in aa_benches if bench.model_slug}
    aa_index = defaultdict(list)
    for aa_model in aa_models:
        aa_provider = _source_provider(aa_model, 'artificial-analysis')
        for key in _source_keys(aa_provider, aa_model.slug):
            aa_index[key].append(aa_model)
    md_or_matches = {}
    md_aa_matches = {}
    matched_md_ids = set()
    for model in md_models:
        provider = _source_provider(model, 'models.dev')
        # Prefer strict provider-scoped matches to the already identified AA/OR
        # canonical rows. If there is no unique match, keep this source record
        # separate rather than attaching it by a similar display name.
        matched_aa, ambiguous_aa = _ambiguous_match(
            identity_candidates(provider, model.modelsdev_id, model.canonical_model_id), aa_index
        )
        or_model, ambiguous_or = _match_openrouter(
            provider, (model.modelsdev_id, model.canonical_model_id), or_index
        )
        md_aa_matches[model.pk] = matched_aa
        md_or_matches[model.pk] = or_model
        if matched_aa:
            matched_md_ids.add(model.pk)
            matched_aa_ids.add(matched_aa.pk)
        elif or_model:
            matched_md_ids.add(model.pk)
            matched_or_ids.add(or_model.pk)
        if ambiguous_aa or ambiguous_or:
            ambiguous.append({
                'source': 'models.dev',
                'source_id': model.modelsdev_id,
                'candidate_count': 'multiple',
            })

    or_bench_by_key = defaultdict(list)
    for bench in or_benches:
        provider = _provider_from_id(bench.model_permaslug)
        key = identity_key(provider, bench.model_permaslug)
        if key:
            or_bench_by_key[key].append(bench)

    canonical_items = {}
    model_conflicts = []

    def add_item(provider_hint, name, identifier, **sources):
        provider_token = normalize_provider(provider_hint)
        source_id = identifier or name
        key = identity_key(provider_token, source_id)
        if not key:
            return
        or_model = sources.get('openrouter_model')
        aa_model = sources.get('aa_model')
        aa_bench = sources.get('aa_bench')
        md_model = sources.get('modelsdev_model')
        if md_model:
            provider = _source_provider(md_model, 'models.dev')
        elif aa_model:
            provider = _source_provider(aa_model, 'artificial-analysis')
        elif or_model:
            provider = _source_provider(or_model, 'openrouter')
        else:
            provider = provider_hint

        source_id_candidates = _make_aliases(
            getattr(or_model, 'openrouter_id', ''),
            (f'{aa_model.source_endpoint}#{aa_model.source_id}' if aa_model and aa_model.source_endpoint and aa_model.source_id else getattr(aa_model, 'source_id', '')),
            getattr(aa_model, 'slug', ''),
            getattr(md_model, 'modelsdev_id', ''),
        )
        or_benchmarks = []
        if or_model:
            or_provider = _source_provider(or_model, 'openrouter')
            or_benchmarks = or_bench_by_key.get(
                identity_key(or_provider, or_model.openrouter_id), []
            )

        slug_candidate = _first_non_empty(
            getattr(aa_model, 'slug', ''),
            getattr(or_model, 'canonical_slug', ''),
            getattr(md_model, 'modelsdev_id', ''),
            getattr(or_model, 'openrouter_id', ''),
            name,
        ) or name
        row = _build_row(
            provider_slug=provider,
            provider_name=provider,
            name=name or slug_candidate,
            canonical_source_id=slug_candidate,
            openrouter_model=or_model,
            aa_model=aa_model,
            aa_bench=aa_bench,
            modelsdev_model=md_model,
            or_benchmarks=or_benchmarks,
        )
        if key in canonical_items:
            # Two source records that normalize to the same provider/model key
            # are not silently overwritten. Preserve the second source as a
            # separate explicit row if its source identifier differs.
            existing = canonical_items[key]
            if set(existing['aliases']).isdisjoint(source_id_candidates):
                identity = ','.join(source_id_candidates) or str(source_id)
                digest = hashlib.sha1(identity.encode('utf-8')).hexdigest()[:8]
                alternate_key = f'{key}::source:{normalize_slug(source_id)}:{digest}'
                row['sources'] = list(dict.fromkeys(row['sources'] + ['identity-conflict']))
                canonical_items[alternate_key] = row
                model_conflicts.append({'identity_key': key, 'incoming_source_id': source_id})
            else:
                existing['aliases'] = _make_aliases(*existing['aliases'], *source_id_candidates)
                for source_name in row['sources']:
                    if source_name not in existing['sources']:
                        existing['sources'].append(source_name)
                if row['raw_data'].get('models_dev') and not existing['raw_data'].get('models_dev'):
                    existing['raw_data']['models_dev'] = row['raw_data']['models_dev']
                    existing['modelsdev_id'] = row['modelsdev_id']
                    existing['family'] = existing['family'] or row['family']
                    existing['input_modalities'] = existing['input_modalities'] or row['input_modalities']
                    existing['output_modalities'] = existing['output_modalities'] or row['output_modalities']
                    existing['is_open_weight'] = row['is_open_weight']
                    existing['reasoning'] = row['reasoning']
                    existing['tool_call'] = row['tool_call']
                    existing['structured_output'] = row['structured_output']
        else:
            canonical_items[key] = row

    for aa_model in aa_models:
        provider = _source_provider(aa_model, 'artificial-analysis')
        or_model = aa_or_matches.get(aa_model.pk)
        add_item(
            provider,
            aa_model.name,
            aa_model.slug,
            openrouter_model=or_model,
            aa_model=aa_model,
            aa_bench=aa_bench_by_slug.get(aa_model.slug),
            modelsdev_model=None,
        )

    for or_model in or_models:
        if or_model.pk in matched_or_ids:
            continue
        provider = _source_provider(or_model, 'openrouter')
        add_item(provider, or_model.name, or_model.openrouter_id, openrouter_model=or_model)

    for md_model in md_models:
        aa_model = md_aa_matches.get(md_model.pk)
        or_model = md_or_matches.get(md_model.pk)
        if aa_model or or_model:
            # Reattach models.dev metadata to the exact row populated by its
            # primary source, rather than adding another canonical record.
            provider = _source_provider(aa_model, 'artificial-analysis') if aa_model else _source_provider(or_model, 'openrouter')
            target_id = aa_model.slug if aa_model else or_model.openrouter_id
            target_key = identity_key(provider, target_id)
            existing = canonical_items.get(target_key)
            if existing:
                _enrich_from_modelsdev(existing, md_model)
                matched_md_ids.add(md_model.pk)
                continue
        add_item(_source_provider(md_model, 'models.dev'), md_model.name, md_model.modelsdev_id,
                 modelsdev_model=md_model)

    items = list(canonical_items.values())
    if not items:
        return {'status': 'skipped', 'reason': 'Normalization yielded no canonical rows.'}

    # Produce deterministic unique public slugs. Keep existing slugs where
    # unique; only namespace true collisions by provider, then use a stable
    # short digest as a final collision guard.
    slug_groups = defaultdict(list)
    for row in items:
        slug_groups[slugify(str(row['canonical_slug'])) or 'model'].append(row)
    for base_slug, group in slug_groups.items():
        if len(group) > 1:
            for row in group:
                row['canonical_slug'] = f"{row['provider_slug'] or 'model'}-{base_slug}"
    used_slugs = set()
    for row in sorted(items, key=lambda item: (item['provider_slug'], item['canonical_slug'], item['name'])):
        base_slug = slugify(str(row['canonical_slug'])) or 'model'
        if base_slug in used_slugs:
            identity = f"{row['provider_slug']}:{','.join(row['aliases'])}:{row['name']}"
            suffix = hashlib.sha1(identity.encode('utf-8')).hexdigest()[:8]
            base_slug = f'{base_slug}-{suffix}'
        row['canonical_slug'] = base_slug
        used_slugs.add(base_slug)

    for row in items:
        row['_price_conflicts'] = row.pop('_price_conflicts', [])
        row['_metric_conflicts'] = row.pop('_metric_conflicts', [])
        model_conflicts.extend(row['_price_conflicts'])
        model_conflicts.extend(row['_metric_conflicts'])
        row['raw_data']['identity_match'] = {
            'strategy': 'provider-scoped exact normalized ID/alias',
            'confidence': 'high' if len(row['sources']) > 1 else 'source-only',
        }

    scored = [row for row in items if row['rankllms_index'] is not None]
    scored.sort(key=lambda row: (row['rankllms_index'], row['coding_index'] or -1), reverse=True)
    for rank, row in enumerate(scored, start=1):
        row['rank_overall'] = rank

    coding_ranked = sorted(
        (row for row in items if row['coding_index'] is not None),
        key=lambda row: row['coding_index'], reverse=True,
    )
    for rank, row in enumerate(coding_ranked, start=1):
        row['rank_coding'] = rank

    reasoning_ranked = sorted(
        (row for row in items if row['gpqa_diamond'] is not None or row['math_index'] is not None),
        key=lambda row: (row['gpqa_diamond'] or -1, row['math_index'] or -1), reverse=True,
    )
    for rank, row in enumerate(reasoning_ranked, start=1):
        row['rank_reasoning'] = rank

    value_ranked = []
    for row in items:
        total_price = (row['prompt_price_per_1m'] or Decimal('0')) + (row['completion_price_per_1m'] or Decimal('0'))
        if row['rankllms_index'] is not None and row['is_free'] is False and total_price > 0:
            value_ranked.append((row['rankllms_index'] / float(total_price), row))
    value_ranked.sort(key=lambda item: item[0], reverse=True)
    for rank, (_score, row) in enumerate(value_ranked, start=1):
        row['rank_value'] = rank

    model_fields = [
        'canonical_slug', 'name', 'provider', 'author_slug', 'openrouter_id', 'aa_slug',
        'modelsdev_id', 'family', 'version', 'aliases', 'category', 'status', 'license',
        'description', 'release_date', 'last_verified_at', 'input_modalities', 'output_modalities',
        'media_metrics', 'is_open_weight', 'is_free', 'reasoning', 'tool_call', 'structured_output',
        'rankllms_index', 'rank_overall', 'rank_coding', 'rank_reasoning', 'rank_value',
        'intelligence_index', 'coding_index', 'agentic_index',
        'finance_and_accounting_index', 'strategy_and_ops_index', 'legal_index',
        'healthcare_and_medical_index', 'engineering_index', 'economics_index',
        'math_index', 'terminalbench_hard',
        'terminalbench_v2_1', 'gpqa_diamond', 'mmlu_pro', 'hle', 'livecodebench', 'scicode',
        'math_500', 'aime_25', 'design_arena_elo', 'design_arena_win_rate', 'ifbench', 'lcr',
        'tau2', 'tau_banking', 'context_length', 'max_output_tokens', 'prompt_price_per_1m',
        'completion_price_per_1m', 'aa_cache_hit_price_per_1m', 'aa_cache_write_price_per_1m',
        'tokens_per_second', 'time_to_first_token',
        'time_to_first_answer_token', 'end_to_end_response_time', 'has_openrouter',
        'has_artificial_analysis', 'has_design_arena', 'sources', 'raw_data',
    ]
    rankindex_objects = [RankIndex(**{field: row.get(field) for field in model_fields}) for row in items]

    with transaction.atomic():
        RankIndex.objects.all().delete()
        RankIndex.objects.bulk_create(rankindex_objects, batch_size=250)

    return {
        'status': 'success',
        'total_merged_models': len(rankindex_objects),
        'ranked_models': len(scored),
        'source_ormodels': len(or_models),
        'source_orbench': len(or_benches),
        'source_aamodels': len(aa_models),
        'source_aabanch': len(aa_benches),
        'source_modelsdev': len(md_models),
        'unmatched_openrouter': max(0, len(or_models) - len(matched_or_ids)),
        'unmatched_aamodels': max(0, len(aa_models) - len(matched_aa_ids)),
        'unmatched_modelsdev': max(0, len(md_models) - len(matched_md_ids)),
        'ambiguous_matches': len(ambiguous),
        'conflicts': len(model_conflicts),
        'conflict_details': model_conflicts[:100],
        'ambiguous_details': ambiguous[:100],
    }
