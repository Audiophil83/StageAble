"""REST API serializers."""

from rest_framework import serializers

from .models import AppSettings, Setlist, SetlistEntry


class AppSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = AppSettings
        fields = [
            "ableton_osc_host",
            "sliding_animation_enabled",
            "sliding_animation_duration_ms",
            "updated_at",
        ]
        read_only_fields = ["updated_at"]


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
