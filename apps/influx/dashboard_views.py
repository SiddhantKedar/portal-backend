# apps/influx/dashboard_views.py
# Two dashboard endpoints:
#   1. /dashboard/overview/ — everything for the plant page, one call
#   2. /dashboard/daily-energy/ — 7 day bar chart, called once on load

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from core.permissions import IsAnyRole
from core.mixins import TenantFilterMixin
from apps.sites.models import Device

from .queries import get_dashboard_overview, get_daily_energy, get_plant_overview, get_plant_power_trend   


class DashboardOverviewView(TenantFilterMixin, APIView):
    """
    GET /api/v1/dashboard/overview/?site=1&interval=5
    Single endpoint for the full plant overview page.
    Frontend polls this every 60 seconds.
    Returns plant stats, grid values, per-inverter data, power trend.
    """
    permission_classes = [IsAnyRole]

    def get(self, request):
        site_id  = request.query_params.get('site')
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

        # Get all active inverters
        inverters = Device.objects.filter(
            site=site, device_type='INVERTER', is_active=True
        )
        if not inverters.exists():
            return Response(
                {'detail': 'No active inverters found'},
                status=status.HTTP_404_NOT_FOUND
            )

        # Get plant meter (meter1)
        meter = Device.objects.filter(
            site=site, device_type='METER', is_active=True
        ).first()
        if not meter:
            return Response(
                {'detail': 'No active meter found'},
                status=status.HTTP_404_NOT_FOUND
            )

        # Build name map for inverters: influx_id → human name
        name_map     = {d.influx_device_id: d.name for d in inverters}
        inverter_ids = list(name_map.keys())
        bucket       = site.customer.influx_bucket

        try:
            data = get_dashboard_overview(
                bucket           = bucket,
                site_id          = site.influx_site_id,
                inverter_ids     = inverter_ids,
                meter_id         = meter.influx_device_id,
                interval_minutes = interval,
            )

            # Attach human readable names to inverter list
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


class DailyEnergyView(TenantFilterMixin, APIView):
    """
    GET /api/v1/dashboard/daily-energy/?site=1&days=7
    Returns daily generation for the last N days.
    Used for the bar chart — call once on page load, not on every poll.
    """
    permission_classes = [IsAnyRole]

    def get(self, request):
        site_id = request.query_params.get('site')
        days    = int(request.query_params.get('days', 7))

        if not site_id:
            return Response(
                {'detail': 'site param is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Cap at 30 days max
        if days > 30:
            days = 30

        try:
            site = self.get_filtered_sites().get(pk=site_id)
        except Exception:
            return Response(
                {'detail': 'Site not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        meter = Device.objects.filter(
            site=site, device_type='METER', is_active=True
        ).first()
        if not meter:
            return Response(
                {'detail': 'No active meter found'},
                status=status.HTTP_404_NOT_FOUND
            )

        bucket = site.customer.influx_bucket

        try:
            data = get_daily_energy(
                bucket   = bucket,
                site_id  = site.influx_site_id,
                meter_id = meter.influx_device_id,
                days     = days,
            )
            return Response({
                'site': site.name,
                'days': days,
                'data': data,
            })

        except Exception as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        

class PlantOverviewView(TenantFilterMixin, APIView):
    """
    GET /api/v1/plant/overview/?site=1
    Single endpoint for the plant overview page.
    Polls every 60 seconds for live data.
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

        meter = Device.objects.filter(
            site=site, device_type='METER', is_active=True
        ).first()
        if not meter:
            return Response(
                {'detail': 'No active meter found'},
                status=status.HTTP_404_NOT_FOUND
            )

        name_map     = {d.influx_device_id: d.name for d in inverters}
        inverter_ids = list(name_map.keys())
        bucket       = site.customer.influx_bucket

        try:
            data = get_plant_overview(
                bucket       = bucket,
                site_id      = site.influx_site_id,
                inverter_ids = inverter_ids,
                meter_id     = meter.influx_device_id,
            )

            # Attach human readable names
            for inv in data['inverters']:
                inv['name'] = name_map.get(inv['device_id'], inv['device_id'])

            # Serialize last_updated if it's a datetime object
            if data.get('last_updated') and hasattr(data['last_updated'], 'isoformat'):
                data['last_updated'] = data['last_updated'].isoformat()

            return Response({
                'site': site.name,
                **data,
            })

        except Exception as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class PlantPowerTrendView(TenantFilterMixin, APIView):
    """
    GET /api/v1/plant/power-trend/?site=1&date=2026-06-03&interval=5
    Power trend for a selected date.
    date defaults to today if not provided.
    Called on page load and when user picks a new date — not on every poll.
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

        meter = Device.objects.filter(
            site=site, device_type='METER', is_active=True
        ).first()
        if not meter:
            return Response(
                {'detail': 'No active meter found'},
                status=status.HTTP_404_NOT_FOUND
            )

        bucket = site.customer.influx_bucket

        try:
            data = get_plant_power_trend(
                bucket           = bucket,
                site_id          = site.influx_site_id,
                meter_id         = meter.influx_device_id,
                date_str         = date_str,
                interval_minutes = interval,
            )

            return Response({
                'site':     site.name,
                'date':     date_str or 'today',
                'interval': interval,
                'data':     data,
            })

        except Exception as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )