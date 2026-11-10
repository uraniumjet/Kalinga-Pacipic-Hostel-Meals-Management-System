from django.urls import path

from . import views

app_name = "mess"

urlpatterns = [
    path("", views.counter_list, name="counters"),
    path("counter/<int:pk>/", views.counter_screen, name="counter"),
]
