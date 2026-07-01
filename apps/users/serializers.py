# apps/users/serializers.py
# Serializers control what data goes in and out of our API
# Think of them as the shape of the data the frontend receives

from rest_framework import serializers
from .models import User


class UserSerializer(serializers.ModelSerializer):
    """
    Returns safe user data to the frontend.
    Never expose password or internal fields.
    """
    full_name   = serializers.CharField(read_only=True)
    installer_name = serializers.SerializerMethodField()
    customer_id    = serializers.SerializerMethodField()    
    customer_name  = serializers.SerializerMethodField()

    class Meta:
        model  = User
        fields = (
            'id',
            'email',
            'first_name',
            'last_name',
            'full_name',
            'role',
            'installer',
            'installer_name',
            'customer_id',
            'customer_name',
            'is_active',
        )
        read_only_fields = fields   # this endpoint is read only, no editing here

    def get_installer_name(self, obj):
        # Return installer company name if user belongs to one
        if obj.installer:
            return obj.installer.name
        return None

    def get_customer_id(self, obj):     
        if obj.customer:
            return obj.customer.id
        return None

    def get_customer_name(self, obj):   
        if obj.customer:
            return obj.customer.name
        return None


class LoginSerializer(serializers.Serializer):
    """
    Validates login input - just email and password.
    """
    email    = serializers.EmailField()
    password = serializers.CharField(write_only=True)