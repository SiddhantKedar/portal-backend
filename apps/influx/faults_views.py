# apps/influx/faults_views.py
# Faults page — inverter status timeline + transformer annunciator alarm history,
# per-site, one IST day.
#   GET /api/v1/influx/faults/?site=1&date=2026-09-09
# date optional → today (IST). Both sections are capability-driven: a site renders
# only what it has. `annunciator` (bool) tells the frontend whether to load the
# alarm section at all; `annunciator_data` is null when the site has none.

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from core.permissions import IsAnyRole
from core.mixins import TenantFilterMixin
from apps.sites.models import Device

from .queries import get_inverter_faults, get_annunciator_history


class InverterFaultsView(TenantFilterMixin, APIView):
    """
    Inverter status timeline + annunciator alarm log for a site and IST day.
    Tenant-scoped — a user sees faults only for sites they can already reach.

    Capability-driven: the two sections are independent. A transformer-only site
    (GSS/substation, no inverters) still returns its alarm history; a site with no
    annunciator returns annunciator=false / null data so the frontend skips that
    section without a wasted request. 404 only when the site has neither.
    """
    permission_classes = [IsAnyRole]

    def get(self, request):
        site_id  = request.query_params.get('site')
        date_str = request.query_params.get('date', None)

        if not site_id:
            return Response({'detail': 'site param is required'},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            site = self.get_filtered_sites().get(pk=site_id)
        except Exception:
            return Response({'detail': 'Site not found'},
                            status=status.HTTP_404_NOT_FOUND)

        inverters = Device.objects.filter(
            site=site, device_type='INVERTER', is_active=True
        )
        annunciators = Device.objects.filter(
            site=site, device_type='ANNUNCIATOR', is_active=True
        )

        # Nothing on the faults page for this site at all.
        if not inverters.exists() and not annunciators.exists():
            return Response({'detail': 'No active inverters or annunciators found'},
                            status=status.HTTP_404_NOT_FOUND)

        bucket = site.customer.influx_bucket

        try:
            # ── Inverter timeline (skipped for annunciator-only sites) ──
            inv_block = None
            if inverters.exists():
                inv_name_map = {d.influx_device_id: d.name for d in inverters}
                inv_block = get_inverter_faults(
                    bucket       = bucket,
                    site_id      = site.influx_site_id,
                    inverter_ids = list(inv_name_map.keys()),
                    date_str     = date_str,
                )
                for inv in inv_block['inverters']:
                    inv['name'] = inv_name_map.get(inv['device_id'], inv['device_id'])

            # ── Annunciator alarm history (only if the site has one) ──
            ann_block = None
            if annunciators.exists():
                ann_name_map = {d.influx_device_id: d.name for d in annunciators}
                ann_block = get_annunciator_history(
                    bucket     = bucket,
                    site_id    = site.influx_site_id,
                    device_ids = list(ann_name_map.keys()),
                    date_str   = date_str,
                )
                for ann in ann_block['annunciators']:
                    ann['name'] = ann_name_map.get(ann['device_id'], ann['device_id'])

            # Top-level day/window from whichever section ran (identical either way;
            # at least one is present thanks to the 404 guard above).
            meta = inv_block or ann_block

            return Response({
                'site':      site.name,
                'date':      meta['date'],
                'is_today':  meta['is_today'],
                'window':    meta['window'],

                # Inverter section — unchanged shape; empty for annunciator-only sites.
                'inverters': inv_block['inverters'] if inv_block else [],
                'gap_threshold_seconds': (
                    inv_block['gap_threshold_seconds'] if inv_block else None
                ),

                # Annunciator section — capability flag + null-when-absent data.
                'annunciator': bool(ann_block),
                'annunciator_data': ({
                    'gap_threshold_seconds': ann_block['gap_threshold_seconds'],
                    'channels': ann_block['channels'],
                    'devices':  ann_block['annunciators'],
                } if ann_block else None),
            })

        except Exception as e:
            return Response({'detail': str(e)},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)