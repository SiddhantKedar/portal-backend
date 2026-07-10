# apps/influx/inverter_detail_views.py
# Per-inverter detail page endpoints.
# Three endpoints:
#   1. /inverter/detail/                → live snapshot + PV strings, polls every 60s
#   2. /inverter/detail/power-trend/    → DC/Active/Reactive chart, load + date change
#   3. /inverter/detail/daily-energy/   → 7-day bars for this inverter, load only

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from core.permissions import IsAnyRole
from core.mixins import TenantFilterMixin
from apps.sites.models import Device

from .queries import (
    get_inverter_detail,
    get_inverter_detail_power_trend,
    get_inverter_daily_energy,
)


class InverterDetailView(TenantFilterMixin, APIView):
    """
    GET /api/v1/inverter/detail/?site=1&device=3
    Live snapshot for a single inverter, including raw PV string currents.
    Frontend polls this every 60 seconds.
    """
    permission_classes = [IsAnyRole]

    def get(self, request):
        site_id   = request.query_params.get('site')
        device_id = request.query_params.get('device')

        if not site_id or not device_id:
            return Response(
                {'detail': 'site and device params are required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            site = self.get_filtered_sites().get(pk=site_id)
        except Exception:
            return Response({'detail': 'Site not found'}, status=status.HTTP_404_NOT_FOUND)

        try:
            device = Device.objects.get(
                pk=device_id, site=site, device_type='INVERTER', is_active=True
            )
        except Device.DoesNotExist:
            return Response({'detail': 'Inverter not found'}, status=status.HTTP_404_NOT_FOUND)

        weather_device = Device.objects.filter(
            site=site, device_type='WEATHER_STATION', is_active=True
        ).first()
        weather_device_id = weather_device.influx_device_id if weather_device else None

        active_inverter_count = Device.objects.filter(
            site=site, device_type='INVERTER', is_active=True
        ).count()
        dc_capacity_per_inverter = (
            float(site.dc_capacity_kw) / active_inverter_count
            if site.dc_capacity_kw and active_inverter_count > 0 else None
        )

        try:
            data = get_inverter_detail(
                bucket                   = site.customer.influx_bucket,
                site_id                  = site.influx_site_id,
                device_id                = device.influx_device_id,
                weather_device_id        = weather_device_id,
                dc_capacity_per_inverter = dc_capacity_per_inverter,
            )
            data['name'] = device.name

            return Response({
                'site': site.name,
                **data,
            })

        except Exception as e:
            return Response({'detail': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class InverterDetailPowerTrendView(TenantFilterMixin, APIView):
    """
    GET /api/v1/inverter/detail/power-trend/?site=1&device=3&date=2026-06-15&interval=5
    DC Input / Active / Reactive power trend for one inverter, selected date.
    """
    permission_classes = [IsAnyRole]

    def get(self, request):
        site_id   = request.query_params.get('site')
        device_id = request.query_params.get('device')
        date_str  = request.query_params.get('date', None)
        interval  = int(request.query_params.get('interval', 5))

        if not site_id or not device_id:
            return Response(
                {'detail': 'site and device params are required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if interval < 5:
            interval = 5

        try:
            site = self.get_filtered_sites().get(pk=site_id)
        except Exception:
            return Response({'detail': 'Site not found'}, status=status.HTTP_404_NOT_FOUND)

        try:
            device = Device.objects.get(
                pk=device_id, site=site, device_type='INVERTER', is_active=True
            )
        except Device.DoesNotExist:
            return Response({'detail': 'Inverter not found'}, status=status.HTTP_404_NOT_FOUND)

        try:
            data = get_inverter_detail_power_trend(
                bucket           = site.customer.influx_bucket,
                site_id          = site.influx_site_id,
                device_id        = device.influx_device_id,
                date_str         = date_str,
                interval_minutes = interval,
            )

            return Response({
                'site':     site.name,
                'device':   device.name,
                'date':     date_str or 'today',
                'interval': interval,
                'data':     data,
            })

        except Exception as e:
            return Response({'detail': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class InverterDailyEnergyView(TenantFilterMixin, APIView):
    """
    GET /api/v1/inverter/detail/daily-energy/?site=1&device=3&days=7
    One inverter's own daily generation for the last N days. Load only, not polled.
    """
    permission_classes = [IsAnyRole]

    def get(self, request):
        site_id   = request.query_params.get('site')
        device_id = request.query_params.get('device')
        days      = int(request.query_params.get('days', 7))

        if not site_id or not device_id:
            return Response(
                {'detail': 'site and device params are required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            site = self.get_filtered_sites().get(pk=site_id)
        except Exception:
            return Response({'detail': 'Site not found'}, status=status.HTTP_404_NOT_FOUND)

        try:
            device = Device.objects.get(
                pk=device_id, site=site, device_type='INVERTER', is_active=True
            )
        except Device.DoesNotExist:
            return Response({'detail': 'Inverter not found'}, status=status.HTTP_404_NOT_FOUND)

        try:
            data = get_inverter_daily_energy(
                bucket    = site.customer.influx_bucket,
                site_id   = site.influx_site_id,
                device_id = device.influx_device_id,
                days      = days,
            )

            return Response({
                'site':   site.name,
                'device': device.name,
                'days':   days,
                'data':   data,
            })

        except Exception as e:
            return Response({'detail': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)