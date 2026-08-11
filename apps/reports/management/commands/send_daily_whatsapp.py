# apps/reports/management/commands/send_daily_whatsapp.py
#
# v1 — daily generation WhatsApp for SITE_USERs.
# Sends TODAY's live generation (midnight IST -> now) to each SITE_USER who has
# a whatsapp_number, using their single assigned site. Meant to run in the
# evening (~19:30 IST), before the nightly snapshot exists — so it reads live,
# NOT from DailySiteSnapshot.
#
#   python manage.py send_daily_whatsapp                 # all SITE_USERs w/ a number
#   python manage.py send_daily_whatsapp --site=14       # only users on site 14
#   python manage.py send_daily_whatsapp --dry-run       # resolve + log, DON'T send
#
# v1 scope (deliberately minimal):
#   - SITE_USER role only. CUSTOMER/INSTALLER/ADMIN come later.
#   - Sends: name, site, date, energy_today (live), CUF (live). PR is sent as
#     "-" for now (live PR gating deferred — see handoff).
#   - Reuses the snapshot command's proven Postgres resolution + the same
#     _query_meter_energy_for_day live query.
#
# One user failing never stops the rest. Non-zero exit if any send failed.

import sys
from datetime import datetime, timezone as dt_timezone

from django.core.management.base import BaseCommand, CommandError

from apps.users.models import User
from apps.sites.models import Site, Device
from apps.influx.client import get_influx_client
from apps.influx.queries import (
    _resolve_ist_date_range,
    MIN_POA_KWH_M2_FOR_PR,
    # TEMP (v1 reuse): borrowed from the snapshot + live paths.
    _query_meter_energy_for_day,
    _query_meter_live,
    _query_poa_irradiation_for_day,
)

# AiSensy campaign name for the approved daily-report template.
# NOTE: must match the campaign name in the AiSensy dashboard exactly.
CAMPAIGN_NAME = 'daily_gen_v2'  # TEMP: swap to the real 6-param greeting campaign once approved


def _fmt_num(value, decimals=1, zero_ok=False):
    """None -> '-'. A 0 -> '-' too, UNLESS zero_ok (then '0.0').
    CUF/PR use the strict rule (a bare 0% reads as broken on WhatsApp).
    Energy passes zero_ok=True: a real 0 kWh means the plant was offline
    or genuinely produced nothing — both worth showing as 0.0, not '-'.
    Only a missing meter (-> None) shows '-' for energy."""
    if value is None:
        return '-'
    if value == 0 and not zero_ok:
        return '-'
    return f'{value:.{decimals}f}'


class Command(BaseCommand):
    help = "Sends today's live generation summary to SITE_USERs via WhatsApp (v1)."

    def add_arguments(self, parser):
        parser.add_argument('--site', type=int, default=None,
                            help='Postgres Site pk. Omit to run all SITE_USERs with a number.')
        parser.add_argument('--dry-run', action='store_true',
                            help='Resolve recipients + data and log, but do NOT send.')

    def handle(self, *args, **options):
        site_pk = options.get('site')
        dry_run = options.get('dry_run')

        # Import here so a missing key / requests issue surfaces as a clean
        # command error rather than an import-time crash.
        from core.whatsapp import send_template

        # --- Recipients: SITE_USERs with a real number and an assigned site.
        #     whatsapp_number is stored bare (no '+'); '' / None both mean opt-out.
        recipients = User.objects.filter(
            role='SITE_USER',
            site__isnull=False,
            is_active=True,
        ).exclude(
            whatsapp_number__isnull=True
        ).exclude(
            whatsapp_number=''
        ).select_related('site', 'site__customer')

        if site_pk:
            recipients = recipients.filter(site_id=site_pk)

        recipients = list(recipients)
        if not recipients:
            self.stdout.write('No SITE_USER recipients with a WhatsApp number found.')
            return

        # Live window: today, IST midnight -> now, as the RFC3339 UTC strings
        # the _for_day queries expect. date_str=None => today, end capped at now.
        start, end = _resolve_ist_date_range(None)

        # Reporting date label in IST, e.g. "11 Aug 2026".
        from datetime import timedelta
        ist_tz = dt_timezone(timedelta(hours=5, minutes=30))
        date_label = datetime.now(ist_tz).strftime('%d %b %Y')

        self.stdout.write(
            f'{"[DRY RUN] " if dry_run else ""}'
            f'Sending to {len(recipients)} SITE_USER(s) for {date_label}...'
        )

        sent = 0
        failed = 0
        skipped = 0

        for user in recipients:
            site = user.site

            # Only GENERATION sites produce a report. A SITE_USER should always
            # point at a GENERATION site, but guard anyway.
            if site.site_type != Site.SiteType.GENERATION:
                skipped += 1
                self.stdout.write(self.style.WARNING(
                    f'[{user.pk}] {user.email} — site "{site.name}" is not GENERATION; skipped.'
                ))
                continue

            try:
                energy_kwh, cuf_pct, pr_pct = self._live_metrics(site, start, end)
            except Exception as e:
                failed += 1
                self.stderr.write(self.style.ERROR(
                    f'[{user.pk}] {user.email} — {site.name}: data query FAILED — {e}'
                ))
                continue

            name = f'{user.first_name} {user.last_name}'.strip() or 'Customer'
            params = [
                name,                                   # {{1}}
                site.name,                              # {{2}}
                date_label,                             # {{3}}
                _fmt_num(energy_kwh, 1, zero_ok=True),  # {{4}} energy kWh — real 0 shows 0.0
                _fmt_num(cuf_pct, 1),                   # {{5}} CUF %  (0/None -> '-')
                _fmt_num(pr_pct, 1),                    # {{6}} PR %   (0/None -> '-', live-gated)
            ]

            if dry_run:
                self.stdout.write(
                    f'[{user.pk}] {user.email} -> {user.whatsapp_number} | {params}'
                )
                sent += 1
                continue

            ok, detail = send_template(user.whatsapp_number, CAMPAIGN_NAME, params)
            if ok:
                sent += 1
                self.stdout.write(self.style.SUCCESS(
                    f'[{user.pk}] {user.email} -> {user.whatsapp_number}: sent '
                    f'(energy={params[3]}, cuf={params[4]})'
                ))
            else:
                failed += 1
                self.stderr.write(self.style.ERROR(
                    f'[{user.pk}] {user.email} -> {user.whatsapp_number}: FAILED — {detail}'
                ))

        verb = 'would send' if dry_run else 'sent'
        summary = f'Done. {sent} {verb}, {skipped} skipped, {failed} failed.'
        if failed:
            self.stderr.write(self.style.ERROR(summary))
            sys.exit(1)
        self.stdout.write(self.style.SUCCESS(summary))

    def _live_metrics(self, site, start, end):
        """
        Live energy-today (midnight IST -> now), CUF, and PR for one site.
        Reuses the snapshot's meter-energy + POA queries and the live meter
        query, with PR gated to match get_plant_overview exactly.

        Returns (energy_kwh | None, cuf_pct | None, pr_pct | None).
        - energy_kwh: last-first of export counter; persists through a brief blip.
        - cuf_pct: pure function of energy; None if energy None or no ac_capacity.
        - pr_pct: gated — None unless meter live now AND dc_capacity set AND
          POA >= MIN_POA_KWH_M2_FOR_PR AND weather reported. Matches portal gate.
        """
        bucket = site.customer.influx_bucket
        site_id = site.influx_site_id

        meter = Device.objects.filter(
            site=site, device_type='METER', is_active=True, influx_device_id='meter1'
        ).first()
        if not meter:
            return None, None, None

        weather_device = Device.objects.filter(
            site=site, device_type='WEATHER_STATION', is_active=True
        ).first()

        client = get_influx_client()
        query_api = client.query_api()
        try:
            # TEMP (v1 reuse): energy-so-far, midnight->now.
            energy_kwh, _meter_status = _query_meter_energy_for_day(
                query_api, bucket, site_id, meter.influx_device_id, start, end
            )

            # Meter live NOW? (fresh subset non-empty) — PR gate condition 1.
            meter_data, _meter_time, _meter_last = _query_meter_live(
                query_api, bucket, site_id, meter.influx_device_id
            )
            meter_is_live = bool(meter_data)

            # POA since midnight (Wh/m² -> kWh/m²) — PR gate conditions 3 & 4.
            poa_kwh_m2 = None
            if weather_device:
                poa_wh_m2 = _query_poa_irradiation_for_day(
                    query_api, bucket, site_id, weather_device.influx_device_id, start, end
                )
                poa_kwh_m2 = round(poa_wh_m2 / 1000.0, 4)
        finally:
            client.close()

        # CUF — pure function of energy, ungated.
        cuf_pct = None
        if energy_kwh is not None and site.ac_capacity_kw:
            cuf_pct = round(
                (energy_kwh / (float(site.ac_capacity_kw) * 24)) * 100, 2
            )

        # PR — same four-part gate as get_plant_overview. None (=> "-") if any fails.
        pr_pct = None
        if (
            meter_is_live
            and site.dc_capacity_kw
            and poa_kwh_m2 is not None
            and poa_kwh_m2 >= MIN_POA_KWH_M2_FOR_PR
            and energy_kwh is not None
        ):
            pr_pct = round(
                (energy_kwh / (float(site.dc_capacity_kw) * poa_kwh_m2)) * 100, 2
            )

        return energy_kwh, cuf_pct, pr_pct