"""Small, database-backed runner for staff-triggered synchronization jobs."""

from __future__ import annotations

import logging
import re
import threading
import time
from datetime import timedelta

from django.db import IntegrityError, close_old_connections, transaction
from django.db.models import Q
from django.utils import timezone

from llms.models import DataSourceConfig, SyncRun
from llms.services.sync_all import SOURCE_KEYS, prepare_source_snapshots, run_master_sync

logger = logging.getLogger(__name__)


class SyncAlreadyRunning(RuntimeError):
    pass


def sanitize_error(value: str) -> str:
    text = str(value or '')
    text = re.sub(
        r'(?i)(api[_-]?key|access[_-]?token|secret|authorization)(["\'=:\s]+)[^\s,;]+',
        r'\1\2[redacted]',
        text,
    )
    return text[:1000]


def enqueue_sync(*, source='all', dry_run=False, user=None) -> SyncRun:
    if source != 'all' and source not in SOURCE_KEYS:
        raise ValueError('Unknown data source.')
    stale_before = timezone.now() - timedelta(minutes=30)
    SyncRun.objects.filter(active_key='active', started_at__lt=stale_before).update(
        status='failed',
        active_key=None,
        finished_at=timezone.now(),
        error_count=1,
        error_summary='Sync worker stopped before recording a result.',
    )
    try:
        with transaction.atomic():
            run = SyncRun.objects.create(
                source=source,
                status='queued',
                dry_run=bool(dry_run),
                triggered_by=user if getattr(user, 'is_authenticated', False) else None,
                active_key='active',
            )
    except IntegrityError as exc:
        raise SyncAlreadyRunning('A data sync is already queued or running.') from exc

    worker = threading.Thread(
        target=_execute_sync,
        args=(run.pk,),
        name=f'rankllms-sync-{run.pk}',
        daemon=True,
    )
    try:
        worker.start()
    except RuntimeError as exc:
        SyncRun.objects.filter(pk=run.pk).update(
            status='failed',
            active_key=None,
            finished_at=timezone.now(),
            error_count=1,
            error_summary='Sync worker could not be started.',
        )
        raise RuntimeError('Sync worker could not be started.') from exc
    return run


def _execute_sync(run_id: int):
    close_old_connections()
    started = time.monotonic()
    try:
        run = SyncRun.objects.get(pk=run_id)
        SyncRun.objects.filter(pk=run_id).update(status='running', started_at=timezone.now())
        logger.info('sync.run.started', extra={'run_id': run_id, 'source': run.source, 'dry_run': run.dry_run})

        selected = None if run.source == 'all' else (run.source,)
        if run.dry_run:
            prepared = prepare_source_snapshots(sources=selected)
            with transaction.atomic():
                report = run_master_sync(sources=selected, prepared=prepared)
                transaction.set_rollback(True)
        else:
            report = run_master_sync(sources=selected)

        source_errors = [
            f"{item.get('source')}: {item.get('error')}"
            for item in report.get('sources', [])
            if item.get('status') == 'failed'
        ]
        message = '; '.join(sanitize_error(error) for error in source_errors)
        status = 'dry_run' if run.dry_run else report.get('status', 'failed')
        finished = timezone.now()
        SyncRun.objects.filter(pk=run_id).update(
            status=status,
            finished_at=finished,
            duration_seconds=round(time.monotonic() - started, 2),
            records_received=max(0, int(report.get('records_received') or 0)),
            records_added=max(0, int(report.get('records_added') or 0)),
            records_updated=max(0, int(report.get('records_updated') or 0)),
            records_skipped=max(0, int(report.get('records_skipped') or 0)),
            error_count=len(source_errors),
            error_summary=message,
            summary=report,
            active_key=None,
        )
        logger.info(
            'sync.run.completed',
            extra={
                'run_id': run_id,
                'status': status,
                'duration_seconds': round(time.monotonic() - started, 2),
                'records_received': report.get('records_received', 0),
            },
        )
    except Exception as exc:
        message = sanitize_error(f'{type(exc).__name__}: {exc}')
        SyncRun.objects.filter(pk=run_id).update(
            status='failed',
            finished_at=timezone.now(),
            duration_seconds=round(time.monotonic() - started, 2),
            error_count=1,
            error_summary=message,
            active_key=None,
        )
        logger.error(
            'sync.run.failed',
            extra={'run_id': run_id, 'error_type': type(exc).__name__, 'error': message},
        )
    finally:
        close_old_connections()


def source_health():
    """Build source status cards from persisted settings and the last run."""
    from django.conf import settings

    labels = dict(DataSourceConfig.SOURCE_CHOICES)
    configs = {config.source: config for config in DataSourceConfig.objects.all()}
    latest_runs = {}
    for run in SyncRun.objects.order_by('-started_at')[:100]:
        if run.dry_run:
            continue
        if run.source == 'all':
            for item in (run.summary or {}).get('sources', []):
                source = item.get('source')
                if source in labels and source not in latest_runs:
                    latest_runs[source] = (run, item)
        elif run.source in labels and run.source not in latest_runs:
            latest_runs[run.source] = (run, None)
    all_runs = SyncRun.objects.filter(source='all').order_by('-started_at')
    latest_all = all_runs.first()
    summaries = {
        source: {
            'records': 0, 'added': 0, 'updated': 0, 'skipped': 0, 'unchanged': 0,
            'duration': None, 'rate_limit': 'Not reported by current endpoints',
        }
        for source, _label in DataSourceConfig.SOURCE_CHOICES
    }
    summaries['models_dev']['rate_limit'] = 'Public catalog; no key required'
    for source, pair in latest_runs.items():
        run, item = pair
        summaries[source]['records'] = item.get('records_received', 0) if item else run.records_received
        summaries[source]['added'] = item.get('records_added', 0) if item else run.records_added
        summaries[source]['updated'] = item.get('records_updated', 0) if item else run.records_updated
        summaries[source]['skipped'] = item.get('records_skipped', 0) if item else run.records_skipped
        summaries[source]['unchanged'] = item.get('records_unchanged', 0) if item else 0
        summaries[source]['duration'] = run.duration_seconds
        if item:
            snapshot = item.get('rate_limit') or {}
            if snapshot:
                summaries[source]['rate_limit'] = ', '.join(
                    f'{key.replace("_", " ")}: {value}' for key, value in snapshot.items()
                )

    health = []
    credential_available = {
        'openrouter': bool(getattr(settings, 'OPENROUTER_API_KEY', '')),
        'artificial_analysis': bool(getattr(settings, 'ARTIFICIAL_ANALYSIS_API_KEY', '')),
        'models_dev': True,
    }
    for source, label in DataSourceConfig.SOURCE_CHOICES:
        config = configs.get(source)
        latest_pair = latest_runs.get(source)
        last_run = latest_pair[0] if latest_pair else None
        if latest_pair and latest_pair[1] and latest_pair[1].get('warnings'):
            latest_error = '; '.join(map(str, latest_pair[1]['warnings']))
        else:
            latest_error = ''
        latest_source_status = (
            latest_pair[1].get('status') if latest_pair and latest_pair[1] is not None
            else last_run.status if last_run else None
        )
        last_success = None
        last_failure = None
        candidates = SyncRun.objects.filter(Q(source=source) | Q(source='all')).order_by('-started_at')[:100]
        for candidate in candidates:
            if candidate.status == 'dry_run':
                continue
            source_item = next((
                item for item in (candidate.summary or {}).get('sources', [])
                if item.get('source') == source
            ), None) if candidate.source == 'all' else None
            candidate_status = source_item.get('status') if source_item else candidate.status
            if candidate_status in ('succeeded', 'warning', 'partial') and last_success is None:
                last_success = candidate
            if candidate_status == 'failed' and last_failure is None:
                last_failure = candidate
                latest_error = (
                    source_item.get('error', '') if source_item else candidate.error_summary
                )
        if config and not config.enabled:
            status = 'disabled'
        elif not credential_available[source] and source == 'artificial_analysis':
            status = 'warning'
        elif not last_run:
            status = 'warning'
        elif latest_source_status in ('running', 'queued'):
            status = latest_source_status
        elif latest_source_status == 'failed':
            status = 'failed'
        elif latest_source_status in ('partial', 'warning'):
            status = 'warning'
        elif latest_source_status == 'dry_run':
            status = 'warning'
        elif last_success and last_success.finished_at and last_success.finished_at < timezone.now() - timedelta(hours=24):
            status = 'warning'
        else:
            status = 'healthy'
        if source == 'openrouter':
            connection = (
                'Data API key configured'
                if credential_available[source]
                else 'Key missing; public model catalog remains available'
            )
        elif source == 'artificial_analysis':
            connection = 'Server-side API key configured' if credential_available[source] else 'Server-side API key missing'
        else:
            connection = 'Public catalog; no key required'
        health.append({
            'key': source,
            'name': label,
            'enabled': config.enabled if config else True,
            'status': status,
            'connection': connection,
            'last_success': last_success,
            'last_failure': last_failure,
            'last_run': last_run,
            'records_received': summaries[source]['records'],
            'records_added': summaries[source]['added'],
            'records_updated': summaries[source]['updated'],
            'records_skipped': summaries[source]['skipped'],
            'records_unchanged': summaries[source]['unchanged'],
            'duration_seconds': summaries[source]['duration'],
            'rate_limit': summaries[source]['rate_limit'],
            'timeout_seconds': config.timeout_seconds if config else 30,
            'retry_count': config.retry_count if config else 2,
            'latest_error': latest_error,
        })
    return health, latest_all
