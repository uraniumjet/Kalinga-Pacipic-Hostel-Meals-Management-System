from django.urls import path

from . import setup_views as v

app_name = "setup"

urlpatterns = [
    path("", v.index, name="index"),
    path("lists/", v.lookups, name="lookups"),
    path("lists/<str:kind>/<int:pk>/edit/", v.lookup_edit, name="lookup_edit"),
    path("lists/<str:kind>/<int:pk>/delete/", v.lookup_delete, name="lookup_delete"),
    path("hostels/", v.hostels, name="hostels"),
    path("hostels/<int:pk>/", v.hostel_detail, name="hostel"),
    path("hostels/<int:pk>/delete/", v.hostel_delete, name="hostel_delete"),
    path("rooms/<int:pk>/edit/", v.room_edit, name="room_edit"),
    path("rooms/<int:pk>/delete/", v.room_delete, name="room_delete"),
    path("staff/", v.staff_list, name="staff"),
    path("staff/new/", v.staff_edit, name="staff_new"),
    path("staff/<int:pk>/", v.staff_edit, name="staff_edit"),
]
