# apps/reports/admin.py
from datetime import timezone, timedelta

from django.contrib import admin
from django.utils.html import format_html

from .models import DailySiteSnapshot

IST = timezone(timedelta(hours=5, minutes=30))


def _hm_ist(dt):
    """Stored-UTC datetime -> 'HH:MM' in IST, or None."""
    return dt.astimezone(IST).strftime('%H:%M') if dt else None


@admin.register(DailySiteSnapshot)
class DailySiteSnapshotAdmin(admin.ModelAdmin):
    list_display = (
        'date', 'site', 'customer',
        'energy','energy_active_export_kwh', 'peak', 'pr', 'cuf',
        'inverters', 'gen_window', 'status',
    )
    list_filter = ('meter_status', 'site__customer', 'site')
    search_fields = ('site__name', 'site__customer__name')
    date_hierarchy = 'date'
    ordering = ('-date', 'site')
    list_select_related = ('site', 'site__customer')
    readonly_fields = ('created_at', 'updated_at')

    @admin.display(description='Customer', ordering='site__customer__name')
    def customer(self, obj):
        return obj.site.customer.name

    @admin.display(description='Energy (kWh)', ordering='energy_today_kwh')
    def energy(self, obj):
        v = obj.energy_today_kwh
        return f'{v:,.0f}' if v is not None else '—'

    @admin.display(description='Peak', ordering='peak_power_kw')
    def peak(self, obj):
        if obj.peak_power_kw is None:
            return '—'
        t = _hm_ist(obj.peak_power_time)
        return f'{obj.peak_power_kw:,.0f} kW @ {t}' if t else f'{obj.peak_power_kw:,.0f} kW'

    @admin.display(description='PR %', ordering='performance_ratio_pct')
    def pr(self, obj):
        v = obj.performance_ratio_pct
        return f'{v:.1f}' if v is not None else '—'

    @admin.display(description='CUF %', ordering='cuf_pct')
    def cuf(self, obj):
        v = obj.cuf_pct
        return f'{v:.1f}' if v is not None else '—'

    @admin.display(description='Inverters')
    def inverters(self, obj):
        total = obj.inverters_total_count
        if total is None:
            return '—'
        on = obj.inverters_online_count or 0
        if total and on == 0:
            color = '#dc2626'   # red: nothing reporting
        elif on < total:
            color = '#e17100'   # amber: partial
        else:
            color = '#497d00'   # olive: all online
        return format_html('<span style="color:{};font-weight:600">{}/{}</span>', color, on, total)

    @admin.display(description='Generation window (IST)')
    def gen_window(self, obj):
        s = _hm_ist(obj.generation_start_time)
        e = _hm_ist(obj.generation_end_time)
        if not s and not e:
            return '—'
        return f'{s or "—"} → {e or "—"}'

    @admin.display(description='Status', ordering='meter_status')
    def status(self, obj):
        if obj.meter_status == 'no_data':
            return format_html('<span style="color:#dc2626;font-weight:600">no data</span>')
        return obj.meter_status