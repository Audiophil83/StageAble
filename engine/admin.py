from django.contrib import admin

from .models import AppSettings, ProjectCache, Setlist, SetlistEntry


class SetlistEntryInline(admin.TabularInline):
    model = SetlistEntry
    extra = 1


@admin.register(Setlist)
class SetlistAdmin(admin.ModelAdmin):
    list_display = ["name", "is_active", "updated_at"]
    inlines = [SetlistEntryInline]


@admin.register(ProjectCache)
class ProjectCacheAdmin(admin.ModelAdmin):
    list_display = ["scanned_at", "is_valid", "tempo", "updated_at"]
    readonly_fields = [
        "scanned_at",
        "tempo",
        "is_valid",
        "timeline_errors",
        "timeline_data",
        "cue_points",
        "mixer_tracks",
        "updated_at",
    ]

    def has_add_permission(self, request):
        return not ProjectCache.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AppSettings)
class AppSettingsAdmin(admin.ModelAdmin):
    list_display = [
        "ableton_osc_host",
        "sliding_animation_enabled",
        "sliding_animation_duration_ms",
        "updated_at",
    ]

    def has_add_permission(self, request):
        return not AppSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
