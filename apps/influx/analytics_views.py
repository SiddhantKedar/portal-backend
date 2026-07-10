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
    GET /api/v1/influx/analytics/?site=1&metrics=active_power,irradiation&devices=1,2,3&date=2026-06-18&interval=5
    'metrics' is comma-separated — one or more metric keys.
    Manually triggered by the frontend — never polled.

    Returns merged, time-aligned points (one array, one row per timestamp)
    plus a 'legend' describing what each point key means, so the frontend
    can plot arbitrary metric/device combinations on the same or separate
    axes without guessing at key formats.
    """
    permission_classes = [IsAnyRole]

    def get(self, request):
        site_id     = request.query_params.get('site')
        metrics_str = request.query_params.get('metrics')
        device_ids  = request.query_params.get('devices')
        date_str    = request.query_params.get('date', None)
        interval    = int(request.query_params.get('interval', 5))

        if not site_id or not metrics_str or not device_ids:
            return Response(
                {'detail': 'site, metrics and devices params are required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if interval < 5:
            interval = 5

        metric_keys = [m for m in metrics_str.split(',') if m]
        metrics     = {}
        for metric_key in metric_keys:
            metric = ANALYTICS_METRICS.get(metric_key)
            if not metric:
                return Response({'detail': f'Unknown metric "{metric_key}"'}, status=status.HTTP_400_BAD_REQUEST)
            metrics[metric_key] = metric

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

        # Build one series entry per (device, metric) combo whose device_type
        # has a mapped field for that metric — combos with no mapping are
        # dropped silently, same behavior as before.
        series_map = {}   # series_key -> {'device': influx_device_id, 'field': field_name}
        legend     = []   # description of each series_key, for the frontend

        for device in devices:
            for metric_key, metric in metrics.items():
                field = metric['fields'].get(device.device_type)
                if not field:
                    continue
                series_key = f'{device.influx_device_id}__{metric_key}'
                series_map[series_key] = {'device': device.influx_device_id, 'field': field}
                legend.append({
                    'key':         series_key,
                    'device_id':   device.pk,
                    'device_name': device.name,
                    'device_type': device.device_type,
                    'metric':      metric_key,
                    'label':       metric['label'],
                    'unit':        metric['unit'],
                })

        if not series_map:
            return Response({
                'date': date_str or 'today', 'legend': [], 'data': [],
            })

        try:
            data = get_analytics_data(
                bucket           = site.customer.influx_bucket,
                site_id          = site.influx_site_id,
                series_map       = series_map,
                date_str         = date_str,
                interval_minutes = interval,
            )

            return Response({
                'date': date_str or 'today', 'legend': legend, 'data': data,
            })

        except Exception as e:
            return Response({'detail': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)