# apps/influx/temp_inverter_status_views.py
#
# TEMPORARY — admin-only inverter_status monitor for the portfolio front page.
# Self-contained on purpose: delete this file + its one line in urls.py once the
# inverter_status field is confirmed working. Flux lives here (not queries.py)
# deliberately, to keep the whole throwaway unit in one deletable place.

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status as http_status

from core.permissions import IsAdminUser
from core.mixins import TenantFilterMixin
from apps.sites.models import Device

from .client import get_influx_client
from .queries import INFLUX_ORG


# Single active bit → label. 0 = no bit set = Stopped. Multi-bit not enabled yet.
_STATUS_LABELS = {0: 'Stopped', 1: 'Running', 2: 'Standby', 4: 'Warning', 8: 'Fault'}


def _label(code):
    return _STATUS_LABELS.get(code, 'Unknown')


def _collapse_runs(samples):
    """
    samples: [(time, value_float), ...] ascending, for ONE device.
    Collapses consecutive equal states into runs. Returns newest-first
    [{ code, label, start, end }] — end is the next run's start (the transition
    time), None for the current ongoing run. The earliest run's start is clamped
    to the window edge, not necessarily its true transition (bounded 12h view).
    """
    runs = []
    for t, v in samples:
        code = int(round(v))
        if runs and runs[-1]['code'] == code:
            continue
        runs.append({'code': code, 'start': t})

    out = []
    for i, r in enumerate(runs):
        end = runs[i + 1]['start'] if i + 1 < len(runs) else None
        out.append({
            'code':  r['code'],
            'label': _label(r['code']),
            'start': r['start'].isoformat(),
            'end':   end.isoformat() if end else None,
        })
    out.reverse()   # current run first
    return out


class TempInverterStatusView(TenantFilterMixin, APIView):
    """
    GET /api/v1/influx/admin/inverter-status/   (admin only, temporary)

    Every inverter the admin can see: latest inverter_status ("current", since
    when) + a 12h history collapsed to state-change intervals. No freshness gate
    — shows the last captured value as-is.
    """
    permission_classes = [IsAdminUser]
    HISTORY_HOURS = 12

    def get(self, request):
        sites = self.get_filtered_sites().select_related('customer').order_by('name')

        client    = get_influx_client()
        query_api = client.query_api()

        try:
            site_blocks = []
            for site in sites:
                inverters = list(Device.objects.filter(
                    site=site, device_type='INVERTER', is_active=True
                ))
                if not inverters:
                    continue

                name_map     = {d.influx_device_id: d.name for d in inverters}
                inverter_ids = list(name_map.keys())

                samples_by_device = self._query_status_series(
                    query_api, site.customer.influx_bucket,
                    site.influx_site_id, inverter_ids, self.HISTORY_HOURS,
                )

                inv_blocks = []
                for device_id in inverter_ids:
                    history = _collapse_runs(samples_by_device.get(device_id, []))
                    current = history[0] if history else None
                    inv_blocks.append({
                        'device_id': device_id,
                        'name':      name_map.get(device_id, device_id),
                        'current': (
                            {'code': current['code'], 'label': current['label'],
                             'since': current['start']}
                            if current else None
                        ),
                        'history': history,
                    })

                site_blocks.append({
                    'site_id':        site.id,
                    'site_name':      site.name,
                    'influx_site_id': site.influx_site_id,
                    'customer':       site.customer.name,
                    'inverters':      inv_blocks,
                })

            return Response({
                'history_window_hours': self.HISTORY_HOURS,
                'sites': site_blocks,
            })

        except Exception as e:
            return Response({'detail': str(e)},
                            status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)
        finally:
            client.close()

    def _query_status_series(self, query_api, bucket, site_id, inverter_ids, hours):
        """One query per site: raw inverter_status over -{hours}h, grouped by
        device. Returns { device_id: [(time, value_float), ...] } ascending."""
        device_filter = ' or '.join([f'r.device == "{d}"' for d in inverter_ids])
        flux = f'''
            from(bucket: "{bucket}")
                |> range(start: -{hours}h)
                |> filter(fn: (r) => r._measurement == "solar_data")
                |> filter(fn: (r) => r.site == "{site_id}")
                |> filter(fn: (r) => {device_filter})
                |> filter(fn: (r) => r._field == "inverter_status")
                |> map(fn: (r) => ({{r with _value: float(v: r._value)}}))
                |> sort(columns: ["_time"])
        '''
        out = {}
        for table in query_api.query(flux, org=INFLUX_ORG):
            for record in table.records:
                device = record.values.get('device')
                value  = record.get_value()
                time   = record.get_time()
                if device is None or value is None or time is None:
                    continue
                out.setdefault(device, []).append((time, value))
        for dev in out:
            out[dev].sort(key=lambda p: p[0])
        return out