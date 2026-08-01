# core/permissions.py
# Custom permission classes for our three roles.
# These are used as decorators on API views to control access.


from rest_framework.permissions import BasePermission


class IsAdminUser(BasePermission):
    """
    Only allows access to users with ADMIN role.
    Used for endpoints only your team should access.
    eg: creating installers, viewing all data across all tenants
    """
    def has_permission(self, request, view):
        return (
            request.user.is_authenticated and
            request.user.role == 'ADMIN'
        )


class IsInstallerUser(BasePermission):
    """
    Only allows access to users with INSTALLER role.
    eg: viewing their own customers, their own sites
    """
    def has_permission(self, request, view):
        return (
            request.user.is_authenticated and
            request.user.role == 'INSTALLER'
        )


class IsCustomerUser(BasePermission):
    """
    Only allows access to users with CUSTOMER role.
    eg: viewing their own sites and devices only
    """
    def has_permission(self, request, view):
        return (
            request.user.is_authenticated and
            request.user.role == 'CUSTOMER'
        )


class IsSiteUser(BasePermission):
    """
    Only allows access to users with SITE_USER role.
    eg: an operator scoped to a single site and its substation.
    """
    def has_permission(self, request, view):
        return (
            request.user.is_authenticated and
            request.user.role == 'SITE_USER'
        )


class IsAdminOrInstaller(BasePermission):
    """
    Allows access to both ADMIN and INSTALLER roles.
    Most dashboard endpoints will use this —
    admins see everything, installers see their slice.
    The tenant filter (Part 2) handles what each actually sees.
    """
    def has_permission(self, request, view):
        return (
            request.user.is_authenticated and
            request.user.role in ('ADMIN', 'INSTALLER')
        )


class IsAnyRole(BasePermission):
    """
    Allows any authenticated user regardless of role.
    Used for endpoints all three roles can access
    eg: viewing dashboard data for sites they own
    The tenant filter handles what each user actually sees.
    """
    def has_permission(self, request, view):
        return (
            request.user.is_authenticated and
            request.user.role in ('ADMIN', 'INSTALLER', 'CUSTOMER',  'SITE_USER')
        )