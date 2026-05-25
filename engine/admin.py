from django.contrib import admin

from .models import Setlist, SetlistEntry


class SetlistEntryInline(admin.TabularInline):
    model = SetlistEntry
    extra = 1


@admin.register(Setlist)
class SetlistAdmin(admin.ModelAdmin):
    list_display = ["name", "is_active", "updated_at"]
    inlines = [SetlistEntryInline]
