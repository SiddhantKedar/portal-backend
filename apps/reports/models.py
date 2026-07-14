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

    performance_ratio_pct = models.DecimalField(max_digits=7, decimal_places=2, null=True)
    cuf_pct = models.DecimalField(max_digits=6, decimal_places=2, null=True)
    poa_irradiation_kwh_m2 = models.DecimalField(max_digits=8, decimal_places=4, null=True)

    co2_avoided_kg = models.DecimalField(max_digits=10, decimal_places=2, null=True)

    peak_power_kw = models.DecimalField(max_digits=8, decimal_places=2, null=True)
    peak_power_time = models.DateTimeField(null=True)

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