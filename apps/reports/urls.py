# apps/reports/urls.py
from django.urls import path
from .views import SiteReportView

urlpatterns = [
    path('summary/', SiteReportView.as_view(), name='site-report-summary'),
]