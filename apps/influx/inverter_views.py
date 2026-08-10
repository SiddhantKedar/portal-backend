# apps/influx/inverter_views.py
# Inverter overview page endpoints.
# Two endpoints:
#   1. /inverter/overview/    → live stats, polls every 60s
#   2. /inverter/power-trend/ → chart data, called on load + date change

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from core.permissions import IsAnyRole
from core.mixins import TenantFilterMixin
from apps.sites.models import Device

from .queries import get_inverter_overview, get_inverter_power_trend


class InverterOverviewView(TenantFilterMixin, APIView):
    """
    GET /api/v1/inverter/overview/?site=1
    Returns live data for all inverters at a site.
    Frontend polls this every 60 seconds.
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

        weather_device = Device.objects.filter(
            site=site, device_type='WEATHER_STATION', is_active=True
        ).first()
        weather_device_id = weather_device.influx_device_id if weather_device else None

        try:
            data = get_inverter_overview(
                bucket       = bucket,
                site_id      = site.influx_site_id,
                inverter_ids = inverter_ids,
                weather_device_id = weather_device_id,
                dc_capacity_kw    = site.dc_capacity_kw,
            )

            # Attach human readable names
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


class InverterPowerTrendView(TenantFilterMixin, APIView):
    """
    GET /api/v1/inverter/power-trend/?site=1&date=2026-06-15&interval=5
    Returns summed inverter power trend for a selected date.
    date defaults to today if not provided.
    Called on page load and when date picker changes — not on every poll.
    """
    permission_classes = [IsAnyRole]

    def get(self, request):
        site_id  = request.query_params.get('site')
        date_str = request.query_params.get('date', None)
        interval = int(request.query_params.get('interval', 5))

        if not site_id:
            return Response(
                {'detail': 'site param is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if interval < 5:
            interval = 5

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

        weather_device = Device.objects.filter(
            site=site, device_type='WEATHER_STATION', is_active=True
        ).first()
        weather_device_id = weather_device.influx_device_id if weather_device else None

        try:
            data = get_inverter_power_trend(
                bucket            = bucket,
                site_id           = site.influx_site_id,
                inverter_ids      = inverter_ids,
                weather_device_id = weather_device_id,
                date_str          = date_str,
                interval_minutes  = interval,
            )

            return Response({
                'site':     site.name,
                'date':     date_str or 'today',
                'interval': interval,
                'data':     data['data'],
                'stats':    data['stats'],
            })

        except Exception as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )