# apps/users/admin.py

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm
from django.core.exceptions import ValidationError

from .models import User


class SitesValidationMixin:
    """
    Validates the `sites` M2M using the sites SELECTED in the form — the model's
    clean() can't, because M2M is only attached after the user row is saved.
    Shared by the add and change forms.
    """
    def clean(self):
        cleaned = super().clean()
        role  = cleaned.get('role')
        sites = cleaned.get('sites')

        if role == User.Role.SITE_USER:
            if not sites:
                raise ValidationError('Site users must have at least one site assigned.')
            if len({s.customer_id for s in sites}) > 1:
                raise ValidationError('All sites of a site user must belong to the same customer.')
        elif sites:
            raise ValidationError('Only site users can have sites assigned.')
        return cleaned


class UserAdminChangeForm(SitesValidationMixin, UserChangeForm):
    pass


class UserAdminCreationForm(SitesValidationMixin, UserCreationForm):
    pass


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    form     = UserAdminChangeForm
    add_form = UserAdminCreationForm

    list_display  = ('email', 'full_name', 'role', 'installer', 'customer', 'sites_list',
                     'whatsapp_number', 'is_active')
    list_filter   = ('role', 'is_active', 'is_staff', 'installer', 'customer')
    search_fields = ('email', 'first_name', 'last_name', 'whatsapp_number',
                     'installer__name', 'customer__name', 'sites__name')
    ordering      = ('email',)

    # FKs join in one query; the sites M2M is prefetched in get_queryset.
    list_select_related = ('installer', 'customer')
    # Searchable pickers instead of giant dropdowns (works for M2M too).
    autocomplete_fields = ('installer', 'customer', 'sites')
    readonly_fields     = ('date_joined',)

    fieldsets = (
        (None,            {'fields': ('email', 'password')}),
        ('Personal',      {'fields': ('first_name', 'last_name', 'whatsapp_number')}),
        ('Role & Access', {'fields': ('role', 'installer', 'customer', 'sites')}),
        ('Permissions',   {'fields': ('is_active', 'is_staff', 'is_superuser')}),
        ('Meta',          {'fields': ('date_joined',)}),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'first_name', 'last_name', 'whatsapp_number', 'role',
                       'installer', 'customer', 'sites', 'password1', 'password2'),
        }),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('sites')

    @admin.display(description='Sites')
    def sites_list(self, obj):
        return ', '.join(s.name for s in obj.sites.all()) or '—'