"""REST API serializers."""

from rest_framework import serializers

from .models import (
    AppSettings,
    ControlDevice,
    ControlMapping,
    MixerPreset,
    ProjectCache,
    Setlist,
    SetlistEntry,
    X32Operation,
    X32Snapshot,
)
from .actions import ACTIONS
from .devices.base import trigger_key


class AppSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = AppSettings
        fields = [
            "ableton_osc_host",
            "x32_enabled",
            "x32_host",
            "sliding_animation_enabled",
            "sliding_animation_duration_ms",
            "updated_at",
        ]
        read_only_fields = ["updated_at"]

    def validate(self, attrs):
        enabled = attrs.get(
            "x32_enabled", getattr(self.instance, "x32_enabled", False)
        )
        host = attrs.get("x32_host", getattr(self.instance, "x32_host", ""))
        if enabled and not str(host).strip():
            raise serializers.ValidationError(
                {"x32_host": "Enter the X32 IP address before enabling the connection."}
            )
        return attrs


class ProjectCacheSerializer(serializers.ModelSerializer):
    display_name = serializers.CharField(read_only=True)
    setlist_count = serializers.IntegerField(read_only=True)
    mixer_preset_count = serializers.IntegerField(read_only=True)
    is_active = serializers.SerializerMethodField()

    class Meta:
        model = ProjectCache
        fields = [
            "id",
            "display_name",
            "name",
            "file_path",
            "identity",
            "scanned_at",
            "is_valid",
            "updated_at",
            "setlist_count",
            "mixer_preset_count",
            "is_active",
        ]
        read_only_fields = [
            "identity",
            "scanned_at",
            "is_valid",
            "updated_at",
        ]

    def get_is_active(self, obj) -> bool:
        active_id = self.context.get("active_project_id")
        return active_id is not None and obj.id == active_id


class ProjectRenameSerializer(serializers.Serializer):
    file_path = serializers.CharField(max_length=1024)
    name = serializers.CharField(
        max_length=500, required=False, allow_blank=True, default=""
    )


class MixerPresetSerializer(serializers.ModelSerializer):
    class Meta:
        model = MixerPreset
        fields = ["id", "name", "tracks", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]


class X32SnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = X32Snapshot
        fields = ["id", "name", "keyword", "coverage", "created_at"]
        read_only_fields = ["coverage", "created_at"]


class X32OperationSerializer(serializers.ModelSerializer):
    class Meta:
        model = X32Operation
        fields = [
            "id", "name", "apply_keyword", "rollback_keyword", "changes",
            "created_at",
        ]
        read_only_fields = ["changes", "created_at"]


class SetlistEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = SetlistEntry
        fields = ["id", "song_name", "order", "auto_cue_next", "gap_seconds", "notes"]


class SetlistSerializer(serializers.ModelSerializer):
    entries = SetlistEntrySerializer(many=True, read_only=True)

    class Meta:
        model = Setlist
        fields = ["id", "name", "is_active", "created_at", "updated_at", "entries"]
        read_only_fields = ["created_at", "updated_at"]


class SetlistCreateSerializer(serializers.ModelSerializer):
    entries = SetlistEntrySerializer(many=True, required=False)

    class Meta:
        model = Setlist
        fields = ["id", "name", "is_active", "entries"]

    def create(self, validated_data):
        entries_data = validated_data.pop("entries", [])
        setlist = Setlist.objects.create(**validated_data)
        for i, entry_data in enumerate(entries_data):
            entry_data.setdefault("order", i)
            SetlistEntry.objects.create(setlist=setlist, **entry_data)
        return setlist

    def update(self, instance, validated_data):
        entries_data = validated_data.pop("entries", None)
        instance.name = validated_data.get("name", instance.name)
        instance.is_active = validated_data.get("is_active", instance.is_active)
        instance.save()

        if entries_data is not None:
            instance.entries.all().delete()
            for i, entry_data in enumerate(entries_data):
                entry_data.setdefault("order", i)
                SetlistEntry.objects.create(setlist=instance, **entry_data)

        return instance


class ControlMappingSerializer(serializers.ModelSerializer):
    action_label = serializers.SerializerMethodField()

    class Meta:
        model = ControlMapping
        fields = ["id", "device", "trigger", "action", "action_label", "enabled", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at", "action_label"]

    def get_action_label(self, obj):
        return ACTIONS.get(obj.action, obj.action)

    def validate_action(self, value):
        if value not in ACTIONS:
            raise serializers.ValidationError("Unknown action")
        return value

    def validate(self, attrs):
        device = attrs.get("device", getattr(self.instance, "device", None))
        trigger = attrs.get("trigger", getattr(self.instance, "trigger", None))
        if device and trigger is not None:
            duplicate = ControlMapping.objects.filter(
                device=device, trigger_key=trigger_key(trigger)
            )
            if self.instance:
                duplicate = duplicate.exclude(pk=self.instance.pk)
            if duplicate.exists():
                raise serializers.ValidationError(
                    {"trigger": "This input is already mapped for the device."}
                )
        return attrs

    def create(self, validated_data):
        validated_data["trigger_key"] = trigger_key(validated_data["trigger"])
        return super().create(validated_data)

    def update(self, instance, validated_data):
        if "trigger" in validated_data:
            validated_data["trigger_key"] = trigger_key(validated_data["trigger"])
        return super().update(instance, validated_data)


class ControlDeviceSerializer(serializers.ModelSerializer):
    mappings = ControlMappingSerializer(many=True, read_only=True)

    class Meta:
        model = ControlDevice
        fields = ["id", "adapter", "identifier", "name", "enabled", "config", "mappings", "created_at", "updated_at"]
        read_only_fields = ["adapter", "identifier", "config", "created_at", "updated_at"]
