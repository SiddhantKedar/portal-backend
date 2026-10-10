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
        ADMIN     = 'ADMIN',     'Admin'
        INSTALLER = 'INSTALLER', 'Installer'
        CUSTOMER  = 'CUSTOMER',  'Customer'
        SITE_USER = 'SITE_USER', 'Site User'

    # Core fields
    email      = models.EmailField(unique=True)
    first_name = models.CharField(max_length=150)
    last_name  = models.CharField(max_length=150)
    whatsapp_number = models.CharField(
        max_length=15, null=True, blank=True,
        help_text="WhatsApp number with country code, no '+', e.g. 918424882274. "
                "Null = no WhatsApp delivery.",
    )

    # Optional login number: 10 digits, no country code. A user can log in with
    # this OR their email. Kept separate from whatsapp_number on purpose, because
    # filling that one switches on WhatsApp delivery.
    phone_number = models.CharField(
        max_length=10, unique=True, null=True, blank=True,
        help_text="10-digit mobile number the user can log in with instead of email. "
                  "Leave empty for email-only login.",
    )
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

    # LEGACY — single site, read ONLY by the daily WhatsApp job on the VM.
    # Portal code uses `sites`. Dropped once the WhatsApp runs are stopped.
    site = models.ForeignKey(
        'sites.Site',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='users'
    )

    # Sites a SITE_USER can see — one or more, all under ONE customer
    # (enforced in the admin form; M2M can't be validated in clean()).
    sites = models.ManyToManyField(
       'sites.Site',
       blank=True,
       related_name='site_users',
       limit_choices_to={'site_type': 'GENERATION'},
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

    @property
    def is_site_user(self):
        return self.role == self.Role.SITE_USER
    
    def clean(self):
        super().clean()
        # Empty is stored as NULL, never '': the field is unique, and two users
        # with '' would collide. NULLs do not.
        self.phone_number = (self.phone_number or '').strip() or None
        if self.phone_number and not (
            self.phone_number.isascii() and self.phone_number.isdigit()
            and len(self.phone_number) == 10
        ):
            raise ValidationError('Phone number must be exactly 10 digits.')
        # `sites` (M2M) is validated in the admin form (SitesValidationMixin) —
        # the model can't see the form's selection.
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
        elif self.role == self.Role.SITE_USER:
            if self.installer_id or self.customer_id:
                raise ValidationError('Site users must not have an installer or customer assigned.')

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)