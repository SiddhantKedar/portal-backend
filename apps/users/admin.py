# apps/users/admin.py

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display  = ('email', 'full_name', 'role', 'installer', 'customer', 'site',
                     'whatsapp_number', 'is_active')
    list_filter   = ('role', 'is_active', 'is_staff', 'installer', 'customer')
    search_fields = ('email', 'first_name', 'last_name', 'whatsapp_number',
                     'installer__name', 'customer__name', 'site__name')
    ordering      = ('email',)

    # Changelist touches 3 FKs per row → one JOIN instead of N+1 queries.
    list_select_related = ('installer', 'customer', 'site')
    # Searchable pickers instead of giant dropdowns (matters as sites/customers grow).
    autocomplete_fields = ('installer', 'customer', 'site')
    readonly_fields     = ('date_joined',)

    fieldsets = (
        (None,            {'fields': ('email', 'password')}),
        ('Personal',      {'fields': ('first_name', 'last_name', 'whatsapp_number')}),
        ('Role & Access', {'fields': ('role', 'installer', 'customer', 'site')}),
        ('Permissions',   {'fields': ('is_active', 'is_staff', 'is_superuser')}),
        ('Meta',          {'fields': ('date_joined',)}),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'first_name', 'last_name', 'whatsapp_number', 'role',
                       'installer', 'customer', 'site', 'password1', 'password2'),
        }),
    )