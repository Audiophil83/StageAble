"""
REST API views for transport control, state queries, and setlist management.
"""

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
    if index is None:
        return Response(
            {"error": "Missing 'index' parameter"}, status=status.HTTP_400_BAD_REQUEST
        )
    from .runtime import get_engine

    get_engine().cmd_jump_to_song(int(index))
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


@api_view(["POST"])
def rescan(request):
    from .runtime import get_engine

    get_engine().cmd_rescan()
    return Response({"status": "ok"})


# ── Song / section data ──────────────────────────────────────────────


@api_view(["GET"])
def song_list(request):
    """Return all songs from the timeline."""
    return Response(engine_state.get_setlist())


@api_view(["GET"])
def section_list(request):
    """Return all sections from the timeline."""
    return Response(engine_state.get_sections())


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

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        """Mark this setlist as active (deactivates others)."""
        setlist = self.get_object()
        setlist.is_active = True
        setlist.save()
        return Response(SetlistSerializer(setlist).data)
