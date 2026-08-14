from django.contrib import admin
from django.urls import path
from django.http import JsonResponse
from llms.api import api


from django.shortcuts import render

def root_home(request):
    return render(request, 'docs_portal.html')


urlpatterns = [
    path('', root_home, name='root_home'),
    path('admin/', admin.site.urls),
    path('api/v1/', api.urls),
]

