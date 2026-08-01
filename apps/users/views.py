# apps/users/views.py

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import authenticate

from .serializers import UserSerializer, LoginSerializer
from apps.sites.models import Site
from apps.sites.serializers import SiteListSerializer


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)

        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        email    = serializer.validated_data['email']
        password = serializer.validated_data['password']

        user = authenticate(request, username=email, password=password)

        if not user:
            return Response(
                {'detail': 'Invalid email or password'},
                status=status.HTTP_401_UNAUTHORIZED
            )

        if not user.is_active:
            return Response(
                {'detail': 'Your account has been deactivated'},
                status=status.HTTP_403_FORBIDDEN
            )

        refresh = RefreshToken.for_user(user)

        # Resolve GENERATION sites this user can see, same role logic as
        # TenantFilterMixin.get_filtered_sites — inlined here since this is
        # a one-time call at login, not worth wiring the mixin into a
        # non-DRF-viewset APIView for this alone.
        if user.role == 'ADMIN':
            sites = Site.objects.filter(site_type='GENERATION')
        elif user.role == 'INSTALLER':
            sites = Site.objects.filter(installer=user.installer, site_type='GENERATION')
        elif user.role == 'CUSTOMER':
            sites = Site.objects.filter(customer=user.customer, site_type='GENERATION')
        elif user.role == 'SITE_USER':
            sites = Site.objects.filter(pk=user.site_id, site_type='GENERATION')
        else:
            sites = Site.objects.none()

        return Response({
            'access':  str(refresh.access_token),
            'refresh': str(refresh),
            'user':    UserSerializer(user).data,
            'sites':   SiteListSerializer(sites, many=True).data,
        }, status=status.HTTP_200_OK)

class LogoutView(APIView):
    """
    Blacklists the refresh token so it can't be used again.
    Frontend should also delete tokens from its storage.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            refresh_token = request.data.get('refresh')
            if not refresh_token:
                return Response(
                    {'detail': 'Refresh token required'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            token = RefreshToken(refresh_token)
            token.blacklist()
            return Response(
                {'detail': 'Logged out successfully'},
                status=status.HTTP_200_OK
            )
        except Exception:
            return Response(
                {'detail': 'Invalid token'},
                status=status.HTTP_400_BAD_REQUEST
            )


class MeView(APIView):
    """
    Returns the currently logged in user's details.
    Frontend calls this on app load to know who is logged in and what role they have.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data)