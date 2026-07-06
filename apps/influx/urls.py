# apps/influx/urls.py

from django.urls import path
from .views import SystemHealthView, SystemHealthLatestView
from .dashboard_views import DashboardOverviewView, DailyEnergyView, PlantOverviewView, PlantPowerTrendView, PlantElectricalTrendView

from .inverter_views import InverterOverviewView, InverterPowerTrendView
from .inverter_detail_views import InverterDetailView, InverterDetailPowerTrendView, InverterDailyEnergyView
from .pv_strings_views import InverterPvStringsView
from .meter_views import MeterOverviewView
from .analytics_views import AnalyticsMetricsListView, AnalyticsView
from .installer_views import InstallerOverviewView
from .weather_views import WeatherSnapshotView

urlpatterns = [
    path('system-health/',          SystemHealthView.as_view(),       name='system-health'),
    path('system-health/latest/',   SystemHealthLatestView.as_view(), name='system-health-latest'),
    path('dashboard/overview/',     DashboardOverviewView.as_view(),  name='dashboard-overview'),
    path('dashboard/daily-energy/', DailyEnergyView.as_view(),        name='daily-energy'),
     # Plant overview page
    path('plant/overview/',         PlantOverviewView.as_view(),      name='plant-overview'),
    path('plant/power-trend/',      PlantPowerTrendView.as_view(),    name='plant-power-trend'),
    path('plant/electrical-trend/', PlantElectricalTrendView.as_view(), name='plant-electrical-trend'),

    # Inverter overview
    path('inverter/overview/',       InverterOverviewView.as_view(),    name='inverter-overview'),
    path('inverter/power-trend/',    InverterPowerTrendView.as_view(),  name='inverter-power-trend'),

    # Inverter detail page
    path('inverter/detail/', InverterDetailView.as_view()),
    path('inverter/detail/power-trend/', InverterDetailPowerTrendView.as_view()),
    path('inverter/detail/daily-energy/', InverterDailyEnergyView.as_view()),

    # PV string Current Inverter
    path('inverter/pv-strings/', InverterPvStringsView.as_view()),

    # Meter overview
    path('meter/overview/', MeterOverviewView.as_view(), name='meter-overview'),

    # Analytics
    path('analytics/', AnalyticsView.as_view()),
    path('analytics/metrics/', AnalyticsMetricsListView.as_view()),

    # Installer overview
    path('installer/overview/', InstallerOverviewView.as_view()),

    # Weather station Page
    path('weather/', WeatherSnapshotView.as_view()),
]