from django.urls import path
from . import views 

# Standard practice is to use the 'views.' prefix to keep it clean
urlpatterns = [
    path('collect-meal/', views.collect_meal, name='collect_meal'),
    path('scanner/', views.scanner_page, name='scanner_page'),
    path("admin-dashboard/", views.admin_dashboard, name='admin_dashboard'),
    path("stats/", views.meal_stats, name='meal_stats'),
]