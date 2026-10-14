from django.urls import path

from . import views

app_name = "taxonomy"
urlpatterns = [
    path("", views.domain_list, name="domain-list"),
    path("reorder/", views.domain_reorder, name="domain-reorder"),
    path("services/reorder/", views.service_reorder, name="service-reorder"),
    path("skill/<str:skill_id>/", views.skill_detail, name="skill-detail"),
    path("skill/<str:skill_id>/edit/", views.skill_edit, name="skill-edit"),
    path("profiles/", views.profile_list, name="profile-list"),
    path("profiles/reorder/", views.profile_reorder, name="profile-reorder"),
    path("profiles/<str:profile_id>/", views.profile_detail, name="profile-detail"),
    path("profiles/<str:profile_id>/edit/", views.profile_edit, name="profile-edit"),
    path("services/", views.service_list, name="service-list"),
    path("services/<str:service_id>/", views.service_detail, name="service-detail"),
    path("services/<str:service_id>/edit/", views.service_edit, name="service-edit"),
    path("<str:domain_id>/", views.domain_detail, name="domain-detail"),
    path("<str:domain_id>/edit/", views.domain_edit, name="domain-edit"),
]
