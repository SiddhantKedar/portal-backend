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
    influx_bucket    = models.CharField(max_length=100, null=True, blank=True)
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

    reference_meter = models.ForeignKey(
        'Device', null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='referenced_by_sites',
        limit_choices_to={'device_type': 'METER'},
        help_text=(
            "Meter whose history drives this plant's power/energy figures "
            "(active power, energy today, etotal). Defaults to the site's own "
            "active 'meter1' when unset. May live on a parent/substation site "
            "for a plant with a damaged local meter. If the chosen meter is "
            "deactivated, this plant reports no reference meter until a new one "
            "is set."
        )
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

    daily_generation_target_kwh = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text='Target daily energy generation for this site, used for performance zone comparisons'
    )

    target_cuf_pct = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
        help_text='Target CUF (%) for this site, used for performance zone comparisons'
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

    

    def get_reference_meter(self):
        if self.reference_meter_id:
            m = self.reference_meter          # FK; .site is one extra query when accessed
            return m if m.is_active else None
        return Device.objects.select_related('site').filter(
            site=self, device_type=Device.DeviceType.METER,
            is_active=True, influx_device_id='meter1'
        ).first()

    def get_grid_meter(self):
        return Device.objects.select_related('site').filter(
            site=self, device_type=Device.DeviceType.METER,
            is_active=True, influx_device_id='meter1'
        ).first()

    @staticmethod
    def reference_meters_for(sites):
        """
        {site.pk: Device|None} for many sites in 2 queries, N-independent.
        Bulk mirror of Site.get_reference_meter — MUST stay in lockstep,
        including: an explicit but INACTIVE reference_meter yields None with no
        fallback to meter1. Result is keyed on the REFERENCING site's pk, so a
        meter borrowed from a substation is filed under the plant, not the
        substation.
        """
        result = {}
        ref_ids = {}        # site.pk -> chosen device pk (FK set)
        fallback_pks = []   # sites with no FK -> legacy meter1

        for s in sites:
            if s.reference_meter_id:
                ref_ids[s.pk] = s.reference_meter_id
            else:
                fallback_pks.append(s.pk)

        if ref_ids:
            # in_bulk fetches by pk regardless of is_active — re-check in Python.
            devs = Device.objects.in_bulk(set(ref_ids.values()))
            for pk, dev_id in ref_ids.items():
                m = devs.get(dev_id)
                result[pk] = m if (m and m.is_active) else None

        if fallback_pks:
            legacy = Device.objects.filter(
                site_id__in=fallback_pks, device_type=Device.DeviceType.METER,
                is_active=True, influx_device_id='meter1'
            )
            legacy_by_site = {m.site_id: m for m in legacy}
            for pk in fallback_pks:
                result[pk] = legacy_by_site.get(pk)

        return result


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
        TRANSFORMER     = 'TRANSFORMER',     'Transformer'
        ANNUNCIATOR     = 'ANNUNCIATOR',     'Annunciator'
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

    @property
    def influx_location(self):
        """
        (site_tag, device_tag) for this device's own InfluxDB series.

        The site tag is the DEVICE's own site, not whichever plant references
        it — critical because influx_device_id is NOT unique across sites
        (every site's main meter is 'meter1'). A meter is located in Influx by
        site tag + device tag together; separating them reads a different site's
        same-named meter. Always pass this pair, never the device id alone.
        """
        return self.site.influx_site_id, self.influx_device_id

    def __str__(self):
        return f'{self.name} ({self.device_type}) - {self.site.name}'