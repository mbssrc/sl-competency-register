from django.db import models


class Domain(models.Model):
    id = models.CharField(max_length=20, primary_key=True)
    name = models.CharField(max_length=100)
    description = models.TextField()
    categories = models.JSONField(default=list)
    note = models.TextField(blank=True, default="")
    attack_tiers = models.JSONField(default=list, blank=True)

    class Meta:
        app_label = "taxonomy"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Skill(models.Model):
    STATUS_CHOICES = [("active", "Active"), ("deprecated", "Deprecated")]

    id = models.CharField(max_length=50, primary_key=True)
    name = models.CharField(max_length=200)
    domain = models.ForeignKey(Domain, on_delete=models.PROTECT, related_name="skills")
    category = models.CharField(max_length=100)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    superseded_by = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="supersedes"
    )
    description = models.TextField()
    proficiency = models.JSONField(default=dict)
    requires = models.ManyToManyField(
        "self", symmetrical=False, related_name="required_by", blank=True
    )
    recommended = models.ManyToManyField(
        "self", symmetrical=False, related_name="recommended_for", blank=True
    )
    assessment_methods = models.JSONField(default=list, blank=True)
    framework_mappings = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(default=list, blank=True)
    equipment = models.JSONField(default=list, blank=True)

    class Meta:
        app_label = "taxonomy"
        ordering = ["id"]

    def __str__(self):
        return f"{self.id}: {self.name}"


class Profile(models.Model):
    id = models.CharField(max_length=50, primary_key=True)
    name = models.CharField(max_length=200)
    domain = models.OneToOneField(
        Domain,
        on_delete=models.PROTECT,
        related_name="maturity_profile",
        null=True,
        blank=True,
    )
    description = models.TextField()
    maturity_levels = models.JSONField(default=dict)

    class Meta:
        app_label = "taxonomy"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Service(models.Model):
    id = models.CharField(max_length=50, primary_key=True)
    name = models.CharField(max_length=200)
    description = models.TextField()
    required_competencies = models.JSONField(default=list)
    scope_reference = models.CharField(max_length=200, blank=True, default="")
    standards = models.JSONField(default=list, blank=True)

    class Meta:
        app_label = "taxonomy"
        ordering = ["name"]

    def __str__(self):
        return self.name
