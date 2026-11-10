from django.contrib import admin

from .models import RoomAllocation, Student


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ("name", "roll_number", "organization", "gender", "category", "diet", "status")
    list_filter = ("organization", "category", "diet", "gender", "status")
    search_fields = ("name", "roll_number")
    readonly_fields = ("qr_token",)


@admin.register(RoomAllocation)
class RoomAllocationAdmin(admin.ModelAdmin):
    list_display = ("student", "room", "start_date", "end_date")
    list_filter = ("room__hostel",)
