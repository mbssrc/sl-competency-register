from django.contrib import admin

from .models import DevelopmentPlan, Person, PersonSkill


class PersonSkillInline(admin.TabularInline):
    model = PersonSkill
    extra = 1


class DevelopmentPlanInline(admin.TabularInline):
    model = DevelopmentPlan
    extra = 1


@admin.register(Person)
class PersonAdmin(admin.ModelAdmin):
    list_display = ["id", "name", "start_date"]
    search_fields = ["id", "name"]
    inlines = [PersonSkillInline, DevelopmentPlanInline]
