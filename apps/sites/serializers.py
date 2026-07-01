# apps/sites/serializers.py
# Controls what data shape is sent to the frontend for
# customers, sites and devices.

from rest_framework import serializers
from .models import Customer, Site, Device


class DeviceSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Device
        fields = (
            'id',
            'name',
            'device_type',
            'influx_device_id',
            'is_active',
        )


class SiteSerializer(serializers.ModelSerializer):
    # Nest devices inside each site so one call returns
    # the site and all its devices together
    devices      = DeviceSerializer(many=True, read_only=True)
    customer_name = serializers.CharField(
        source='customer.name',
        read_only=True
    )
    installer_name = serializers.CharField(      
        source='installer.name',
        read_only=True
    )

    class Meta:
        model  = Site
        fields = (
            'id',
            'name',
            'site_type',
            'parent_site',
            'location',
            'latitude',
            'longitude',
            'influx_site_id',
            'customer_name',
            'installer_name',
            'devices',
            'is_active',
        )


class CustomerSerializer(serializers.ModelSerializer):
    # Nest sites inside each customer
    sites          = SiteSerializer(many=True, read_only=True)

    class Meta:
        model  = Customer
        fields = (
            'id',
            'name',
            'email',
            'sites',
            'is_active',
        )


class CustomerListSerializer(serializers.ModelSerializer):
    """
    Lightweight serializer for listing customers.
    Does not nest sites — used for dropdowns where we
    only need id and name, not full site details.
    """
    class Meta:
        model  = Customer
        fields = (
            'id',
            'name',
            'is_active',
        )


class SiteListSerializer(serializers.ModelSerializer):
    """
    Lightweight serializer for listing sites.
    Used for dropdowns — no nested devices.
    """
    customer_name = serializers.CharField(
        source='customer.name',
        read_only=True
    )

    installer_name = serializers.CharField(  
        source='installer.name',
        read_only=True
    )

    class Meta:
        model  = Site
        fields = (
            'id',
            'name',
            'site_type',
            'parent_site',
            'location',
            'influx_site_id',
            'customer_name',
            'installer_name',
            'is_active',
        )