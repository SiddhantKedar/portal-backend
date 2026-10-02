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

    SITE_USER → sees only assigned site (+ their substation) and their devices
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
            # The customer that owns this user's sites (one customer by design).
            return Customer.objects.filter(sites__in=user.sites.all()).distinct()

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
            # Assigned sites + their substation children (parent_site → an
            # assigned site), so linked-substation meter overviews stay visible.
            site_ids = user.sites.values('pk')
            return Site.objects.filter(
                Q(pk__in=site_ids) | Q(parent_site_id__in=site_ids)
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
            site_ids = user.sites.values('pk')
            return Device.objects.filter(
                Q(site_id__in=site_ids) | Q(site__parent_site_id__in=site_ids)
            )

        return Device.objects.none()