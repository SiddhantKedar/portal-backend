# apps/users/models.py

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.core.exceptions import ValidationError


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('Email is required')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('role', 'ADMIN')
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):

    class Role(models.TextChoices):
        ADMIN    = 'ADMIN',    'Admin'
        INSTALLER = 'INSTALLER', 'Installer'
        CUSTOMER = 'CUSTOMER', 'Customer'

    # Core fields
    email      = models.EmailField(unique=True)
    first_name = models.CharField(max_length=150)
    last_name  = models.CharField(max_length=150)
    role       = models.CharField(max_length=20, choices=Role.choices)

    # Link to installer company — only set if role is INSTALLER or CUSTOMER
    # We use a string reference 'tenants.Installer' to avoid circular imports
    installer  = models.ForeignKey(
        'tenants.Installer',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='users'
    )

    # Link to customer — set if role is CUSTOMER
    customer = models.ForeignKey(
        'sites.Customer',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='users'
    )

    # Standard Django fields
    is_active  = models.BooleanField(default=True)
    is_staff   = models.BooleanField(default=False)
    date_joined = models.DateTimeField(auto_now_add=True)

    objects = UserManager()

    USERNAME_FIELD  = 'email'       # login with email not username
    REQUIRED_FIELDS = ['first_name', 'last_name', 'role']

    class Meta:
        db_table = 'users'
        verbose_name = 'User'
        verbose_name_plural = 'Users'

    def __str__(self):
        return f'{self.email} ({self.role})'

    @property
    def full_name(self):
        return f'{self.first_name} {self.last_name}'

    # Helper properties to check role cleanly anywhere in the codebase
    @property
    def is_admin(self):
        return self.role == self.Role.ADMIN

    @property
    def is_installer(self):
        return self.role == self.Role.INSTALLER

    @property
    def is_customer(self):
        return self.role == self.Role.CUSTOMER
    
    def clean(self):
        super().clean()
        if self.role == self.Role.ADMIN:
            if self.installer_id or self.customer_id:
                raise ValidationError('Admin users must not have an installer or customer assigned.')
        elif self.role == self.Role.INSTALLER:
            if not self.installer_id:
                raise ValidationError('Installer users must have an installer assigned.')
            if self.customer_id:
                raise ValidationError('Installer users must not have a customer assigned.')
        elif self.role == self.Role.CUSTOMER:
            if not self.customer_id:
                raise ValidationError('Customer users must have a customer assigned.')
            if self.installer_id:
                raise ValidationError('Customer users must not have an installer assigned.')

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)