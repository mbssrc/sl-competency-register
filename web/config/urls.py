from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("apps.accounts.urls")),
    path("taxonomy/", include("apps.taxonomy.urls")),
    path("personnel/", include("apps.personnel.urls")),
    path("", include("apps.core.urls")),
]
