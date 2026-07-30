# apps/reports/management/commands/snapshot_daily_metrics.py
#
# Nightly rollup: one DailySiteSnapshot row per GENERATION site per day.
# Run via system cron, ~00:15 IST, targeting "yesterday" by default.
#
#   python manage.py snapshot_daily_metrics
#   python manage.py snapshot_daily_metrics --date=2026-07-10
#   python manage.py snapshot_daily_metrics --site=14 --date=2026-07-10
#   python manage.py snapshot_daily_metrics --site=14 --start=2026-07-01 --end=2026-07-10
#
# Idempotent — safe to re-run any date any number of times (update_or_create
# on the site+date unique constraint). One site failing never stops the rest.

from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.sites.models import Site, Device
from apps.reports.models import DailySiteSnapshot
from apps.influx.client import get_influx_client
from apps.influx.queries import (
    INFLUX_ORG,
    CO2_AVOIDED_FACTOR_KG_PER_KWH,
    MIN_POA_KWH_M2_FOR_PR,
    _resolve_ist_date_range,
    _query_meter_energy_for_day,
    _query_poa_irradiation_for_day,
    _query_meter_peak_power_for_day,
    _query_inverter_daily_sum_for_day,
)

def _dec(value):
    """
    float -> Decimal via str, so we don't hand binary-float artifacts to a
    DecimalField column we intend to do commercial reporting off. (Issue 4.)
    """
    return None if value is None else Decimal(str(value))

class Command(BaseCommand):
    help = 'Computes and stores DailySiteSnapshot rows for GENERATION sites.'

    def add_arguments(self, parser):
        parser.add_argument('--site', type=int, default=None,
                             help='Postgres Site pk. Omit to run all active GENERATION sites.')
        parser.add_argument('--date', type=str, default=None,
                         help='YYYY-MM-DD. Defaults to today (IST) — job is scheduled '
                              '~11:50pm IST so "today" already covers the full '
                              'generation day. Ignored if --start/--end given.')
        parser.add_argument('--start', type=str, default=None,
                             help='YYYY-MM-DD, used with --end for a date range backfill.')
        parser.add_argument('--end', type=str, default=None,
                             help='YYYY-MM-DD, used with --start for a date range backfill.')

    def handle(self, *args, **options):
        site_pk   = options.get('site')
        date_str  = options.get('date')
        start_str = options.get('start')
        end_str   = options.get('end')

        # --- Resolve dates. Every path below yields real 'YYYY-MM-DD' strings,
        #     never None — no downstream defaulting, one source of truth.
        if bool(start_str) != bool(end_str):
            raise CommandError('--start and --end must be given together.')

        if start_str:
            if date_str:
                raise CommandError('--date cannot be combined with --start/--end.')
            dates = self._date_range(start_str, end_str)
        else:
            dates = [self._validate_date(date_str) if date_str else self._ist_today_str()]

        sites_qs = Site.objects.filter(
            site_type=Site.SiteType.GENERATION, is_active=True
        ).select_related('customer')
        if site_pk:
            sites_qs = sites_qs.filter(pk=site_pk)

        sites = list(sites_qs)
        if not sites:
            raise CommandError('No matching active GENERATION sites found.')

        self.stdout.write(f'Processing {len(sites)} site(s) across {len(dates)} date(s)...')

        success_count = 0
        fail_count = 0

        for d in dates:
            for site in sites:
                try:
                    self._snapshot_one(site, d)
                    success_count += 1
                except Exception as e:
                    fail_count += 1
                    self.stderr.write(self.style.ERROR(
                        f'[{site.pk}] {site.name} — {d}: FAILED — {e}'
                    ))

        self.stdout.write(self.style.SUCCESS(
            f'Done. {success_count} succeeded, {fail_count} failed.'
        ))

    def _validate_date(self, date_str):
        try:
            datetime.strptime(date_str, '%Y-%m-%d')
        except ValueError:
            raise CommandError(f'Invalid date "{date_str}" — expected YYYY-MM-DD.')
        return date_str

    def _date_range(self, start_str, end_str):
        self._validate_date(start_str)
        self._validate_date(end_str)
        start = datetime.strptime(start_str, '%Y-%m-%d').date()
        end   = datetime.strptime(end_str, '%Y-%m-%d').date()
        if end < start:
            raise CommandError(f'--end ({end_str}) is before --start ({start_str}).')
        days = (end - start).days
        return [(start + timedelta(days=i)).strftime('%Y-%m-%d') for i in range(days + 1)]

    def _ist_today_str(self):
        ist = dt_timezone(timedelta(hours=5, minutes=30))
        return datetime.now(ist).date().strftime('%Y-%m-%d')

    def _snapshot_one(self, site, date_str):
        bucket  = site.customer.influx_bucket
        site_id = site.influx_site_id

        meter = Device.objects.filter(
            site=site, device_type='METER', is_active=True, influx_device_id='meter1'
        ).first()
        if not meter:
            raise Exception('No main meter configured for this site')

        inverters = list(Device.objects.filter(
            site=site, device_type='INVERTER', is_active=True
        ))
        inverter_ids = [d.influx_device_id for d in inverters]

        weather_device = Device.objects.filter(
            site=site, device_type='WEATHER_STATION', is_active=True
        ).first()

        start, end = _resolve_ist_date_range(date_str)

        client = get_influx_client()
        query_api = client.query_api()

        try:
            energy_kwh, meter_status = _query_meter_energy_for_day(
                query_api, bucket, site_id, meter.influx_device_id, start, end
            )

            inv_sum_kwh, inv_reporting_count = (None, None)
            if inverter_ids:
                inv_sum_kwh, inv_reporting_count = _query_inverter_daily_sum_for_day(
                    query_api, bucket, site_id, inverter_ids, start, end
                )

            poa_kwh_m2 = None
            if weather_device:
                poa_wh_m2 = _query_poa_irradiation_for_day(
                    query_api, bucket, site_id, weather_device.influx_device_id, start, end
                )
                poa_kwh_m2 = round(poa_wh_m2 / 1000.0, 4)

            peak_power_kw, peak_power_time = _query_meter_peak_power_for_day(
                query_api, bucket, site_id, meter.influx_device_id, start, end
            )
        finally:
            client.close()

        # --- Derived metrics.
        # Every one of these is a function of meter energy. If energy is not
        # trustworthy (no_data / anomaly), they are all NULL. Storing 0.0 here
        # would make a dead meter indistinguishable from a real zero day.
        performance_ratio_pct = None
        cuf_pct = None
        co2_avoided_kg = None

        if energy_kwh is not None:
            # PR needs a *meaningful* POA, not just a truthy one. A pyranometer
            # that reported for ten minutes at dawn gives POA ~= 0.001, and
            # energy / (capacity * 0.001) overflows the column and kills the run.
            if (
                site.dc_capacity_kw
                and poa_kwh_m2
                and poa_kwh_m2 >= MIN_POA_KWH_M2_FOR_PR
            ):
                performance_ratio_pct = round(
                    (energy_kwh / (float(site.dc_capacity_kw) * poa_kwh_m2)) * 100, 2
                )

            if site.ac_capacity_kw:
                cuf_pct = round(
                    (energy_kwh / (float(site.ac_capacity_kw) * 24)) * 100, 2
                )

            co2_avoided_kg = round(energy_kwh * CO2_AVOIDED_FACTOR_KG_PER_KWH, 2)

        snapshot, created = DailySiteSnapshot.objects.update_or_create(
            site=site,
            date=date_str,
            defaults={
                'energy_today_kwh': _dec(energy_kwh),
                'energy_today_inverter_sum_kwh': _dec(inv_sum_kwh),
                'performance_ratio_pct': _dec(performance_ratio_pct),
                'cuf_pct': _dec(cuf_pct),
                'poa_irradiation_kwh_m2': _dec(poa_kwh_m2),
                'co2_avoided_kg': _dec(co2_avoided_kg),
                'peak_power_kw': _dec(peak_power_kw),
                'peak_power_time': peak_power_time,
                'meter_status': meter_status,
                'inverters_online_count': inv_reporting_count,
                'inverters_total_count': len(inverter_ids),
            },
        )

        verb = 'Created' if created else 'Updated'
        self.stdout.write(
            f'[{site.pk}] {site.name} — {date_str}: {verb} '
            f'(energy={energy_kwh} kWh, meter_status={meter_status})'
        )