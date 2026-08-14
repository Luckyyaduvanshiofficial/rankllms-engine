from django.contrib import admin
from django.urls import path
from django.http import JsonResponse
from llms.api import api


from django.http import JsonResponse, HttpResponse
from django.shortcuts import render

def root_home(request):
    return render(request, 'docs_portal.html')

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
    path('ping', ping_view, name='ping_view'),
    path('health', health_view, name='health_view'),
    path('healthz', health_view, name='healthz_view'),
    path('admin/', admin.site.urls),
    path('api/v1/', api.urls),
]



