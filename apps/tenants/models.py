# apps/tenants/models.py

from django.db import models


class Installer(models.Model):
    name        = models.CharField(max_length=255)
    email       = models.EmailField(unique=True)
    phone       = models.CharField(max_length=20, blank=True)
    address     = models.TextField(blank=True)
    is_active   = models.BooleanField(default=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'installers'

    def __str__(self):
        return self.name