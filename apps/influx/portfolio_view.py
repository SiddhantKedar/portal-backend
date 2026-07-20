# apps/influx/portfolio_views.py
# Role-neutral portfolio overview — the landing page for any user with >1 site.
# GET /api/v1/influx/portfolio/overview/
#
# Scoped via TenantFilterMixin, so the same endpoint serves all three roles:
#   ADMIN     → every customer
#   INSTALLER → customers reachable through their sites
#   CUSTOMER  → themselves, one customer block
# Poll every 60 seconds.

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from core.permissions import IsAnyRole
from core.mixins import TenantFilterMixin
from apps.sites.models import Site, Device

from .queries import get_portfolio_overview


class PortfolioOverviewView(TenantFilterMixin, APIView):
    permission_classes = [IsAnyRole]

    def _scope_name(self, user):
        """Heading text for the portfolio page. ADMIN has no single tenant."""
        if user.role == 'INSTALLER':
            return user.installer.name if user.installer_id else None
        if user.role == 'CUSTOMER':
            return user.customer.name if user.customer_id else None
        return 'All Customers'

    def _empty_response(self, user, include_energy=True):
        return Response({
            'scope_name': self._scope_name(user),
            'portfolio_summary': {
                'total_active_power_kw':  0.0,
                'total_energy_today_kwh': 0.0 if include_energy else None,
                'ac_capacity_kw':         0.0,
                'sites_online':           0,
                'sites_total':            0,
                'inverters_online':       0,
                'inverters_total':        0,
            },
            'customers': [],
        })

    def get(self, request):
        user = request.user

        include_energy = request.query_params.get('detail') != 'basic'

        # Tenant filtering is the ONLY access control here — never read
        # request.user.installer to scope the queryset, or ADMIN and CUSTOMER break.
        sites = list(
            self.get_filtered_sites()
            .filter(site_type=Site.SiteType.GENERATION, is_active=True)
            .select_related('customer', 'installer')
            .order_by('customer__name', 'name')
        )

        if not sites:
            return self._empty_response(user, include_energy)

        site_pks = [s.pk for s in sites]

        # 2 Postgres queries — all meters and inverters for these sites at once
        meters = Device.objects.filter(
            site_id__in=site_pks, device_type='METER', is_active=True, name='HT Meter'
        )
        inverters = Device.objects.filter(
            site_id__in=site_pks, device_type='INVERTER', is_active=True
        )

        # Lookup maps keyed on site PK — never influx_site_id (see D20).
        meter_by_pk = {m.site_id: m.influx_device_id for m in meters}
        inverters_by_pk = {}
        for inv in inverters:
            inverters_by_pk.setdefault(inv.site_id, []).append(inv.influx_device_id)

        # Group by bucket — one Flux query pair per bucket. influx_site_id is safe
        # as a key *inside* a bucket (unique per customer), which is why pk_map
        # rides along to translate back on the way out.
        bucket_groups = {}
        for site in sites:
            bucket = site.customer.influx_bucket
            group = bucket_groups.setdefault(
                bucket, {'pk_map': {}, 'meter_map': {}, 'inverters_map': {}}
            )
            iid = site.influx_site_id
            group['pk_map'][iid] = site.pk
            if site.pk in meter_by_pk:
                group['meter_map'][iid] = meter_by_pk[site.pk]
            group['inverters_map'][iid] = inverters_by_pk.get(site.pk, [])

        try:
            influx_results = get_portfolio_overview(bucket_groups, include_energy=include_energy)
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

        # Assemble response + compute portfolio totals in one pass
        total_active_power     = 0.0
        total_energy_today     = 0.0
        total_ac_capacity      = 0.0
        sites_online           = 0
        inverters_online_total = 0
        inverters_total_total  = 0

        customers_list = []
        for cid, cust_sites in customer_sites.items():
            site_cards = []
            for site in cust_sites:
                r = influx_results.get(site.pk, {})

                active_power = r.get('active_power_kw',  0.0)
                energy_today = r.get('energy_today_kwh') 
                meter_online = r.get('meter_online',     False)
                inv_online   = r.get('inverters_online', 0)
                inv_total    = r.get('inverters_total',  0)

                total_active_power     += active_power
                if energy_today is not None:
                    total_energy_today += energy_today
                total_ac_capacity      += float(site.ac_capacity_kw or 0)
                if meter_online:
                    sites_online       += 1
                inverters_online_total += inv_online
                inverters_total_total  += inv_total

                site_cards.append({
                    'site_id':          site.pk,
                    'site_name':        site.name,
                    'installer_name':   site.installer.name if site.installer_id else None,
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
            'scope_name': self._scope_name(user),
            'portfolio_summary': {
                'total_active_power_kw':  round(total_active_power, 2),
                'total_energy_today_kwh': round(total_energy_today, 2) if include_energy else None,
                'ac_capacity_kw':         round(total_ac_capacity, 2),
                'sites_online':           sites_online,
                'sites_total':            len(sites),
                'inverters_online':       inverters_online_total,
                'inverters_total':        inverters_total_total,
            },
            'customers': customers_list,
        })