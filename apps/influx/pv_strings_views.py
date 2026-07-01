# apps/influx/pv_strings_views.py
# PV Strings page — every inverter's string currents for a site, one call.

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from core.permissions import IsAnyRole
from core.mixins import TenantFilterMixin
from apps.sites.models import Device

from .queries import get_all_inverters_pv_strings


class InverterPvStringsView(TenantFilterMixin, APIView):
    """
    GET /api/v1/inverter/pv-strings/?site=1
    Returns PV string currents for every active inverter at the site.
    """
    permission_classes = [IsAnyRole]

    def get(self, request):
        site_id = request.query_params.get('site')

        if not site_id:
            return Response(
                {'detail': 'site param is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            site = self.get_filtered_sites().get(pk=site_id)
        except Exception:
            return Response({'detail': 'Site not found'}, status=status.HTTP_404_NOT_FOUND)

        inverters = Device.objects.filter(
            site=site, device_type='INVERTER', is_active=True
        )
        if not inverters.exists():
            return Response(
                {'detail': 'No active inverters found'},
                status=status.HTTP_404_NOT_FOUND
            )

        device_map   = {d.influx_device_id: d for d in inverters}
        inverter_ids = list(device_map.keys())

        try:
            pv_data = get_all_inverters_pv_strings(
                bucket       = site.customer.influx_bucket,
                site_id      = site.influx_site_id,
                inverter_ids = inverter_ids,
            )

            inverter_list = []
            for tag, device in device_map.items():
                strings = pv_data.get(tag, {})
                pv_strings = [
                    {'number': number, 'current_a': round(value, 3)}
                    for number, value in sorted(strings.items(), key=lambda x: int(x[0]))
                ]
                inverter_list.append({
                    'device_id':  device.pk,
                    'name':       device.name,
                    'pv_strings': pv_strings,
                })

            inverter_list.sort(key=lambda inv: inv['device_id'])

            return Response({
                'site':      site.name,
                'inverters': inverter_list,
            })

        except Exception as e:
            return Response({'detail': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)