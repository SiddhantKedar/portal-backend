from django.db import models


class DailySiteSnapshot(models.Model):
    site = models.ForeignKey(
        'sites.Site', on_delete=models.CASCADE, related_name='daily_snapshots'
    )
    date = models.DateField()

    energy_today_kwh = models.DecimalField(max_digits=10, decimal_places=3, null=True)
    energy_today_inverter_sum_kwh = models.DecimalField(
        max_digits=10, decimal_places=3, null=True
    )

    energy_active_export_open_kwh = models.DecimalField(
    max_digits=16, decimal_places=2, null=True, blank=True,
    help_text="Day-start raw meter export counter (odometer at 00:00). "
                "Cumulative lifetime, NOT offset-corrected. NULL when the meter "
                "reported nothing. Pairs with energy_active_export_kwh (day-end); "
                "close / open == energy_today_kwh on a clean day. Independent "
                "second source for validating the daily figure."
    )
    energy_active_export_kwh = models.DecimalField(
        max_digits=16, decimal_places=2, null=True, blank=True,
        help_text="End-of-day raw meter export counter (odometer). Cumulative "
                "lifetime, NOT offset-corrected. NULL when the meter reported "
                "nothing that day. Basis for month-to-date via Postgres last and first."
    )

    performance_ratio_pct = models.DecimalField(max_digits=7, decimal_places=2, null=True)
    cuf_pct = models.DecimalField(max_digits=6, decimal_places=2, null=True)
    poa_irradiation_kwh_m2 = models.DecimalField(max_digits=8, decimal_places=4, null=True)

    co2_avoided_kg = models.DecimalField(max_digits=10, decimal_places=2, null=True)

    peak_power_kw = models.DecimalField(max_digits=8, decimal_places=2, null=True)
    peak_power_time = models.DateTimeField(null=True)

    generation_start_time = models.DateTimeField(null=True)
    generation_end_time = models.DateTimeField(null=True)

    meter_status = models.CharField(
        max_length=10,
        choices=[('ok', 'OK'), ('no_data', 'No Data')],
        default='ok',
    )
    inverters_online_count = models.PositiveIntegerField(null=True)
    inverters_total_count = models.PositiveIntegerField(null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('site', 'date')
        ordering = ['-date']

    def __str__(self):
        return f'{self.site.name} — {self.date}'