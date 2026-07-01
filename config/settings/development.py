# config/settings/development.py

from .base import *

DEBUG = True

ALLOWED_HOSTS = ['localhost', '127.0.0.1']

CORS_ALLOWED_ORIGINS = [
    'http://localhost:5173',    # Vite default port
    'http://localhost:3000',
]

# In dev, also allow credentials with CORS
CORS_ALLOW_CREDENTIALS = True

# Print emails to console instead of sending
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'