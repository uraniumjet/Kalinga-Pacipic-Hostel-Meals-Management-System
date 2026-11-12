from django.urls import path

from mess import setup_views as m

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
    path("meals/", m.meals, name="meals"),
    path("meals/<int:pk>/edit/", m.meal_edit, name="meal_edit"),
    path("meals/<int:pk>/delete/", m.meal_delete, name="meal_delete"),
    path("counters/", m.counters, name="counters"),
    path("counters/<int:pk>/edit/", m.counter_edit, name="counter_edit"),
    path("counters/<int:pk>/delete/", m.counter_delete, name="counter_delete"),
    path("periods/", m.periods, name="periods"),
    path("periods/<int:pk>/", m.period_detail, name="period"),
    path("periods/<int:pk>/delete/", m.period_delete, name="period_delete"),
    path("periods/<int:pk>/meals/<int:meal_pk>/clear/", m.period_window_clear, name="period_window_clear"),
    path("periods/<int:pk>/day-changes/<int:override_pk>/delete/", m.override_delete, name="override_delete"),
]
