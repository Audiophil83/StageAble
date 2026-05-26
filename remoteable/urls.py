"""
URL configuration for remoteable project.
"""

from pathlib import Path

from django.conf import settings
from django.contrib import admin
from django.http import FileResponse
from django.urls import include, path
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_control
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.generic import TemplateView

STATIC_DIR = Path(settings.BASE_DIR) / "static"


@cache_control(max_age=86400, public=True)
def serve_icon(request, filename: str, content_type: str):
    return FileResponse((STATIC_DIR / filename).open("rb"), content_type=content_type)


def favicon(request):
    return serve_icon(request, "favicon.ico", "image/x-icon")


def apple_touch_icon(request):
    return serve_icon(request, "apple-touch-icon.png", "image/png")


@method_decorator(ensure_csrf_cookie, name="dispatch")
class IndexView(TemplateView):
    template_name = "index.html"


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("engine.urls")),
    path("favicon.ico", favicon, name="favicon"),
    path("apple-touch-icon.png", apple_touch_icon, name="apple-touch-icon"),
    path("", IndexView.as_view(), name="home"),
]
