from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from core.permissions import IsAnyRole
from core.mixins import TenantFilterMixin

from .metrics import ANALYTICS_METRICS
from .queries import get_analytics_data


class AnalyticsMetricsListView(APIView):
    permission_classes = [IsAnyRole]

    def get(self, request):
        return Response([
            {
                'key':          key,
                'label':        m['label'],
                'unit':         m['unit'],
                'device_types': list(m['fields'].keys()),
            }
            for key, m in ANALYTICS_METRICS.items()
        ])


class AnalyticsView(TenantFilterMixin, APIView):
    """
    GET /api/v1/influx/analytics/?site=1&metric=active_power&devices=1,2,3&date=2026-06-18&interval=5
    Manually triggered by the frontend — never polled.
    """
    permission_classes = [IsAnyRole]

    def get(self, request):
        site_id    = request.query_params.get('site')
        metric_key = request.query_params.get('metric')
        device_ids = request.query_params.get('devices')
        date_str   = request.query_params.get('date', None)
        interval   = int(request.query_params.get('interval', 5))

        if not site_id or not metric_key or not device_ids:
            return Response(
                {'detail': 'site, metric and devices params are required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if interval < 5:
            interval = 5

        metric = ANALYTICS_METRICS.get(metric_key)
        if not metric:
            return Response({'detail': f'Unknown metric "{metric_key}"'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            site = self.get_filtered_sites().get(pk=site_id)
        except Exception:
            return Response({'detail': 'Site not found'}, status=status.HTTP_404_NOT_FOUND)

        try:
            requested_pks = [int(d) for d in device_ids.split(',') if d]
        except ValueError:
            return Response({'detail': 'devices must be comma-separated IDs'}, status=status.HTTP_400_BAD_REQUEST)

        devices = self.get_filtered_devices().filter(
            pk__in=requested_pks, site=site, is_active=True
        )

        # Devices whose type has no mapped field for this metric are dropped silently
        device_field_map = {}
        device_lookup     = {}
        for device in devices:
            field = metric['fields'].get(device.device_type)
            if field:
                device_field_map[device.influx_device_id] = field
                device_lookup[device.influx_device_id]    = device

        if not device_field_map:
            return Response({
                'metric': metric_key, 'label': metric['label'], 'unit': metric['unit'],
                'date': date_str or 'today', 'series': [],
            })

        try:
            data = get_analytics_data(
                bucket           = site.customer.influx_bucket,
                site_id          = site.influx_site_id,
                device_field_map = device_field_map,
                date_str         = date_str,
                interval_minutes = interval,
            )

            series = [
                {
                    'device_id':   device_lookup[tag].pk,
                    'device_name': device_lookup[tag].name,
                    'device_type': device_lookup[tag].device_type,
                    'data':        points,
                }
                for tag, points in data.items()
            ]

            return Response({
                'metric': metric_key, 'label': metric['label'], 'unit': metric['unit'],
                'date': date_str or 'today', 'series': series,
            })

        except Exception as e:
            return Response({'detail': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)