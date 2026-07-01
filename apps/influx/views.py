# apps/influx/views.py
# API endpoints that return InfluxDB data.
# Every endpoint:
#   1. Looks up the site/device from Postgres (tenant filtered)
#   2. Uses the influx IDs from those records to query InfluxDB
#   3. Returns the data to the frontend
#
# The frontend never knows about InfluxDB directly.

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from core.permissions import IsAnyRole
from core.mixins import TenantFilterMixin
from apps.sites.models import Site, Device

from .queries import get_system_health, get_latest_system_health


class SystemHealthView(TenantFilterMixin, APIView):
    """
    GET /api/v1/influx/system-health/?site=1&device=1&hours=3
    Returns system health time series for a device.
    """
    permission_classes = [IsAnyRole]

    def get(self, request):
        site_id   = request.query_params.get('site')
        device_id = request.query_params.get('device')
        hours     = int(request.query_params.get('hours', 3))

        # Validate required params
        if not site_id or not device_id:
            return Response(
                {'detail': 'site and device params are required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Fetch site and device from Postgres (tenant filtered)
        # This ensures user can only query data they own
        try:
            site   = self.get_filtered_sites().get(pk=site_id)
            device = self.get_filtered_devices().get(pk=device_id, site=site)
        except (Site.DoesNotExist, Device.DoesNotExist):
            return Response(
                {'detail': 'Site or device not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        # Get bucket from the customer record
        bucket = site.customer.influx_bucket

        if not bucket:
            return Response(
                {'detail': 'InfluxDB bucket not configured for this customer'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            data = get_system_health(
                bucket    = bucket,
                site_id   = site.influx_site_id,
                device_id = device.influx_device_id,
                range_hours = hours
            )
            return Response({
                'site'   : site.name,
                'device' : device.name,
                'data'   : data
            })
        except Exception as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class SystemHealthLatestView(TenantFilterMixin, APIView):
    """
    GET /api/v1/influx/system-health/latest/?site=1&device=1
    Returns only the most recent system health values.
    Used for live status cards on dashboard.
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
            site   = self.get_filtered_sites().get(pk=site_id)
            device = self.get_filtered_devices().get(pk=device_id, site=site)
        except (Site.DoesNotExist, Device.DoesNotExist):
            return Response(
                {'detail': 'Site or device not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        bucket = site.customer.influx_bucket

        if not bucket:
            return Response(
                {'detail': 'InfluxDB bucket not configured for this customer'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            data = get_latest_system_health(
                bucket    = bucket,
                site_id   = site.influx_site_id,
                device_id = device.influx_device_id,
            )
            return Response({
                'site'   : site.name,
                'device' : device.name,
                'data'   : data
            })
        except Exception as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )