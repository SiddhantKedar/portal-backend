# apps/influx/faults_views.py
# Inverter faults / status-timeline page — per-site, one IST day.
#   GET /api/v1/influx/faults/?site=1&date=2026-08-17
# date optional → today (IST). Called on page load and on date-picker change.
# For 'today' the frontend can refresh on the usual 60s cadence to keep `current`
# live; past dates are static.

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from core.permissions import IsAnyRole
from core.mixins import TenantFilterMixin
from apps.sites.models import Device

from .queries import get_inverter_faults


class InverterFaultsView(TenantFilterMixin, APIView):
    """
    Per-inverter inverter_status timeline for a site and IST day, plus the
    freshness-gated current state (today only). Tenant-scoped like the rest of
    the dashboard — a user sees faults only for sites they can already reach.
    """
    permission_classes = [IsAnyRole]

    def get(self, request):
        site_id  = request.query_params.get('site')
        date_str = request.query_params.get('date', None)

        if not site_id:
            return Response(
                {'detail': 'site param is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            site = self.get_filtered_sites().get(pk=site_id)
        except Exception:
            return Response(
                {'detail': 'Site not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        inverters = Device.objects.filter(
            site=site, device_type='INVERTER', is_active=True
        )
        if not inverters.exists():
            return Response(
                {'detail': 'No active inverters found'},
                status=status.HTTP_404_NOT_FOUND
            )

        name_map     = {d.influx_device_id: d.name for d in inverters}
        inverter_ids = list(name_map.keys())
        bucket       = site.customer.influx_bucket

        try:
            data = get_inverter_faults(
                bucket       = bucket,
                site_id      = site.influx_site_id,
                inverter_ids = inverter_ids,
                date_str     = date_str,
            )

            for inv in data['inverters']:
                inv['name'] = name_map.get(inv['device_id'], inv['device_id'])

            return Response({
                'site': site.name,
                **data,
            })

        except Exception as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )