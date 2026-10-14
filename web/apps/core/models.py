from django.db import models


class TaxonomyMeta(models.Model):
    """Singleton storing taxonomy metadata from _meta.json."""

    version = models.CharField(max_length=20)
    proficiency_model = models.JSONField()
    domains = models.JSONField()
    relationship_types = models.JSONField()
    profile_order = models.JSONField(default=list, blank=True)
    service_order = models.JSONField(default=list, blank=True)

    class Meta:
        app_label = "taxonomy"
        verbose_name = "Taxonomy Metadata"
        verbose_name_plural = "Taxonomy Metadata"

    def __str__(self):
        return f"Taxonomy v{self.version}"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.using("taxonomy").get_or_create(
            pk=1,
            defaults={
                "version": "0.0.0",
                "proficiency_model": {},
                "domains": [],
                "relationship_types": {},
            },
        )
        return obj

    @classmethod
    def domain_sort_key(cls):
        """Return a dict mapping domain ID to sort index, based on _meta.json order."""
        meta = cls.load()
        return {d["id"]: idx for idx, d in enumerate(meta.domains or [])}
