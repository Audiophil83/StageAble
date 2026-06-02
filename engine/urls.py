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
    path("chords/", views.chord_list, name="chord-list"),
    path("lyrics/", views.lyric_list, name="lyric-list"),
    path("rescan/", views.rescan, name="rescan"),
    path("mixer/tracks/", views.mixer_tracks, name="mixer-tracks"),
    path(
        "mixer/tracks/<int:track_index>/mute/",
        views.mixer_track_mute,
        name="mixer-track-mute",
    ),
    path("settings/", views.app_settings, name="app-settings"),
    # Setlist CRUD
    path("", include(router.urls)),
]
