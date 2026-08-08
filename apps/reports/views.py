# apps/reports/views.py
# Read side of the reports app: monthly / date-range site report,
# served entirely from DailySiteSnapshot (Postgres). No InfluxDB.

from datetime import datetime, timedelta, timezone as dt_timezone

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from core.permissions import IsAnyRole
from core.mixins import TenantFilterMixin

from .aggregation import build_site_report

IST = dt_timezone(timedelta(hours=5, minutes=30))


class SiteReportView(TenantFilterMixin, APIView):
    """
    GET /api/v1/reports/summary/?site=1&start=2026-07-01&end=2026-07-31

    Monthly (or any date-range) report for one site. start/end default to
    1st-of-current-month → today (IST), so it reads as "this month" on load.
    Called on page load and when the user changes the range — never polled.
    Site is resolved through get_filtered_sites() so the SITE_USER boundary
    holds here exactly as on the influx endpoints.
    """
    permission_classes = [IsAnyRole]

    def get(self, request):
        site_id   = request.query_params.get('site')
        start_str = request.query_params.get('start')
        end_str   = request.query_params.get('end')

        if not site_id:
            return Response({'detail': 'site param is required'},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            site = self.get_filtered_sites().get(pk=site_id)
        except Exception:
            return Response({'detail': 'Site not found'},
                            status=status.HTTP_404_NOT_FOUND)

        today_ist = datetime.now(IST).date()
        yesterday_ist = today_ist - timedelta(days=1)
        try:
            end_date   = self._parse_date(end_str)   if end_str   else yesterday_ist
            start_date = self._parse_date(start_str) if start_str else end_date.replace(day=1)
        except ValueError:
            return Response({'detail': 'Invalid date — expected YYYY-MM-DD.'},
                            status=status.HTTP_400_BAD_REQUEST)

        if end_date < start_date:
            return Response({'detail': 'end is before start.'},
                            status=status.HTTP_400_BAD_REQUEST)

        report = build_site_report(site, start_date, end_date)

        return Response({
            'site':     site.name,
            'customer': site.customer.name,
            **report,
        })

    def _parse_date(self, s):
        return datetime.strptime(s, '%Y-%m-%d').date()