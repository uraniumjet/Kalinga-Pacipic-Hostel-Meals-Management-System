from django.contrib import admin

from .models import ExitPermit, RollCall, RollCallEntry


@admin.register(ExitPermit)
class ExitPermitAdmin(admin.ModelAdmin):
    list_display = ("student", "start_date", "end_date", "returned_on", "cancelled", "granted_by")
    list_filter = ("cancelled",)
    search_fields = ("student__name", "student__roll_number")


class EntryInline(admin.TabularInline):
    model = RollCallEntry
    extra = 0


@admin.register(RollCall)
class RollCallAdmin(admin.ModelAdmin):
    list_display = ("hostel", "date", "taken_by", "updated_at")
    list_filter = ("hostel", "date")
    inlines = [EntryInline]
