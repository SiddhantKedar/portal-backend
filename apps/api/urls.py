# apps/api/urls.py
# Central URL file for all API endpoints
# All routes are prefixed with /api/v1/

from django.urls import path, include

urlpatterns = [
    path('auth/', include('apps.users.urls')),
    path('', include('apps.sites.urls')),
    path('influx/', include('apps.influx.urls')),
]