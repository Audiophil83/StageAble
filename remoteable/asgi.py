"""
ASGI config for remoteable project.
"""

import os

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from django.conf import settings
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "remoteable.settings")

django_asgi_app = get_asgi_application()

# Use the staticfiles handler in DEBUG mode so Daphne serves static files
if settings.DEBUG:
    from django.contrib.staticfiles.handlers import ASGIStaticFilesHandler

    django_asgi_app = ASGIStaticFilesHandler(django_asgi_app)

from engine.routing import websocket_urlpatterns  # noqa: E402
from engine.startup import auto_start_engine  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": AuthMiddlewareStack(URLRouter(websocket_urlpatterns)),
    }
)

# Auto-start the engine when the ASGI server boots
auto_start_engine()
