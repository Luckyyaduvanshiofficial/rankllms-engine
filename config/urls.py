from django.contrib import admin
from django.urls import path
from django.http import JsonResponse, HttpResponse
from django.db import DatabaseError, connection
from django.shortcuts import render
from llms.api import api
from llms.seo import robots_txt, sitemap_xml
from llms.seo_context import (
    get_seo_context,
    item_list_jsonld,
    leaderboard_rows,
    models_rows,
    rankindex_rows,
)
from llms.models import RankIndex
from llms.settings_views import data_sync_action, data_sync_run_status, data_sync_settings


def root_home(request):
    return render(request, 'docs_portal.html')


def leaderboard_page(request):
    return render(request, 'leaderboard.html')


def llm_leaderboard_page(request):
    ctx = get_seo_context('llm-leaderboard')
    ctx.update({
        'seed_rows_html': leaderboard_rows(50),
        'json_ld_items': item_list_jsonld(10),
        'total_models': RankIndex.objects.count(),
    })
    return render(request, 'llm_leaderboard.html', ctx)


def benchmarks_page(request):
    return render(request, 'benchmarks.html')


def ormodels_page(request):
    return render(request, 'ormodels.html')


def orbench_page(request):
    return render(request, 'orbench.html')


def aamodels_page(request):
    return render(request, 'aamodels.html')


def aabanch_page(request):
    return render(request, 'aabanch.html')


def modelsdev_page(request):
    return render(request, 'modelsdev.html')


def rankllms_page(request):
    ctx = get_seo_context('rankllms')
    ctx.update({
        'total_models': RankIndex.objects.count(),
        'top_rows_html': rankindex_rows(10),
    })
    return render(request, 'rankindex.html', ctx)


def rankllms_models_page(request):
    ctx = get_seo_context('rankllms-models')
    ctx.update({
        'total_models': RankIndex.objects.count(),
        'seed_rows_html': models_rows(50),
    })
    return render(request, 'rankllms_models.html', ctx)


def compare_page(request):
    return render(request, 'compare.html')


def cards_page(request):
    return render(request, 'cards.html')


def agent_guide_page(request):
    return render(request, 'agent_guide.html')


def ping_view(request):
    return HttpResponse("pong", content_type="text/plain", status=200)


def health_view(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
        latest = RankIndex.objects.order_by('-updated_at').values_list('updated_at', flat=True).first()
        return JsonResponse({
            'status': 'healthy',
            'service': 'RankLLMs Engine',
            'database': 'connected',
            'canonical_models': RankIndex.objects.count(),
            'data_snapshot_time': latest.isoformat() if latest else None,
        }, status=200)
    except DatabaseError:
        return JsonResponse({
            'status': 'unavailable',
            'service': 'RankLLMs Engine',
            'database': 'unavailable',
        }, status=503)


urlpatterns = [
    path('', root_home, name='root_home'),
    path('leaderboard', leaderboard_page, name='leaderboard_page'),
    path('benchmarks', benchmarks_page, name='benchmarks_page'),
    # Source pages — data shown as-is from each provider
    path('ormodels', ormodels_page, name='ormodels_page'),
    path('orbench', orbench_page, name='orbench_page'),
    path('aamodels', aamodels_page, name='aamodels_page'),
    path('aabanch', aabanch_page, name='aabanch_page'),
    path('modelsdev', modelsdev_page, name='modelsdev_page'),
    # Merged source of truth (rankindex) — /rankllms is the product-facing path
    path('rankllms', rankllms_page, name='rankllms_page'),
    path('rankindex', rankllms_page, name='rankindex_page'),
    # Full model catalog from rankindex
    path('rankllms/models', rankllms_models_page, name='rankllms_models_page'),
    # Leaderboard from merged rankindex (product path); legacy /leaderboard kept
    path('llm-leaderboard', llm_leaderboard_page, name='llm_leaderboard_page'),
    # Utility pages linked from footers/home
    path('compare', compare_page, name='compare_page'),
    path('cards', cards_page, name='cards_page'),
    path('agent-guide', agent_guide_page, name='agent_guide_page'),
    path('ping', ping_view, name='ping_view'),
    path('health', health_view, name='health_view'),
    path('healthz', health_view, name='healthz_view'),
    path('settings/data-sync/', data_sync_settings, name='data_sync_settings'),
    path('settings/data-sync/action/', data_sync_action, name='data_sync_action'),
    path('settings/data-sync/runs/<int:run_id>/', data_sync_run_status, name='data_sync_run_status'),
    path('admin/', admin.site.urls),
    path('api/v1/', api.urls),

    # SEO surfaces — must come before nothing (exact paths, no conflicts)
    path('robots.txt', robots_txt, name='robots_txt'),
    path('sitemap.xml', sitemap_xml, name='sitemap_xml'),
]

