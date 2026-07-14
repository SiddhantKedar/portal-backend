# apps/influx/meter_views.py
# Meter overview page - tabular view of all meters at a site,
# including its linked substation if one exists.

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from core.permissions import IsAnyRole
from core.mixins import TenantFilterMixin
from apps.sites.models import Device

from .queries import get_meter_overview


class MeterOverviewView(TenantFilterMixin, APIView):
    """
    GET /api/v1/influx/meter/overview/?site=1
    Returns all meters for the given site, plus all meters from its
    linked substation if one exists.
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
            return Response(
                {'detail': 'Site not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        bucket = site.customer.influx_bucket

        # Build the main site's meter group
        main_meters = Device.objects.filter(
            site=site, device_type='METER', is_active=True
        )

        sites_with_meters = [{
            'influx_site_id': site.influx_site_id,
            'site_type':      site.site_type,
            'meters': [
                {
                    'influx_device_id':  d.influx_device_id,
                    'name':              d.name,
                    'pk':                d.id,
                    'energy_offset_kwh': float(d.energy_offset_kwh),
                }
                for d in main_meters
            ]
        }]

        # Check for a linked substation
        substation = site.related_sites.filter(site_type='SUBSTATION').first()
        substation_name = None

        if substation:
            substation_name = substation.name
            sub_meters = Device.objects.filter(
                site=substation, device_type='METER', is_active=True
            )
            sites_with_meters.append({
                'influx_site_id': substation.influx_site_id,
                'site_type':       substation.site_type,
                'meters': [
                    {'influx_device_id': d.influx_device_id, 
                     'name': d.name, 
                     'pk': d.id,
                     'energy_offset_kwh': float(d.energy_offset_kwh),
                    }
                    for d in sub_meters
                ]
            })

        try:
            meters = get_meter_overview(
                bucket             = bucket,
                sites_with_meters  = sites_with_meters,
            )

            return Response({
                'site':       site.name,
                'substation': substation_name,   # null if no substation
                'meters':     meters,
            })

        except Exception as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )