# apps/sites/urls.py

from django.urls import path
from .views import (
    CustomerListView,
    CustomerDetailView,
    SiteListView,
    SiteDetailView,
    DeviceListView,
    DeviceDetailView,
)

urlpatterns = [
    path('customers/',        CustomerListView.as_view(),   name='customer-list'),
    path('customers/<int:pk>/', CustomerDetailView.as_view(), name='customer-detail'),
    path('sites/',            SiteListView.as_view(),       name='site-list'),
    path('sites/<int:pk>/',   SiteDetailView.as_view(),     name='site-detail'),
    path('devices/',          DeviceListView.as_view(),     name='device-list'),
    path('devices/<int:pk>/', DeviceDetailView.as_view(),   name='device-detail'),
]