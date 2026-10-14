import re
import unicodedata

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.core.validators import LEVEL_MAX, LEVEL_MIN

LEVEL_VALIDATORS = [MinValueValidator(LEVEL_MIN), MaxValueValidator(LEVEL_MAX)]


MAX_ID_LENGTH = 50

# Latin letters NFKD does not decompose into a base letter plus a mark.
_LATIN_EXTRA = str.maketrans(
    {
        "ł": "l",
        "Ł": "l",
        "ø": "o",
        "Ø": "o",
        "ß": "ss",
        "æ": "ae",
        "Æ": "ae",
        "œ": "oe",
        "Œ": "oe",
        "đ": "d",
        "Đ": "d",
        "þ": "th",
        "Þ": "th",
        "ı": "i",
    }
)


def sanitize_id(value, max_length=MAX_ID_LENGTH):
    """Build a URL-safe ID from a display name.

    Accented Latin characters are transliterated ("Müller" -> "muller") rather
    than dropped, which previously turned them into misspellings. Scripts with
    no Latin transliteration yield "" — callers must treat that as an error
    rather than creating a record with an empty primary key.
    """
    # NFKD splits "ü" into "u" + combining diaeresis; dropping the combining
    # marks leaves the base letter.
    decomposed = unicodedata.normalize("NFKD", value.translate(_LATIN_EXTRA))
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))

    text = stripped.lower().strip()
    text = re.sub(r"['\"\s]+", "-", text)
    text = re.sub(r"[^a-z0-9\-]", "", text)
    text = re.sub(r"-{2,}", "-", text)
    return text.strip("-")[:max_length].strip("-")


class Person(models.Model):
    id = models.CharField(max_length=MAX_ID_LENGTH, primary_key=True)
    name = models.CharField(max_length=200)
    domains = models.JSONField(default=list)
    start_date = models.DateField()

    class Meta:
        app_label = "personnel"
        ordering = ["name"]

    def __str__(self):
        return f"{self.id}: {self.name}"


class PersonSkill(models.Model):
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="skills")
    skill_id = models.CharField(max_length=50)
    level = models.PositiveSmallIntegerField(validators=LEVEL_VALIDATORS)
    assessed_date = models.DateField()
    assessed_by_id = models.CharField(max_length=150)
    last_practiced = models.DateField(null=True, blank=True)
    evidence_notes = models.TextField(blank=True, default="")
    authorization = models.JSONField(null=True, blank=True, default=None)
    is_self_assessed = models.BooleanField(default=False)

    class Meta:
        app_label = "personnel"
        unique_together = [("person", "skill_id")]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(level__gte=LEVEL_MIN, level__lte=LEVEL_MAX),
                name="personskill_level_in_range",
            ),
        ]

    def __str__(self):
        return f"{self.person.id} — {self.skill_id} (L{self.level})"

    def clean(self):
        from apps.taxonomy.models import Skill

        if not Skill.objects.using("taxonomy").filter(id=self.skill_id).exists():
            raise ValidationError(
                {"skill_id": f"Skill '{self.skill_id}' does not exist in taxonomy."}
            )


class DevelopmentPlan(models.Model):
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="development_plans")
    skill_id = models.CharField(max_length=50)
    current_level = models.PositiveSmallIntegerField(validators=LEVEL_VALIDATORS)
    target_level = models.PositiveSmallIntegerField(validators=LEVEL_VALIDATORS)
    target_date = models.DateField()
    actions = models.JSONField(default=list)

    class Meta:
        app_label = "personnel"
        unique_together = [("person", "skill_id")]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    current_level__gte=LEVEL_MIN,
                    current_level__lte=LEVEL_MAX,
                    target_level__gte=LEVEL_MIN,
                    target_level__lte=LEVEL_MAX,
                ),
                name="developmentplan_levels_in_range",
            ),
        ]

    def __str__(self):
        return f"{self.person.id} — {self.skill_id}: {self.current_level} → {self.target_level}"


class SelfAssessment(models.Model):
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="self_assessments")
    skill_id = models.CharField(max_length=50)
    level = models.PositiveSmallIntegerField(validators=LEVEL_VALIDATORS)
    assessed_date = models.DateField()
    evidence_notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "personnel"
        unique_together = [("person", "skill_id")]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(level__gte=LEVEL_MIN, level__lte=LEVEL_MAX),
                name="selfassessment_level_in_range",
            ),
        ]

    def __str__(self):
        return f"{self.person.id} — {self.skill_id} self:L{self.level}"


class Project(models.Model):
    STATUS_CHOICES = [
        ("planning", "Planning"),
        ("done", "Done"),
        ("archived", "Archived"),
    ]

    id = models.CharField(max_length=50, primary_key=True)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="planning")
    required_competencies = models.JSONField(default=list)
    source_service_id = models.CharField(max_length=50, blank=True, default="")
    created_by_id = models.CharField(max_length=150, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    notes = models.TextField(blank=True, default="")

    class Meta:
        app_label = "personnel"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.status})"


def _unique_id(model, name, prefix, max_length=MAX_ID_LENGTH):
    """A free ID derived from `name`, or `<prefix>-<n>` when nothing survives.

    Names in non-Latin scripts sanitize to "", and refusing them would force
    people to misspell their own names, so they get a numbered ID instead.
    """
    base = sanitize_id(name, max_length=max_length)
    candidate = base or f"{prefix}-1"
    counter = 2
    while model.objects.filter(id=candidate).exists():
        suffix = f"-{counter}"
        candidate = f"{(base or prefix)[: max_length - len(suffix)].strip('-')}{suffix}"
        counter += 1
    return candidate


def unique_person_id(name):
    return _unique_id(Person, name, "person")


def unique_project_id(name):
    return _unique_id(Project, name, "project")
