"""Staff-only data operations and integrity views."""

from collections import Counter
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Q
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from llms.models import (
    AABench,
    AAModel,
    DataSourceConfig,
    ModelsDevModel,
    ORBench,
    ORModel,
    RankIndex,
    SyncRun,
)
from llms.services.admin_sync import (
    SyncAlreadyRunning,
    enqueue_sync,
    source_health,
)


@staff_member_required(login_url='/admin/login/')
@require_GET
def data_sync_settings(request):
    sources, latest_all = source_health()
    active_run = SyncRun.objects.filter(active_key='active').first()
    history = SyncRun.objects.select_related('triggered_by').all()[:20]
    integrity = data_integrity_report()
    selected_run = None
    run_id = request.GET.get('run')
    if run_id and run_id.isdigit():
        selected_run = SyncRun.objects.filter(pk=int(run_id)).first()
    return render(request, 'data_sync_settings.html', {
        'sources': sources,
        'history': history,
        'active_run': active_run,
        'latest_all': latest_all,
        'integrity': integrity,
        'selected_run': selected_run,
        'scheduler_enabled': settings.ENABLE_SCHEDULER,
        'sync_interval_hours': settings.SYNC_INTERVAL_HOURS,
    })


@staff_member_required(login_url='/admin/login/')
@require_POST
def data_sync_action(request):
    action = request.POST.get('action', '')
    if action == 'save_source':
        source = request.POST.get('source', '')
        if source not in dict(DataSourceConfig.SOURCE_CHOICES):
            return HttpResponseBadRequest('Unknown data source.')
        try:
            timeout = int(request.POST.get('timeout_seconds', '30'))
            retries = int(request.POST.get('retry_count', '2'))
        except (TypeError, ValueError):
            return HttpResponseBadRequest('Timeout and retry count must be whole numbers.')
        if not 5 <= timeout <= 120 or not 0 <= retries <= 5:
            return HttpResponseBadRequest('Timeout must be 5–120 seconds and retries must be 0–5.')
        config, _ = DataSourceConfig.objects.get_or_create(source=source)
        config.enabled = request.POST.get('enabled') == 'on'
        config.timeout_seconds = timeout
        config.retry_count = retries
        config.save(update_fields=['enabled', 'timeout_seconds', 'retry_count', 'updated_at'])
        messages.success(request, f'{config.get_source_display()} settings saved.')
        return redirect('data_sync_settings')

    if action in ('sync', 'dry_run'):
        source = request.POST.get('source', 'all')
        if source != 'all' and source not in dict(DataSourceConfig.SOURCE_CHOICES):
            return HttpResponseBadRequest('Unknown data source.')
        try:
            run = enqueue_sync(
                source=source,
                dry_run=(action == 'dry_run'),
                user=request.user,
            )
        except SyncAlreadyRunning as exc:
            messages.warning(request, str(exc))
            return redirect('data_sync_settings')
        except ValueError as exc:
            return HttpResponseBadRequest(str(exc))
        messages.info(request, 'Dry run queued.' if action == 'dry_run' else 'Sync queued.')
        return redirect(f'/settings/data-sync/?run={run.pk}')

    return HttpResponseBadRequest('Unknown action.')


@staff_member_required(login_url='/admin/login/')
@require_GET
def data_sync_run_status(request, run_id):
    run = get_object_or_404(SyncRun, pk=run_id)
    return JsonResponse({
        'id': run.pk,
        'source': run.source,
        'status': run.status,
        'dry_run': run.dry_run,
        'started_at': run.started_at.isoformat() if run.started_at else None,
        'finished_at': run.finished_at.isoformat() if run.finished_at else None,
        'duration_seconds': run.duration_seconds,
        'records_received': run.records_received,
        'records_added': run.records_added,
        'records_updated': run.records_updated,
        'records_skipped': run.records_skipped,
        'error_count': run.error_count,
        'error_summary': run.error_summary,
        'summary': run.summary,
    })


def data_integrity_report():
    raw_counts = {
        'OpenRouter models': ORModel.objects.count(),
        'OpenRouter benchmarks': ORBench.objects.count(),
        'Artificial Analysis models': AAModel.objects.count(),
        'Artificial Analysis benchmarks': AABench.objects.count(),
        'models.dev models': ModelsDevModel.objects.count(),
    }
    stale_source_counts = {
        'OpenRouter models': ORModel.objects.filter(is_active=False).count(),
        'OpenRouter benchmarks': ORBench.objects.filter(is_active=False).count(),
        'Artificial Analysis models': AAModel.objects.filter(is_active=False).count(),
        'Artificial Analysis benchmarks': AABench.objects.filter(is_active=False).count(),
        'models.dev models': ModelsDevModel.objects.filter(is_active=False).count(),
    }
    aliases = Counter()
    for values in RankIndex.objects.values_list('aliases', flat=True).iterator(chunk_size=500):
        for value in values or []:
            aliases[value] += 1
    duplicate_aliases = sum(1 for count in aliases.values() if count > 1)
    latest_snapshot = None
    for candidate in SyncRun.objects.filter(dry_run=False).order_by('-started_at')[:100]:
        candidate_merge = (candidate.summary or {}).get('merge_summary') or {}
        if candidate_merge.get('status') == 'success':
            latest_snapshot = candidate
            break
    merge = ((latest_snapshot.summary or {}).get('merge_summary') or {}) if latest_snapshot else {}
    valid_percentages = (
        'gpqa_diamond', 'mmlu_pro', 'hle', 'livecodebench', 'scicode', 'math_500',
        'aime_25', 'ifbench', 'lcr', 'tau2', 'tau_banking', 'terminalbench_hard',
        'terminalbench_v2_1', 'design_arena_win_rate', 'intelligence_index',
        'coding_index', 'agentic_index', 'finance_and_accounting_index',
        'strategy_and_ops_index', 'legal_index', 'healthcare_and_medical_index',
        'engineering_index', 'economics_index',
    )
    invalid_benchmark_conditions = Q(pk__in=[])
    for field in valid_percentages:
        invalid_benchmark_conditions |= Q(**{f'{field}__lt': 0}) | Q(**{f'{field}__gt': 100})
    latest_success = SyncRun.objects.filter(
        status__in=('succeeded', 'partial'),
        finished_at__isnull=False,
    ).order_by('-finished_at').first()
    stale_after = timezone.now() - timedelta(hours=24)
    return {
        'source_records': raw_counts,
        'total_source_records': sum(raw_counts.values()),
        'stale_source_records': sum(stale_source_counts.values()),
        'stale_source_breakdown': stale_source_counts,
        'canonical_models': RankIndex.objects.count(),
        'duplicate_canonical_aliases': duplicate_aliases,
        'unmatched_openrouter_records': merge.get('unmatched_openrouter'),
        'unmatched_aamodel_records': merge.get('unmatched_aamodels'),
        'unmatched_modelsdev_records': merge.get('unmatched_modelsdev'),
        'ambiguous_matches': merge.get('ambiguous_matches'),
        'source_conflicts': merge.get('conflicts'),
        'missing_provider': RankIndex.objects.filter(Q(provider='') | Q(provider__isnull=True)).count(),
        'missing_name': RankIndex.objects.filter(Q(name='') | Q(name__isnull=True)).count(),
        'missing_pricing': RankIndex.objects.filter(
            Q(prompt_price_per_1m__isnull=True) | Q(completion_price_per_1m__isnull=True)
        ).count(),
        'missing_context': RankIndex.objects.filter(context_length__isnull=True).count(),
        'impossible_prices': RankIndex.objects.filter(
            Q(prompt_price_per_1m__lt=0) | Q(completion_price_per_1m__lt=0)
        ).count(),
        'invalid_benchmarks': RankIndex.objects.filter(invalid_benchmark_conditions).count(),
        'orphan_records': int(merge.get('unmatched_openrouter') or 0) + int(merge.get('unmatched_aamodels') or 0) + int(merge.get('unmatched_modelsdev') or 0),
        'stale': bool(latest_success and latest_success.finished_at < stale_after),
        'last_success': latest_success,
        'latest_conflict_details': merge.get('conflict_details', [])[:10],
    }
