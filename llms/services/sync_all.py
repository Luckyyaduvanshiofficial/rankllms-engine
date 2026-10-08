"""Orchestrate source snapshots, then atomically rebuild the canonical catalog."""

import logging
import re
import time

from django.db import transaction

from llms.models import (
    AABench,
    AAModel,
    AppRanking,
    DataSourceConfig,
    LLMModel,
    ModelBenchmark,
    ModelPricing,
    ModelSpecification,
    ModelsDevModel,
    ORBench,
    ORModel,
    Provider,
    RankIndex,
    TaskClassification,
)
from llms.services.artificial_analysis_sync import sync_artificial_analysis_data
from llms.services.artificial_analysis_client import fetch_language_models, fetch_media_models
from llms.services.merge_rankindex import merge_and_build_rankindex
from llms.services.models_dev_sync import fetch_models_dev_catalog, sync_models_dev_catalog
from llms.services.openrouter_sync import fetch_openrouter_snapshot, sync_openrouter_models
from llms.services.sync_dedicated_tables import sync_artificial_analysis_tables
from llms.services.source_http import get_rate_limit_snapshot

logger = logging.getLogger(__name__)

SOURCE_KEYS = ('openrouter', 'artificial_analysis', 'models_dev')


def _resolve_sources(sources):
    if sources is None or sources == 'all':
        selected = SOURCE_KEYS
    elif isinstance(sources, str):
        selected = (sources,)
    else:
        selected = tuple(sources)
    selected = tuple(dict.fromkeys(selected))
    invalid = set(selected) - set(SOURCE_KEYS)
    if invalid:
        raise ValueError(f'Unknown source(s): {", ".join(sorted(invalid))}')
    return selected


def _safe_error(error):
    message = str(error or '')
    message = re.sub(
        r'(?i)(api[_-]?key|access[_-]?token|secret|authorization)(["\'=:\s]+)[^\s,;]+',
        r'\1\2[redacted]',
        message,
    )
    return message[:500]


def _source_counts(source, details):
    if source in {'openrouter', 'artificial_analysis'}:
        raw = details.get('raw_tables') or {}
        catalog = details.get('catalog') or {}
        analytics_received = int(catalog.get('analytics_records_fetched') or 0) if source == 'openrouter' else 0
        model_count = int(raw.get('models_fetched') or raw.get('ormodels_count') or raw.get('aamodels_count') or 0)
        benchmark_count = int(raw.get('benchmarks_fetched') or raw.get('orbench_count') or raw.get('aabanch_count') or 0)
        source_received = int(catalog.get('total_fetched') or model_count) if source == 'openrouter' else model_count
        source_skipped = int(raw.get('records_skipped') or 0)
        if source == 'openrouter':
            source_skipped = max(source_skipped, int(catalog.get('skipped') or 0))
        return {
            'received': source_received + benchmark_count + analytics_received,
            'added': int(raw.get('models_added') or 0) + int(raw.get('benchmarks_added') or 0) + int(catalog.get('analytics_records_added') or 0),
            'updated': int(raw.get('models_updated') or 0) + int(raw.get('benchmarks_updated') or 0) + int(catalog.get('analytics_records_updated') or 0),
            'skipped': source_skipped + int(catalog.get('analytics_records_skipped') or 0),
            'unchanged': int(raw.get('models_unchanged') or 0) + int(raw.get('benchmarks_unchanged') or 0) + int(catalog.get('analytics_records_unchanged') or 0),
        }
    return {
        'received': int(details.get('models_fetched') or 0),
        'added': int(details.get('created') or 0),
        'updated': int(details.get('updated') or 0),
        'skipped': int(details.get('records_skipped') or 0),
        'unchanged': int(details.get('unchanged') or details.get('models_unchanged') or 0),
    }


def _source_enabled_map(source_keys):
    saved = {
        row.source: row.enabled
        for row in DataSourceConfig.objects.filter(source__in=source_keys)
    }
    return {key: saved.get(key, True) for key in source_keys}


def prepare_source_snapshots(sources=None):
    """Fetch every selected source before opening any snapshot write transaction."""
    selected = _resolve_sources(sources)
    enabled = _source_enabled_map(selected)
    snapshots = {}
    errors = {}
    for source in selected:
        if not enabled[source]:
            continue
        try:
            if source == 'openrouter':
                snapshots[source] = fetch_openrouter_snapshot()
            elif source == 'artificial_analysis':
                snapshots[source] = {
                    'models': fetch_language_models(),
                    'media': fetch_media_models(),
                }
            else:
                snapshots[source] = fetch_models_dev_catalog()
        except Exception as exc:
            errors[source] = exc
    return {
        'selected': selected,
        'enabled': enabled,
        'snapshots': snapshots,
        'errors': errors,
    }


def run_master_sync(sources=None, *, prepared=None):
    """Sync selected sources and preserve the last good snapshot on failures.

    Each source is fetched and validated before its own transaction writes.
    The canonical table is replaced only after normalization succeeds and is
    itself an atomic delete-and-bulk-insert operation.
    """
    started = time.monotonic()
    selected = _resolve_sources(sources)
    prepared = prepared or prepare_source_snapshots(selected)
    enabled = prepared['enabled']
    snapshots = prepared['snapshots']
    fetch_errors = prepared['errors']
    source_results = []
    successful = 0
    failed = 0
    warnings = []

    for source in selected:
        if not enabled[source]:
            source_results.append({'source': source, 'status': 'disabled'})
            continue
        logger.info('sync.source.started', extra={'source': source})
        try:
            if source in fetch_errors:
                raise fetch_errors[source]
            snapshot = snapshots[source]
            if source == 'openrouter':
                main = sync_openrouter_models(snapshot=snapshot)
                raw = main.get('raw_tables', {})
                details = {'catalog': main, 'raw_tables': raw}
                source_warnings = list(main.get('warnings') or [])
                if raw.get('warning'):
                    source_warnings.append(raw['warning'])
            elif source == 'artificial_analysis':
                aa_models = snapshot['models']
                aa_media = snapshot['media']
                with transaction.atomic():
                    main = sync_artificial_analysis_data(aa_models)
                    raw = sync_artificial_analysis_tables(aa_models, aa_media)
                details = {'catalog': main, 'raw_tables': raw}
                source_warnings = []
            else:
                details = sync_models_dev_catalog(snapshot=snapshot)
                source_warnings = []
                if details.get('error'):
                    raise RuntimeError('models.dev sync did not complete successfully.')
            successful += 1
            warnings.extend(f'{source}: {warning}' for warning in source_warnings)
            counts = _source_counts(source, details)
            result = {
                'source': source,
                'status': 'warning' if source_warnings else 'succeeded',
                'summary': details,
                'records_received': counts['received'],
                'records_added': counts['added'],
                'records_updated': counts['updated'],
                'records_skipped': counts['skipped'],
                'records_unchanged': counts['unchanged'],
                'warnings': source_warnings,
                'rate_limit': get_rate_limit_snapshot(source),
            }
            source_results.append(result)
            logger.info(
                'sync.source.completed',
                extra={
                    'source': source,
                    'records_received': result['records_received'],
                    'records_added': result['records_added'],
                    'records_updated': result['records_updated'],
                    'warning_count': len(source_warnings),
                },
            )
        except Exception as exc:
            failed += 1
            message = _safe_error(exc)
            source_results.append({
                'source': source,
                'status': 'failed',
                'error': message,
                'error_type': type(exc).__name__,
            })
            logger.error(
                'sync.source.failed',
                extra={'source': source, 'error_type': type(exc).__name__, 'error': message},
            )

    merge_summary = {}
    if successful:
        try:
            merge_summary = merge_and_build_rankindex()
            if merge_summary.get('status') != 'success':
                failed += 1
                warnings.append(merge_summary.get('reason', 'Canonical merge did not complete.'))
                source_results.append({
                    'source': 'canonical_merge',
                    'status': 'failed',
                    'error': merge_summary.get('reason', 'Canonical merge did not complete.'),
                })
        except Exception as exc:
            failed += 1
            merge_summary = {'status': 'failed', 'error': _safe_error(exc)}
            source_results.append({
                'source': 'canonical_merge',
                'status': 'failed',
                'error': _safe_error(exc),
                'error_type': type(exc).__name__,
            })
            logger.exception('sync.canonical_merge.failed', extra={'error_type': type(exc).__name__})
    else:
        merge_summary = {'status': 'skipped', 'reason': 'No enabled source completed successfully.'}

    fetched = sum(result.get('records_received', 0) for result in source_results)
    added = sum(result.get('records_added', 0) for result in source_results)
    updated = sum(result.get('records_updated', 0) for result in source_results)
    skipped = sum(result.get('records_skipped', 0) for result in source_results)
    elapsed = round(time.monotonic() - started, 2)
    status = (
        'skipped' if not successful and not failed
        else 'failed' if failed and not successful
        else 'partial' if failed or warnings
        else 'succeeded'
    )
    report = {
        'status': status,
        'elapsed_seconds': elapsed,
        'selected_sources': list(selected),
        'sources_successful': successful,
        'sources_failed': failed,
        'records_received': fetched,
        'records_added': added,
        'records_updated': updated,
        'records_skipped': skipped,
        'records_unchanged': max(0, fetched - added - updated - skipped),
        'sources': source_results,
        'merge_summary': merge_summary,
        'total_providers': Provider.objects.count(),
        'total_models': LLMModel.objects.count(),
        'total_specs': ModelSpecification.objects.count(),
        'total_pricing': ModelPricing.objects.count(),
        'total_benchmarks': ModelBenchmark.objects.count(),
        'total_openrouter_models': ORModel.objects.count(),
        'total_openrouter_benchmarks': ORBench.objects.count(),
        'total_artificial_analysis_models': AAModel.objects.count(),
        'total_artificial_analysis_benchmarks': AABench.objects.count(),
        'total_modelsdev': ModelsDevModel.objects.count(),
        'total_rankindex': RankIndex.objects.count(),
        'total_app_rankings': AppRanking.objects.count(),
        'total_task_classifications': TaskClassification.objects.count(),
        'warnings': warnings,
    }
    logger.info(
        'sync.completed',
        extra={
            'status': status,
            'duration_seconds': elapsed,
            'records_received': fetched,
            'records_added': added,
            'records_updated': updated,
            'sources_failed': failed,
        },
    )
    return report
