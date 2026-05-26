"""
URL configuration for remoteable project.
"""

from django.contrib import admin
from django.urls import include, path
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.generic import TemplateView


@method_decorator(ensure_csrf_cookie, name="dispatch")
class IndexView(TemplateView):
    template_name = "index.html"


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("engine.urls")),
    path("", IndexView.as_view(), name="home"),
]
