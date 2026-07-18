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

from .queries import get_daily_energy, get_plant_overview, get_plant_power_trend, get_plant_electrical_trend


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
            site=site, device_type='METER', is_active=True, name='HT Meter'
        ).first()
        if not meter:
            return Response(
                {'detail': 'No HT meter found'},
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
            site=site, device_type='METER', is_active=True, name='HT Meter'
        ).first()
        if not meter:
            return Response(
                {'detail': 'No HT meter found'},
                status=status.HTTP_404_NOT_FOUND
            )

        name_map     = {d.influx_device_id: d.name for d in inverters}
        inverter_ids = list(name_map.keys())
        bucket       = site.customer.influx_bucket

        # Optional — not every site has a weather station yet, and an
        # offline/missing station should never take down the rest of the page.
        
        weather_device = Device.objects.filter(
            site=site, device_type='WEATHER_STATION', is_active=True
        ).first()

        dido_device = Device.objects.filter(
            site=site, device_type='DIDO', is_active=True
        ).first()

        try:
            data = get_plant_overview(
                bucket       = bucket,
                site_id      = site.influx_site_id,
                inverter_ids = inverter_ids,
                meter_id     = meter.influx_device_id,
                weather_device_id  = weather_device.influx_device_id if weather_device else None,
                dido_device_id     = dido_device.influx_device_id if dido_device else None,
                dc_capacity_kw     = site.dc_capacity_kw,
                ac_capacity_kw     = site.ac_capacity_kw,
                daily_generation_target_kwh = site.daily_generation_target_kwh,
                meter_energy_offset_kwh = float(meter.energy_offset_kwh),
            )

            # Attach human readable names
            for inv in data['inverters']:
                inv['name'] = name_map.get(inv['device_id'], inv['device_id'])

            # Serialize last_updated if it's a datetime object
            if data.get('last_updated') and hasattr(data['last_updated'], 'isoformat'):
                data['last_updated'] = data['last_updated'].isoformat()

            return Response({
                'site': site.name,
                'customer': site.customer.name,
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
            site=site, device_type='METER', is_active=True, name='HT Meter'
        ).first()
        if not meter:
            return Response(
                {'detail': 'No HT meter found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        weather_device = Device.objects.filter(
            site=site, device_type='WEATHER_STATION', is_active=True
        ).first()

        bucket = site.customer.influx_bucket

        try:
            result = get_plant_power_trend(
                bucket             = bucket,
                site_id            = site.influx_site_id,
                meter_id           = meter.influx_device_id,
                weather_device_id  = weather_device.influx_device_id if weather_device else None,
                date_str           = date_str,
                interval_minutes   = interval,
            )

            return Response({
                'site':     site.name,
                'date':     date_str or 'today',
                'interval': interval,
                'data':     result['data'],
                'stats':    result['stats'],
            })

        except Exception as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        
class PlantElectricalTrendView(TenantFilterMixin, APIView):
    """
    GET /api/v1/plant/electrical-trend/?site=1&date=2026-06-03&interval=5
    HT meter voltage/current/frequency trend for a selected date.
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
            site=site, device_type='METER', is_active=True, name='HT Meter'
        ).first()
        if not meter:
            return Response(
                {'detail': 'No active HT meter found'},
                status=status.HTTP_404_NOT_FOUND
            )

        bucket = site.customer.influx_bucket

        try:
            result = get_plant_electrical_trend(
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
                'data':     result['data'],
                'stats':    result['stats'],
            })

        except Exception as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )