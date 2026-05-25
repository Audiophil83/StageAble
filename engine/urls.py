"""REST API URL routing."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register(r"setlists", views.SetlistViewSet, basename="setlist")

urlpatterns = [
    # Engine state
    path("status/", views.engine_status, name="engine-status"),
    # Transport
    path("transport/play/", views.transport_play, name="transport-play"),
    path("transport/stop/", views.transport_stop, name="transport-stop"),
    path("transport/seek/", views.transport_seek, name="transport-seek"),
    path("transport/jump-to-song/", views.jump_to_song, name="jump-to-song"),
    path(
        "transport/jump-to-section/",
        views.jump_to_section,
        name="jump-to-section",
    ),
    # Arrangement
    path("songs/", views.song_list, name="song-list"),
    path("sections/", views.section_list, name="section-list"),
    path("rescan/", views.rescan, name="rescan"),
    # Setlist CRUD
    path("", include(router.urls)),
]
