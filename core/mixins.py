# core/mixins.py
# TenantFilterMixin automatically filters querysets based on who is logged in.
from django.db.models import Q
from apps.sites.models import Customer, Site, Device


class TenantFilterMixin:
    """
    Filters data based on the logged in user's role.

    ADMIN      → sees everything, no filter applied
    INSTALLER  → sees only sites/devices THEY are assigned to
                 (customers are derived through those sites)
    CUSTOMER   → sees only their own sites/devices

    SITE_USER → sees only one assigned site (+ its substation) and its devices
    """

    def get_filtered_customers(self):
        """
        Returns customers the current user is allowed to see.
        """
        user = self.request.user

        if user.role == 'ADMIN':
            return Customer.objects.all()

        if user.role == 'INSTALLER':
            # A customer "belongs" to an installer if at least one
            # of their sites is managed by that installer.
            return Customer.objects.filter(
                sites__installer=user.installer
            ).distinct()

        if user.role == 'SITE_USER':
            if not user.site_id:
                return Customer.objects.none()
            # The customer that owns this user's single site.
            return Customer.objects.filter(sites__id=user.site_id).distinct()

        # Customer role cannot list all customers
        return Customer.objects.none()

    def get_filtered_sites(self):
        """
        Returns sites the current user is allowed to see.
        """
        user = self.request.user

        if user.role == 'ADMIN':
            return Site.objects.all()

        if user.role == 'INSTALLER':
            # Direct filter now - installer FK lives on Site itself
            return Site.objects.filter(installer=user.installer)

        if user.role == 'CUSTOMER':
            return Site.objects.filter(customer=user.customer)

        if user.role == 'SITE_USER':
            if not user.site_id:
                return Site.objects.none()
            # Assigned site + its substation child (parent_site → assigned site),
            # so the linked-substation meter overview stays visible.
            return Site.objects.filter(
                Q(pk=user.site_id) | Q(parent_site_id=user.site_id)
            )

        return Site.objects.none()

    def get_filtered_devices(self):
        """
        Returns devices the current user is allowed to see.
        """
        user = self.request.user

        if user.role == 'ADMIN':
            return Device.objects.all()

        if user.role == 'INSTALLER':
            return Device.objects.filter(site__installer=user.installer)

        if user.role == 'CUSTOMER':
            return Device.objects.filter(site__customer=user.customer)

        if user.role == 'SITE_USER':
            if not user.site_id:
                return Device.objects.none()
            return Device.objects.filter(
                Q(site_id=user.site_id) | Q(site__parent_site_id=user.site_id)
            )

        return Device.objects.none()