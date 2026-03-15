from django.urls import path
from . import views 
from .views import list_students, create_student, student_register

urlpatterns = [
    path('', list_students),
    path('create/', create_student),
    path('register/', student_register, name='student_register'),
    path("", views.dashboard, name="dashboard"),
    path("delete/<int:id>/", views.delete_student, name="delete_student"),

]