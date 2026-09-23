from django.contrib import admin
from django.urls import path
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render
from llms.api import api


def root_home(request):
    return render(request, 'docs_portal.html')


def leaderboard_page(request):
    return render(request, 'leaderboard.html')


def benchmarks_page(request):
    return render(request, 'benchmarks.html')


def ormodels_page(request):
    return render(request, 'ormodels.html')


def orbench_page(request):
    return render(request, 'orbench.html')


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
    path('ping', ping_view, name='ping_view'),
    path('health', health_view, name='health_view'),
    path('healthz', health_view, name='healthz_view'),
    path('admin/', admin.site.urls),
    path('api/v1/', api.urls),
]



