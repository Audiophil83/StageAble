from django.contrib import admin

from .models import AppSettings, Setlist, SetlistEntry


class SetlistEntryInline(admin.TabularInline):
    model = SetlistEntry
    extra = 1


@admin.register(Setlist)
class SetlistAdmin(admin.ModelAdmin):
    list_display = ["name", "is_active", "updated_at"]
    inlines = [SetlistEntryInline]


@admin.register(AppSettings)
class AppSettingsAdmin(admin.ModelAdmin):
    list_display = [
        "ableton_osc_host",
        "default_preroll_bars",
        "updated_at",
    ]

    def has_add_permission(self, request):
        return not AppSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
