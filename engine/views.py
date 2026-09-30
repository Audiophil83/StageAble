"""
REST API views for transport control, state queries, and setlist management.
"""

from django.views.decorators.csrf import csrf_exempt
from django.db.models import Count
from rest_framework import mixins, permissions, status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.decorators import action, api_view
from rest_framework.response import Response

from .models import AppSettings, ControlDevice, ControlMapping, MixerPreset, ProjectCache, Setlist
from .serializers import (
    AppSettingsSerializer,
    ControlDeviceSerializer,
    ControlMappingSerializer,
    MixerPresetSerializer,
    ProjectCacheSerializer,
    ProjectRenameSerializer,
    SetlistCreateSerializer,
    SetlistSerializer,
)
from .actions import ACTIONS
from .state import engine_state


def _active_project_id() -> int | None:
    project = engine_state.active_project
    if project:
        return project.get("id")
    return None


def _require_active_project_id() -> int | None:
    project_id = _active_project_id()
    if project_id is None:
        from .project_cache import resolve_project_identity_from_settings, get_or_create_project_record

        identity = resolve_project_identity_from_settings()
        if identity:
            project = get_or_create_project_record(identity=identity)
            return project.id
    return project_id


class IsLoopback(permissions.BasePermission):
    """Device configuration can only be changed from the server machine."""

    def has_permission(self, request, view):
        address = request.META.get("REMOTE_ADDR", "")
        return address in {"127.0.0.1", "::1"} or address.startswith("127.")


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
def transport_toggle(request):
    from .runtime import get_engine

    get_engine().actions.dispatch("transport.toggle_play")
    return Response({"status": "ok"})


@api_view(["POST"])
def song_previous(request):
    from .runtime import get_engine

    get_engine().actions.dispatch("song.previous")
    return Response({"status": "ok"})


@api_view(["POST"])
def song_next(request):
    from .runtime import get_engine

    get_engine().actions.dispatch("song.next")
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


@api_view(["POST"])
def rehearse_play(request):
    start_beat = request.data.get("start_beat")
    if start_beat is None:
        return Response(
            {"error": "Missing 'start_beat' parameter"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    from .runtime import get_engine

    get_engine().cmd_rehearse_play(float(start_beat))
    return Response({"status": "ok", "start_beat": float(start_beat)})


@api_view(["POST"])
def rehearse_loop(request):
    start_beats = request.data.get("start_beats")
    if not start_beats:
        return Response(
            {"error": "Missing 'start_beats' parameter"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    from .runtime import get_engine

    try:
        get_engine().cmd_rehearse_loop([float(b) for b in start_beats])
    except ValueError as e:
        return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
    return Response({"status": "ok", "start_beats": [float(b) for b in start_beats]})


@api_view(["POST"])
def rehearse_stop(request):
    from .runtime import get_engine

    get_engine().cmd_rehearse_stop()
    return Response({"status": "ok"})


@api_view(["POST"])
def rehearse_exit(request):
    from .runtime import get_engine

    get_engine().cmd_rehearse_exit()
    return Response({"status": "ok"})


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


@api_view(["GET", "POST"])
def keep_awake(request):
    """Enable/disable macOS system keep-awake (caffeinate) for local server use."""
    from . import keep_awake as keep_awake_service

    if request.method == "GET":
        return Response(keep_awake_service.status())

    enabled = request.data.get("enabled")
    if enabled is None:
        return Response(
            {"error": "Missing 'enabled' parameter"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if enabled:
        return Response(keep_awake_service.enable())
    return Response(keep_awake_service.disable())


class SetlistViewSet(viewsets.ModelViewSet):
    serializer_class = SetlistSerializer

    def get_queryset(self):
        project_id = _active_project_id()
        qs = Setlist.objects.all()
        if project_id is not None:
            qs = qs.filter(project_id=project_id)
        return qs

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return SetlistCreateSerializer
        return SetlistSerializer

    def perform_create(self, serializer):
        project_id = _require_active_project_id()
        if project_id is None:
            raise ValidationError(
                "No active project — connect to Ableton or rescan first."
            )
        setlist = serializer.save(project_id=project_id)
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


class ProjectViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = ProjectCacheSerializer

    def get_queryset(self):
        return ProjectCache.objects.annotate(
            setlist_count=Count("setlists", distinct=True),
            mixer_preset_count=Count("mixer_presets", distinct=True),
        ).order_by("-updated_at")

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["active_project_id"] = _active_project_id()
        return context

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    def retrieve(self, request, *args, **kwargs):
        project = self.get_object()
        serializer = self.get_serializer(project)
        return Response(serializer.data)

    def perform_destroy(self, instance):
        project_id = instance.id
        identity = instance.identity

        settings = AppSettings.objects.filter(pk=1).first()
        if settings and settings.last_active_project_id == project_id:
            settings.last_active_project = None
            settings.save(update_fields=["last_active_project", "updated_at"])

        instance.delete()

        from .runtime import get_engine

        # Suppress auto-recreation while Ableton still has this Live set open.
        get_engine().forget_stored_project(identity)

    @action(detail=True, methods=["post"])
    def rename(self, request, pk=None):
        """Update stored path/identity when the .als file was moved or renamed."""
        project = self.get_object()
        serializer = ProjectRenameSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        file_path = serializer.validated_data["file_path"].strip()
        name = serializer.validated_data.get("name", "").strip()
        if not file_path:
            raise ValidationError({"file_path": "Path is required."})

        from .project_cache import (
            compute_project_identity,
            project_to_state_dict,
            relocate_project_record,
        )

        new_identity = compute_project_identity(file_path, name)
        if (
            new_identity != project.identity
            and ProjectCache.objects.filter(identity=new_identity)
            .exclude(pk=project.pk)
            .exists()
        ):
            raise ValidationError(
                {"file_path": "Another stored project already uses this path."}
            )

        if not name:
            import os

            name = os.path.basename(file_path)

        relocated = relocate_project_record(
            project,
            identity=new_identity,
            name=name,
            file_path=file_path,
        )

        if (
            engine_state.active_project is not None
            and engine_state.active_project.get("id") == project.id
        ):
            engine_state.update(active_project=project_to_state_dict(relocated))
            from .runtime import get_engine

            get_engine().notify_state_changed()

        data = ProjectCacheSerializer(
            relocated, context={"active_project_id": _active_project_id()}
        ).data
        return Response(data)


class MixerPresetViewSet(viewsets.ModelViewSet):
    serializer_class = MixerPresetSerializer

    def get_queryset(self):
        project_id = _active_project_id()
        qs = MixerPreset.objects.all()
        if project_id is not None:
            qs = qs.filter(project_id=project_id)
        return qs

    def perform_create(self, serializer):
        project_id = _require_active_project_id()
        if project_id is None:
            raise ValidationError(
                "No active project — connect to Ableton or rescan first."
            )
        serializer.save(project_id=project_id)

    @action(detail=True, methods=["post"])
    def apply(self, request, pk=None):
        """Apply this preset's mute states to Ableton Live."""
        preset = self.get_object()
        from .runtime import get_engine

        engine = get_engine()
        tracks = engine.cmd_apply_mixer_preset(preset.tracks)
        return Response({"status": "ok", "tracks": tracks})


def _device_manager():
    from .devices import DeviceManager
    from .runtime import get_engine

    engine = get_engine()
    if engine.device_manager is None:
        engine.device_manager = DeviceManager(engine)
        engine.device_manager.start()
    return engine.device_manager


class ControlDeviceViewSet(viewsets.ModelViewSet):
    serializer_class = ControlDeviceSerializer
    permission_classes = [IsLoopback]
    http_method_names = ["get", "patch", "delete", "post", "head", "options"]

    def get_queryset(self):
        return ControlDevice.objects.prefetch_related("mappings").all()

    def list(self, request, *args, **kwargs):
        return Response({"actions": ACTIONS, "devices": _device_manager().snapshot()})

    def partial_update(self, request, *args, **kwargs):
        response = super().partial_update(request, *args, **kwargs)
        _device_manager().refresh()
        return response

    def destroy(self, request, *args, **kwargs):
        """Clear saved mappings while leaving connected hardware discoverable."""
        device = self.get_object()
        device.mappings.all().delete()
        device.enabled = False
        device.save(update_fields=["enabled", "updated_at"])
        _device_manager().broadcast("devices_changed", {"devices": _device_manager().snapshot()})
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=["post"])
    def refresh(self, request):
        return Response({"actions": ACTIONS, "devices": _device_manager().refresh()})

    @action(detail=False, methods=["post"], url_path="pair-bluetooth")
    def pair_bluetooth(self, request):
        from .devices.macos_hid import MacBluetoothHidAdapter

        try:
            MacBluetoothHidAdapter.open_pairing()
        except RuntimeError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"status": "opened"})

    @action(detail=False, methods=["post"], url_path="open-device-permission")
    def open_device_permission(self, request):
        from .devices.macos_hid import MacBluetoothHidAdapter

        try:
            MacBluetoothHidAdapter.open_permission(request.data.get("kind", "input"))
        except RuntimeError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"status": "opened"})

    @action(detail=False, methods=["post"], url_path="broker-input")
    def broker_input(self, request):
        from .devices.base import InputEvent

        required = ("adapter", "identifier", "trigger")
        if any(field not in request.data for field in required):
            return Response({"error": "Invalid broker input"}, status=status.HTTP_400_BAD_REQUEST)
        _device_manager().handle_input(InputEvent(
            adapter=request.data["adapter"],
            identifier=request.data["identifier"],
            trigger=request.data["trigger"],
            pressed=bool(request.data.get("pressed", True)),
            value=request.data.get("value"),
        ))
        return Response({"status": "ok"})

    @action(detail=False, methods=["post"], url_path="broker-state")
    def broker_state(self, request):
        devices = request.data.get("devices", [])
        broker_status = request.data.get("status", {})
        if not isinstance(devices, list) or not isinstance(broker_status, dict):
            return Response({"error": "Invalid broker state"}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"devices": _device_manager().update_external(devices, broker_status)})

    @action(detail=True, methods=["post"])
    def learn(self, request, pk=None):
        action_name = request.data.get("action")
        try:
            session = _device_manager().start_learn(int(pk), action_name)
        except (ValueError, ControlDevice.DoesNotExist) as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(session)

    @action(detail=False, methods=["post"], url_path="cancel-learn")
    def cancel_learn(self, request):
        _device_manager().cancel_learn()
        return Response({"status": "cancelled"})


class ControlMappingViewSet(viewsets.ModelViewSet):
    queryset = ControlMapping.objects.select_related("device").all()
    serializer_class = ControlMappingSerializer
    permission_classes = [IsLoopback]
