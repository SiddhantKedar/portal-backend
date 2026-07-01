# apps/sites/views.py
# API views for customers, sites and devices.
# Every view uses TenantFilterMixin so data is automatically
# filtered based on who is logged in.

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from core.permissions import IsAdminOrInstaller, IsAnyRole
from core.mixins import TenantFilterMixin

from .models import Customer, Site, Device
from .serializers import (
    CustomerSerializer,
    CustomerListSerializer,
    SiteSerializer,
    SiteListSerializer,
    DeviceSerializer,
)


class CustomerListView(TenantFilterMixin, APIView):
    """
    GET /api/v1/customers/
    Returns list of customers the logged in user can see.
    Uses lightweight serializer — no nested sites.
    """
    permission_classes = [IsAdminOrInstaller]

    def get(self, request):
        customers  = self.get_filtered_customers()
        serializer = CustomerListSerializer(customers, many=True)
        return Response(serializer.data)


class CustomerDetailView(TenantFilterMixin, APIView):
    """
    GET /api/v1/customers/{id}/
    Returns a single customer with all their sites and devices nested.
    """
    permission_classes = [IsAdminOrInstaller]

    def get(self, request, pk):
        customers = self.get_filtered_customers()

        try:
            # Only fetch from the already filtered queryset
            # so an installer cant access another installers customer
            # by guessing the ID
            customer   = customers.get(pk=pk)
            serializer = CustomerSerializer(customer)
            return Response(serializer.data)
        except Customer.DoesNotExist:
            return Response(
                {'detail': 'Customer not found'},
                status=status.HTTP_404_NOT_FOUND
            )


class SiteListView(TenantFilterMixin, APIView):
    """
    GET /api/v1/sites/
    Returns list of sites the logged in user can see.
    Supports optional filtering by customer:
    GET /api/v1/sites/?customer=1
    """
    permission_classes = [IsAnyRole]

    def get(self, request):
        sites = self.get_filtered_sites()

        # Optional filter by customer id from query param
        customer_id = request.query_params.get('customer')
        if customer_id:
            sites = sites.filter(customer_id=customer_id)

        serializer = SiteListSerializer(sites, many=True)
        return Response(serializer.data)


class SiteDetailView(TenantFilterMixin, APIView):
    """
    GET /api/v1/sites/{id}/
    Returns a single site with all its devices nested.
    """
    permission_classes = [IsAnyRole]

    def get(self, request, pk):
        sites = self.get_filtered_sites()

        try:
            site       = sites.get(pk=pk)
            serializer = SiteSerializer(site)
            return Response(serializer.data)
        except Site.DoesNotExist:
            return Response(
                {'detail': 'Site not found'},
                status=status.HTTP_404_NOT_FOUND
            )


class DeviceListView(TenantFilterMixin, APIView):
    """
    GET /api/v1/devices/
    Returns devices. Almost always filtered by site:
    GET /api/v1/devices/?site=1
    """
    permission_classes = [IsAnyRole]

    def get(self, request):
        devices = self.get_filtered_devices()

        # Optional filter by site id from query param
        site_id = request.query_params.get('site')
        if site_id:
            devices = devices.filter(site_id=site_id)

        serializer = DeviceSerializer(devices, many=True)
        return Response(serializer.data)


class DeviceDetailView(TenantFilterMixin, APIView):
    """
    GET /api/v1/devices/{id}/
    Returns a single device detail.
    """
    permission_classes = [IsAnyRole]

    def get(self, request, pk):
        devices = self.get_filtered_devices()

        try:
            device     = devices.get(pk=pk)
            serializer = DeviceSerializer(device)
            return Response(serializer.data)
        except Device.DoesNotExist:
            return Response(
                {'detail': 'Device not found'},
                status=status.HTTP_404_NOT_FOUND
            )