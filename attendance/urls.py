from django.urls import path

from . import views

app_name = "attendance"

urlpatterns = [
    path("permits/", views.permit_list, name="permits"),
    path("permits/new/", views.permit_create, name="permit_create"),
    path("permits/<int:pk>/return/", views.permit_return, name="permit_return"),
    path("permits/<int:pk>/cancel/", views.permit_cancel, name="permit_cancel"),
    path("rollcall/", views.rollcall_home, name="rollcall_home"),
    path("rollcall/<int:hostel_pk>/", views.rollcall, name="rollcall"),
]
