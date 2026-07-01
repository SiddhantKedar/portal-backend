# apps/sites/admin.py

from django.contrib import admin
from .models import Customer, Site, Device


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display  = ('name', 'email', 'is_active', 'created_at')   # installer removed
    list_filter   = ('is_active',)
    search_fields = ('name', 'email')


@admin.register(Site)
class SiteAdmin(admin.ModelAdmin):
    list_display  = ('name', 'site_type', 'parent_site', 'customer', 'installer', 'location', 'influx_site_id', 'is_active')
    list_filter   = ('is_active', 'site_type', 'installer')   # filter by installer moved here
    search_fields = ('name', 'influx_site_id')


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display  = ('name', 'device_type', 'site', 'influx_device_id', 'is_active')
    list_filter   = ('device_type', 'is_active')
    search_fields = ('name', 'influx_device_id')