"""URL configuration. Each app owns its own URLs."""
from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.generic import RedirectView

from backend.views import healthz
from residents.views import student_photo

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="accounts:home", permanent=False)),
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("setup/", include("organizations.setup_urls")),
    path("residents/", include("residents.urls")),
    path("mess/", include("mess.urls")),
    path("attendance/", include("attendance.urls")),
    path("reports/", include("reports.urls")),
    path("healthz/", healthz, name="healthz"),
    # Photos are personal data, so they are served by a view that checks who is asking.
    re_path(r"^" + settings.MEDIA_URL.lstrip("/") + r"(?P<name>.+)$", student_photo, name="media"),
]
