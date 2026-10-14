from django.contrib import admin

from .models import Domain, Profile, Service, Skill


@admin.register(Domain)
class DomainAdmin(admin.ModelAdmin):
    list_display = ["id", "name"]
    search_fields = ["id", "name"]


@admin.register(Skill)
class SkillAdmin(admin.ModelAdmin):
    list_display = ["id", "name", "domain", "category", "status"]
    list_filter = ["domain", "status"]
    search_fields = ["id", "name"]


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ["id", "name"]


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ["id", "name"]
