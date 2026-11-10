from django.contrib import admin

from .models import Category, DietType, Hostel, Organization, Room, StaffProfile

admin.site.register(Organization)
admin.site.register(Category)
admin.site.register(DietType)
admin.site.register(StaffProfile)


@admin.register(Hostel)
class HostelAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "gender")


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ("hostel", "number", "capacity")
    list_filter = ("hostel",)
