"""
WSGI config for remoteable project.
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "remoteable.settings")

application = get_wsgi_application()
