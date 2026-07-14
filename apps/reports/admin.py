# apps/reports/admin.py
from django.contrib import admin
from .models import DailySiteSnapshot


@admin.register(DailySiteSnapshot)
class DailySiteSnapshotAdmin(admin.ModelAdmin):
    list_display = ('site', 'date', 'energy_today_kwh', 'performance_ratio_pct', 'meter_status')
    list_filter = ('meter_status', 'date')
    search_fields = ('site__name',)
    ordering = ('-date',)