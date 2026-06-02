"""
REST API views for transport control, state queries, and setlist management.
"""

from django.views.decorators.csrf import csrf_exempt
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view
from rest_framework.response import Response

from .models import AppSettings, Setlist
from .serializers import AppSettingsSerializer, SetlistCreateSerializer, SetlistSerializer
from .state import engine_state


# ── Engine state & transport ──────────────────────────────────────────


@api_view(["GET"])
def engine_status(request):
    """Return the current engine state snapshot."""
    return Response(engine_state.snapshot())


@api_view(["POST"])
def transport_play(request):
    from .runtime import get_engine

    get_engine().cmd_play()
    return Response({"status": "ok"})


@api_view(["POST"])
def transport_stop(request):
    from .runtime import get_engine

    get_engine().cmd_stop()
    return Response({"status": "ok"})


@api_view(["POST"])
def transport_seek(request):
    beat = request.data.get("beat")
    if beat is None:
        return Response(
            {"error": "Missing 'beat' parameter"}, status=status.HTTP_400_BAD_REQUEST
        )
    from .runtime import get_engine

    get_engine().cmd_seek(float(beat))
    return Response({"status": "ok", "beat": float(beat)})


@api_view(["POST"])
def jump_to_song(request):
    index = request.data.get("index")
    setlist_index = request.data.get("setlist_index")
    if index is None and setlist_index is None:
        return Response(
            {"error": "Missing 'index' or 'setlist_index' parameter"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    from .runtime import get_engine

    engine = get_engine()
    if setlist_index is not None:
        engine.cmd_jump_to_setlist_index(int(setlist_index))
        return Response({"status": "ok", "setlist_index": int(setlist_index)})

    engine.cmd_jump_to_song(int(index))
    return Response({"status": "ok", "index": int(index)})


@api_view(["POST"])
def jump_to_section(request):
    start_beat = request.data.get("start_beat")
    if start_beat is None:
        return Response(
            {"error": "Missing 'start_beat' parameter"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    from .runtime import get_engine

    get_engine().cmd_jump_to_section(float(start_beat))
    return Response({"status": "ok", "start_beat": float(start_beat)})


@csrf_exempt
@api_view(["POST"])
def rescan(request):
    from .runtime import get_engine

    get_engine().cmd_rescan()
    return Response({"status": "ok"})


# ── Mixer ─────────────────────────────────────────────────────────────


@api_view(["GET"])
def mixer_tracks(request):
    """Return [MIX] tracks; refresh mute from Ableton when connected."""
    from .state import ConnectionStatus

    from .runtime import get_engine

    engine = get_engine()
    live = engine_state.connection_status == ConnectionStatus.CONNECTED
    tracks = engine.get_mixer_tracks(live=live)
    if not tracks and not live:
        return Response(
            {"error": "No cached mixer tracks — rescan the project from Ableton"},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return Response(tracks)


@api_view(["POST"])
def mixer_track_mute(request, track_index: int):
    """Mute or unmute a [MIX] track."""
    muted = request.data.get("muted")
    if muted is None:
        return Response(
            {"error": "Missing 'muted' parameter"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    from .runtime import get_engine

    try:
        engine = get_engine()
        engine.cmd_set_track_mute(int(track_index), bool(muted))
    except ValueError as e:
        return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    return Response({"status": "ok", "tracks": engine.get_mixer_tracks(live=False)})


# ── Song / section data ──────────────────────────────────────────────


@api_view(["GET"])
def song_list(request):
    """Return all songs from the timeline."""
    return Response(engine_state.get_setlist())


@api_view(["GET"])
def section_list(request):
    """Return all sections from the timeline."""
    return Response(engine_state.get_sections())


@api_view(["GET"])
def chord_list(request):
    """Return all chords from the timeline."""
    return Response(engine_state.get_chords())


@api_view(["GET"])
def lyric_list(request):
    """Return all lyrics from the timeline."""
    return Response(engine_state.get_lyrics())


# ── Setlist CRUD ──────────────────────────────────────────────────────


@api_view(["GET", "PATCH"])
def app_settings(request):
    """Read or update engine configuration stored in the database."""
    from .config import get_app_settings_model

    settings_obj = get_app_settings_model()

    if request.method == "GET":
        return Response(AppSettingsSerializer(settings_obj).data)

    serializer = AppSettingsSerializer(
        settings_obj, data=request.data, partial=True
    )
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    serializer.save()

    from .runtime import get_engine

    get_engine().apply_settings()

    return Response(serializer.data)


class SetlistViewSet(viewsets.ModelViewSet):
    queryset = Setlist.objects.all()

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return SetlistCreateSerializer
        return SetlistSerializer

    def perform_create(self, serializer):
        setlist = serializer.save()
        if setlist.is_active:
            self._reload_active_setlist()

    def perform_update(self, serializer):
        was_active = serializer.instance.is_active
        setlist = serializer.save()
        if was_active or setlist.is_active:
            self._reload_active_setlist()

    def perform_destroy(self, instance):
        was_active = instance.is_active
        instance.delete()
        if was_active:
            self._reload_active_setlist()

    def _reload_active_setlist(self) -> None:
        from .setlist_loader import reload_engine_active_setlist

        reload_engine_active_setlist()

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        """Mark this setlist as active (deactivates others)."""
        setlist = self.get_object()
        setlist.is_active = True
        setlist.save()
        self._reload_active_setlist()
        return Response(SetlistSerializer(setlist).data)
