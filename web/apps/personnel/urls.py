from django.urls import path

from . import views

app_name = "personnel"
urlpatterns = [
    path("", views.person_list, name="person-list"),
    path("add/", views.person_create, name="person-create"),
    path("gaps/", views.gap_analysis, name="gap-analysis"),
    path("gaps/export/", views.gap_analysis_export, name="gap-analysis-export"),
    path("readiness/", views.service_readiness, name="service-readiness"),
    # Projects (before person catch-all)
    path("projects/", views.project_list, name="project-list"),
    path("projects/create/", views.project_create, name="project-create"),
    path("projects/<str:project_id>/", views.project_detail, name="project-detail"),
    path("projects/<str:project_id>/edit/", views.project_edit, name="project-edit"),
    path("projects/<str:project_id>/skills/", views.project_skills, name="project-skills"),
    path("projects/<str:project_id>/assess/", views.project_assess, name="project-assess"),
    # Person detail (catch-all — must be last)
    path("<str:person_id>/", views.person_detail, name="person-detail"),
    path("<str:person_id>/edit/", views.person_edit, name="person-edit"),
    path("<str:person_id>/delete/", views.person_delete, name="person-delete"),
    path("<str:person_id>/skill/add/", views.person_skill_add, name="person-skill-add"),
    path(
        "<str:person_id>/skill/<str:skill_id>/edit/",
        views.person_skill_edit,
        name="person-skill-edit",
    ),
    path(
        "<str:person_id>/skill/<str:skill_id>/delete/",
        views.person_skill_delete,
        name="person-skill-delete",
    ),
    path(
        "<str:person_id>/self-assessment/export/",
        views.self_assessment_export,
        name="self-assessment-export",
    ),
    path(
        "<str:person_id>/self-assessment/import/",
        views.self_assessment_import,
        name="self-assessment-import",
    ),
    path(
        "<str:person_id>/seed-self-assessment/",
        views.seed_self_assessment,
        name="seed-self-assessment",
    ),
]
