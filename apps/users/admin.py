# apps/users/admin.py

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display  = ('email', 'full_name', 'role', 'installer', 'whatsapp_number', 'is_active')
    list_filter   = ('role', 'is_active')
    search_fields = ('email', 'first_name', 'last_name')
    ordering      = ('email',)

    fieldsets = (
        (None,           {'fields': ('email', 'password')}),
        ('Personal',     {'fields': ('first_name', 'last_name', 'whatsapp_number')}),
        ('Role & Access', {'fields': ('role', 'installer', 'customer', 'site')}),
        ('Permissions',  {'fields': ('is_active', 'is_staff', 'is_superuser')}),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'first_name', 'last_name', 'whatsapp_number', 'role', 'installer', 'customer', 'site', 'password1', 'password2'),
        }),
    )