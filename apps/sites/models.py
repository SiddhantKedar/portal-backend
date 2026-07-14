# apps/sites/models.py
# Handles solar sites (physical locations) and devices (inverters, meters etc)
# Each site belongs to a customer, each customer belongs to an installer

from django.db import models


class Customer(models.Model):
    """
    The end customer - business entity that owns solar installations.
    No longer linked to a single installer - a customer's sites
    can be installed and managed by different installers.
    """
    name        = models.CharField(max_length=255)
    email       = models.EmailField(unique=True)
    phone       = models.CharField(max_length=20, blank=True)
    address     = models.TextField(blank=True)
    influx_bucket    = models.CharField(max_length=100, unique=True, null=True, blank=True)
    influx_client_id = models.CharField(max_length=100, null=True, blank=True)
    is_active   = models.BooleanField(default=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'customers'

    def __str__(self):
        return self.name


class Site(models.Model):
    """
    A physical location where solar is installed.
    One customer can have multiple sites.
    eg: Main Factory, Substation, Warehouse Rooftop
    """

    class SiteType(models.TextChoices):
        GENERATION  = 'GENERATION', 'Generation Plant'
        SUBSTATION  = 'SUBSTATION', 'Substation / GSS'
        OTHER       = 'OTHER',      'Other'
    customer    = models.ForeignKey(
        Customer,
        on_delete=models.PROTECT,
        related_name='sites'
    )
    installer   = models.ForeignKey(          
        'tenants.Installer',
        on_delete=models.PROTECT,
        related_name='sites'
    )

    name        = models.CharField(max_length=255) 
    site_type      = models.CharField(       
        max_length=20,
        choices=SiteType.choices,
        default=SiteType.GENERATION 
    )

    parent_site = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='related_sites'
    )
    location    = models.CharField(max_length=255, blank=True)
    latitude    = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude   = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    # This must match exactly the 'site' tag value in InfluxDB
    influx_site_id = models.CharField(max_length=100)

    dc_capacity_kw = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    ac_capacity_kw = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )

    is_active   = models.BooleanField(default=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'sites'
        constraints = [
            models.UniqueConstraint(
                fields=['customer', 'influx_site_id'],
                name='unique_site_id_per_customer'
            ),
            models.UniqueConstraint(
            fields=['parent_site'],
            condition=models.Q(parent_site__isnull=False),
            name='unique_substation_per_parent_site'
        ),
        ]

    def __str__(self):
        return f'{self.name} - {self.customer.name}'


class Device(models.Model):
    """
    A physical device at a site - inverter, meter, dido, weatherstation etc.
    The influx_device_id must match exactly the 'device' tag in InfluxDB.
    This is the critical link between Postgres and InfluxDB data.
    """

    class DeviceType(models.TextChoices):
        INVERTER        = 'INVERTER',       'Inverter'
        METER           = 'METER',          'Meter'
        DIDO            = 'DIDO',           'DIDO'
        WEATHER_STATION = 'WEATHER_STATION','Weather Station'
        OTHER           = 'OTHER',          'Other'

    site            = models.ForeignKey(
        Site,
        on_delete=models.PROTECT,
        related_name='devices'
    )
    name            = models.CharField(max_length=255)  # human readable name
    device_type     = models.CharField(max_length=20, choices=DeviceType.choices)

    # Must match exactly the 'device' tag value in InfluxDB
    influx_device_id = models.CharField(max_length=100)

    is_active       = models.BooleanField(default=True)
    created_at      = models.DateTimeField(auto_now_add=True)
    energy_offset_kwh = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text='Manual correction added to raw meter lifetime energy reading '
    )
    class Meta:
        db_table = 'devices'
        constraints = [
            models.UniqueConstraint(
                fields=['site', 'influx_device_id'],
                name='unique_device_id_per_site'
            )
        ]

    def __str__(self):
        return f'{self.name} ({self.device_type}) - {self.site.name}'