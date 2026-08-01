# apps/users/serializers.py
# Serializers control what data goes in and out of our API
# Think of them as the shape of the data the frontend receives

from rest_framework import serializers
from .models import User


class UserSerializer(serializers.ModelSerializer):
    """
    Returns safe user data to the frontend.
    Never expose password or internal fields.
    """
    full_name      = serializers.CharField(read_only=True)
    installer_name = serializers.SerializerMethodField()
    installers     = serializers.SerializerMethodField()
    customer_id    = serializers.SerializerMethodField()
    customer_name  = serializers.SerializerMethodField()
    site_id     = serializers.SerializerMethodField()
    site_name   = serializers.SerializerMethodField()

    class Meta:
        model  = User
        fields = (
            'id',
            'email',
            'first_name',
            'last_name',
            'full_name',
            'role',
            'installer',
            'installer_name',
            'installers',
            'customer_id',
            'customer_name',
            'site_id',
            'site_name',
            'is_active',
        )
        read_only_fields = fields   # this endpoint is read only, no editing here

    def get_installer_name(self, obj):
        # Only meaningful for INSTALLER-role users (their own company).
        # CUSTOMER users never have this set — see `installers` instead.
        if obj.installer:
            return obj.installer.name
        return None

    def get_installers(self, obj):
        # For CUSTOMER users: the distinct installer(s) managing their sites.
        # A customer's sites can each be run by a different installer, so
        # this is always a list, never a single value.
        if obj.role != User.Role.CUSTOMER or not obj.customer:
            return []

        installer_ids_seen = set()
        result = []
        sites = obj.customer.sites.filter(
            is_active=True, installer__isnull=False
        ).select_related('installer')

        for site in sites:
            inst = site.installer
            if inst.id not in installer_ids_seen:
                installer_ids_seen.add(inst.id)
                result.append({'id': inst.id, 'name': inst.name})

        return result

    def get_customer_id(self, obj):
        if obj.customer:
            return obj.customer.id
        if obj.role == User.Role.SITE_USER and obj.site:
            return obj.site.customer_id
        return None

    def get_customer_name(self, obj):
        if obj.customer:
            return obj.customer.name
        if obj.role == User.Role.SITE_USER and obj.site:
            return obj.site.customer.name
        return None

    def get_site_id(self, obj):
        if obj.role == User.Role.SITE_USER and obj.site:
            return obj.site.id
        return None

    def get_site_name(self, obj):
        if obj.role == User.Role.SITE_USER and obj.site:
            return obj.site.name
        return None


class LoginSerializer(serializers.Serializer):
    """
    Validates login input - just email and password.
    """
    email    = serializers.EmailField()
    password = serializers.CharField(write_only=True)