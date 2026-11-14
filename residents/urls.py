from django.urls import path

from . import import_views, views

app_name = "residents"

urlpatterns = [
    path("", views.student_list, name="list"),
    path("new/", views.student_create, name="create"),
    path("import/", import_views.import_students, name="import"),
    path("import/confirm/", import_views.import_confirm, name="import_confirm"),
    path("import/cancel/", import_views.import_cancel, name="import_cancel"),
    path("import/template.csv", import_views.import_template, name="import_template"),
    path("cards/", views.student_cards, name="cards"),
    path("cards.pdf", views.student_cards_pdf, name="cards_pdf"),
    path("<int:pk>/", views.student_detail, name="detail"),
    path("<int:pk>/move/", views.student_move, name="move"),
    path("<int:pk>/left/", views.student_leave, name="leave"),
    path("<int:pk>/readmit/", views.student_readmit, name="readmit"),
    path("<int:pk>/edit/", views.student_edit, name="edit"),
    path("<int:pk>/qr.png", views.student_qr, name="qr"),
]
