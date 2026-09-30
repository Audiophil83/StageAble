from django.contrib import admin

from .models import AppSettings, ControlDevice, ControlMapping, MixerPreset, ProjectCache, Setlist, SetlistEntry


class SetlistEntryInline(admin.TabularInline):
    model = SetlistEntry
    extra = 1


@admin.register(Setlist)
class SetlistAdmin(admin.ModelAdmin):
    list_display = ["name", "project", "is_active", "updated_at"]
    list_filter = ["project"]
    inlines = [SetlistEntryInline]


@admin.register(MixerPreset)
class MixerPresetAdmin(admin.ModelAdmin):
    list_display = ["name", "project", "updated_at"]
    list_filter = ["project"]


@admin.register(ProjectCache)
class ProjectCacheAdmin(admin.ModelAdmin):
    list_display = ["display_name", "identity", "scanned_at", "is_valid", "tempo", "updated_at"]
    search_fields = ["name", "file_path", "identity"]
    readonly_fields = [
        "identity",
        "scanned_at",
        "tempo",
        "is_valid",
        "timeline_errors",
        "timeline_data",
        "cue_points",
        "mixer_tracks",
        "updated_at",
    ]


@admin.register(AppSettings)
class AppSettingsAdmin(admin.ModelAdmin):
    list_display = [
        "ableton_osc_host",
        "last_active_project",
        "sliding_animation_enabled",
        "sliding_animation_duration_ms",
        "updated_at",
    ]

    def has_add_permission(self, request):
        return not AppSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


class ControlMappingInline(admin.TabularInline):
    model = ControlMapping
    extra = 0


@admin.register(ControlDevice)
class ControlDeviceAdmin(admin.ModelAdmin):
    list_display = ["name", "adapter", "identifier", "enabled", "updated_at"]
    inlines = [ControlMappingInline]
