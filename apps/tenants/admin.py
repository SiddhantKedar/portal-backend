# apps/tenants/admin.py

from django.contrib import admin
from .models import Installer


@admin.register(Installer)
class InstallerAdmin(admin.ModelAdmin):
    list_display  = ('name', 'email', 'phone', 'is_active', 'created_at')
    list_filter   = ('is_active',)
    search_fields = ('name', 'email')
    ordering      = ('name',)