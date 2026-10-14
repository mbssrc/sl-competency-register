from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("health/", views.health, name="health"),
    path("admin-tools/", views.admin_tools, name="admin-tools"),
    path("admin-tools/seed/", views.admin_seed, name="admin-seed"),
    path("admin-tools/export-json/", views.admin_export_json, name="admin-export-json"),
    path("admin-tools/export-download/", views.admin_export_download, name="admin-export-download"),
    path(
        "admin-tools/check-integrity/",
        views.admin_check_integrity,
        name="admin-check-integrity",
    ),
    path("users/", views.user_list, name="user-list"),
    path("users/create/", views.user_create, name="user-create"),
    path("users/<int:user_id>/edit/", views.user_edit, name="user-edit"),
    path(
        "users/<int:user_id>/toggle-active/",
        views.user_toggle_active,
        name="user-toggle-active",
    ),
    path("export/", views.export_page, name="export-page"),
    path("export/taxonomy.xlsx", views.export_taxonomy_xlsx, name="export-taxonomy"),
    path("export/personnel.xlsx", views.export_personnel_xlsx, name="export-personnel"),
    path("export/reports.xlsx", views.export_reports_xlsx, name="export-reports"),
]
