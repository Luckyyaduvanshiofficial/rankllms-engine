from django.contrib import admin
from django.urls import path
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render
from llms.api import api


def root_home(request):
    return render(request, 'docs_portal.html')


def leaderboard_page(request):
    return render(request, 'leaderboard.html')


def llm_leaderboard_page(request):
    return render(request, 'llm_leaderboard.html')


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
    return render(request, 'rankindex.html')


def rankllms_models_page(request):
    return render(request, 'rankllms_models.html')


def compare_page(request):
    return render(request, 'compare.html')


def cards_page(request):
    return render(request, 'cards.html')


def agent_guide_page(request):
    return render(request, 'agent_guide.html')


def ping_view(request):
    return HttpResponse("pong", content_type="text/plain", status=200)


def health_view(request):
    return JsonResponse({
        "status": "healthy",
        "service": "RankLLMs Engine",
        "render_keep_alive": True,
    }, status=200)


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
    path('admin/', admin.site.urls),
    path('api/v1/', api.urls),
]



