# apps/influx/installer_views.py
# Installer portfolio overview.
# GET /api/v1/influx/installer/overview/
# Scoped automatically to request.user.installer — no site param needed.
# Poll every 60 seconds.

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from core.permissions import IsInstallerUser
from apps.sites.models import Site, Device

from .queries import get_installer_overview


class InstallerOverviewView(APIView):
    permission_classes = [IsInstallerUser]

    def get(self, request):
        installer = request.user.installer

        # All active GENERATION sites for this installer, ordered for consistent grouping
        sites = list(
            Site.objects.filter(
                installer=installer,
                site_type=Site.SiteType.GENERATION,
                is_active=True
            ).select_related('customer').order_by('customer__name', 'name')
        )

        if not sites:
            return Response({
                'fleet_summary': {
                    'total_active_power_kw':  0.0,
                    'total_energy_today_kwh': 0.0,
                    'sites_online':           0,
                    'sites_total':            0,
                    'inverters_online':       0,
                    'inverters_total':        0,
                },
                'customers': [],
            })

        site_pks = [s.pk for s in sites]

        # 2 Postgres queries — all meters and inverters for these sites at once
        meters = Device.objects.filter(
            site_id__in=site_pks, device_type='METER', is_active=True
        ).select_related('site').order_by('influx_device_id')

        inverters = Device.objects.filter(
            site_id__in=site_pks, device_type='INVERTER', is_active=True
        ).select_related('site')

        # Build lookup maps (influx tags as keys — needed for Flux result matching)
        site_by_pk        = {s.pk: s for s in sites}
        site_meter_influx = {}   # influx_site_id -> meter influx_device_id
        for m in meters:
            s = site_by_pk[m.site_id]
            iid = s.influx_site_id
            if iid not in site_meter_influx:  # first one wins, not last
                site_meter_influx[iid] = m.influx_device_id

        site_inverters_influx = {}   # influx_site_id -> [inv influx_device_ids]
        for inv in inverters:
            s   = site_by_pk[inv.site_id]
            iid = s.influx_site_id
            if iid not in site_inverters_influx:
                site_inverters_influx[iid] = []
            site_inverters_influx[iid].append(inv.influx_device_id)

        # Group by bucket — one Flux query pair per customer
        bucket_groups = {}
        for site in sites:
            bucket = site.customer.influx_bucket
            if bucket not in bucket_groups:
                bucket_groups[bucket] = {'meter_map': {}, 'inverters_map': {}}
            iid = site.influx_site_id
            if iid in site_meter_influx:
                bucket_groups[bucket]['meter_map'][iid]     = site_meter_influx[iid]
            bucket_groups[bucket]['inverters_map'][iid] = site_inverters_influx.get(iid, [])

        try:
            influx_results = get_installer_overview(bucket_groups)
        except Exception as e:
            return Response({'detail': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # Group sites by customer for response shape
        customer_sites = {}
        customer_obj   = {}
        for site in sites:
            cid = site.customer_id
            if cid not in customer_sites:
                customer_sites[cid] = []
                customer_obj[cid]   = site.customer
            customer_sites[cid].append(site)

        # Assemble response + compute fleet totals in one pass
        total_active_power    = 0.0
        total_energy_today    = 0.0
        sites_online          = 0
        inverters_online_total = 0
        inverters_total_total  = 0

        customers_list = []
        for cid, cust_sites in customer_sites.items():
            site_cards = []
            for site in cust_sites:
                iid = site.influx_site_id
                r   = influx_results.get(iid, {})

                active_power = r.get('active_power_kw',  0.0)
                energy_today = r.get('energy_today_kwh', 0.0)
                meter_online = r.get('meter_online',     False)
                inv_online   = r.get('inverters_online', 0)
                inv_total    = r.get('inverters_total',  0)

                total_active_power     += active_power
                total_energy_today     += energy_today
                if meter_online:
                    sites_online       += 1
                inverters_online_total += inv_online
                inverters_total_total  += inv_total

                site_cards.append({
                    'site_id':          site.pk,
                    'site_name':        site.name,
                    'active_power_kw':  active_power,
                    'energy_today_kwh': energy_today,
                    'meter_online':     meter_online,
                    'inverters_online': inv_online,
                    'inverters_total':  inv_total,
                    'last_updated':     r.get('last_updated'),
                })

            customers_list.append({
                'customer_id':   customer_obj[cid].pk,
                'customer_name': customer_obj[cid].name,
                'sites':         site_cards,
            })

        return Response({
            'fleet_summary': {
                'total_active_power_kw':  round(total_active_power, 2),
                'total_energy_today_kwh': round(total_energy_today, 2),
                'sites_online':           sites_online,
                'sites_total':            len(sites),
                'inverters_online':       inverters_online_total,
                'inverters_total':        inverters_total_total,
            },
            'customers': customers_list,
        })