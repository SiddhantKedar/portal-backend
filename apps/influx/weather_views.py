# apps/influx/weather_views.py
# Weather station live snapshot.
# GET /api/v1/influx/weather/?site=1

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from core.permissions import IsAnyRole
from core.mixins import TenantFilterMixin
from apps.sites.models import Device

from .queries import get_weather_snapshot


class WeatherSnapshotView(TenantFilterMixin, APIView):
    """
    GET /api/v1/influx/weather/?site=1
    Live snapshot for all weather station fields.
    Poll every 60 seconds.
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

        try:
            device = Device.objects.get(
                site=site, device_type='WEATHER_STATION', is_active=True
            )
        except Device.DoesNotExist:
            return Response(
                {'detail': 'No active weather station found'},
                status=status.HTTP_404_NOT_FOUND
            )

        try:
            data = get_weather_snapshot(
                bucket    = site.customer.influx_bucket,
                site_id   = site.influx_site_id,
                device_id = device.influx_device_id,
            )

            return Response({
                'site':   site.name,
                'device': device.name,
                **data,
            })

        except Exception as e:
            return Response({'detail': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)