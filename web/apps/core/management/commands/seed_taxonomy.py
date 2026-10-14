"""Management command to seed taxonomy data from JSON files."""

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.core.models import TaxonomyMeta
from apps.taxonomy.models import Domain, Profile, Service, Skill

DB = "taxonomy"


def read_json(path):
    """Read a JSON file as UTF-8, naming the file if it cannot be parsed."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise CommandError(f"{path}: invalid JSON ({e})")
    except OSError as e:
        raise CommandError(f"{path}: cannot read ({e})")


class Command(BaseCommand):
    help = "Load taxonomy JSON files into the database."

    def add_arguments(self, parser):
        parser.add_argument(
            "--source",
            default=None,
            help="Directory holding taxonomy/, profiles/ and services/. "
            "Defaults to settings.TAXONOMY_JSON_DIR.",
        )
        parser.add_argument(
            "--prune",
            action="store_true",
            help="Delete database rows that no longer have a backing JSON file.",
        )

    def handle(self, *args, **options):
        # One transaction on the taxonomy DB: a failure part-way through must
        # not leave a mixture of old and new reference data behind.
        with transaction.atomic(using=DB):
            self._seed(options)

    def _seed(self, options):
        root = Path(options["source"] or settings.TAXONOMY_JSON_DIR)
        if not root.is_dir():
            raise CommandError(f"{root}: not a directory")
        taxonomy_dir = root / "taxonomy"
        profiles_dir = root / "profiles"
        services_dir = root / "services"

        # 1. Load _meta.json into TaxonomyMeta singleton
        meta_path = taxonomy_dir / "_meta.json"
        meta_data = read_json(meta_path)

        seen_domains = set()
        seen_skills = set()
        seen_profiles = set()
        seen_services = set()

        meta = TaxonomyMeta.load()
        meta.version = meta_data["version"]
        meta.proficiency_model = meta_data["proficiency_model"]
        meta.domains = meta_data["domains"]
        meta.relationship_types = meta_data.get("relationship_types", {})
        meta.save(using=DB)
        self.stdout.write(f"Loaded TaxonomyMeta v{meta.version}")

        # 2. Build domain directory -> ID mapping from _meta.json
        dir_to_id = {}
        for entry in meta_data["domains"]:
            dir_to_id[entry["directory"]] = entry["id"]

        # 3. Load all _domain.json files into Domain objects
        domain_count = 0
        for domain_dir in sorted(taxonomy_dir.iterdir()):
            if not domain_dir.is_dir():
                continue
            domain_file = domain_dir / "_domain.json"
            if not domain_file.exists():
                continue
            d = read_json(domain_file)
            seen_domains.add(d["id"])
            Domain.objects.using(DB).update_or_create(
                id=d["id"],
                defaults={
                    "name": d["name"],
                    "description": d["description"],
                    "categories": d.get("categories", []),
                    "note": d.get("note", ""),
                    "attack_tiers": d.get("attack_tiers", []),
                },
            )
            domain_count += 1
        self.stdout.write(f"Loaded {domain_count} domains")

        # 4. Load all skill JSON files (skip files starting with _)
        #    Collect requires/recommended for second pass
        skill_relations = {}  # skill_id -> {requires: [...], recommended: [...], superseded_by: ...}
        skill_count = 0
        for domain_dir in sorted(taxonomy_dir.iterdir()):
            if not domain_dir.is_dir():
                continue
            for skill_file in sorted(domain_dir.rglob("*.json")):
                if skill_file.name.startswith("_"):
                    continue
                s = read_json(skill_file)
                seen_skills.add(s["id"])

                # Resolve domain directory name to domain ID
                domain_dirname = s["domain"]
                domain_id = dir_to_id.get(domain_dirname, domain_dirname)

                Skill.objects.using(DB).update_or_create(
                    id=s["id"],
                    defaults={
                        "name": s["name"],
                        "domain_id": domain_id,
                        "category": s.get("category", ""),
                        "status": s.get("status", "active"),
                        "description": s.get("description", ""),
                        "proficiency": s.get("proficiency", {}),
                        "assessment_methods": s.get("assessment_methods", []),
                        "framework_mappings": s.get("framework_mappings", {}),
                        "tags": s.get("tags", []),
                        "equipment": s.get("equipment", []),
                    },
                )
                skill_count += 1

                # Collect relationship data for second pass
                # Recorded for every skill, empty or not, so a relation removed
                # from the JSON is also removed from the database.
                skill_relations[s["id"]] = {
                    "requires": s.get("requires") or [],
                    "recommended": s.get("recommended") or [],
                    "superseded_by": s.get("superseded_by"),
                }

        self.stdout.write(f"Loaded {skill_count} skills")

        # 5. Wire up M2M relationships and superseded_by in a second pass
        m2m_count = 0
        for skill_id, rels in skill_relations.items():
            skill = Skill.objects.using(DB).get(id=skill_id)

            required_skills = Skill.objects.using(DB).filter(id__in=rels["requires"])
            skill.requires.set(required_skills)
            m2m_count += required_skills.count()

            recommended_skills = Skill.objects.using(DB).filter(id__in=rels["recommended"])
            skill.recommended.set(recommended_skills)
            m2m_count += recommended_skills.count()

            superseding = None
            if rels["superseded_by"]:
                superseding = Skill.objects.using(DB).filter(id=rels["superseded_by"]).first()
                if superseding is None:
                    self.stderr.write(
                        f"Warning: superseded_by target '{rels['superseded_by']}' "
                        f"not found for skill {skill_id}"
                    )
            if skill.superseded_by_id != (superseding.id if superseding else None):
                skill.superseded_by = superseding
                skill.save(using=DB)

        self.stdout.write(f"Wired {m2m_count} M2M relationships")

        # 6. Load profiles
        profile_count = 0
        for profile_file in sorted(profiles_dir.glob("*.json")):
            p = read_json(profile_file)
            seen_profiles.add(p["id"])

            domain_id = p.get("domain")
            Profile.objects.using(DB).update_or_create(
                id=p["id"],
                defaults={
                    "name": p["name"],
                    "description": p.get("description", ""),
                    "domain_id": domain_id,
                    "maturity_levels": p.get("maturity_levels", {}),
                },
            )
            profile_count += 1
        self.stdout.write(f"Loaded {profile_count} profiles")

        # 7. Load services
        service_count = 0
        for service_file in sorted(services_dir.glob("*.json")):
            svc = read_json(service_file)
            seen_services.add(svc["id"])
            Service.objects.using(DB).update_or_create(
                id=svc["id"],
                defaults={
                    "name": svc["name"],
                    "description": svc.get("description", ""),
                    "required_competencies": svc.get("required_competencies", []),
                    "scope_reference": svc.get("scope_reference", ""),
                    "standards": svc.get("standards", []),
                },
            )
            service_count += 1
        self.stdout.write(f"Loaded {service_count} services")

        if options["prune"]:
            # Order matters: skills reference domains with on_delete=PROTECT.
            stale_services = Service.objects.using(DB).exclude(id__in=seen_services)
            stale_profiles = Profile.objects.using(DB).exclude(id__in=seen_profiles)
            stale_skills = Skill.objects.using(DB).exclude(id__in=seen_skills)

            pruned = 0
            for queryset, label in (
                (stale_services, "services"),
                (stale_profiles, "profiles"),
                (stale_skills, "skills"),
            ):
                ids = list(queryset.values_list("id", flat=True))
                if ids:
                    self.stdout.write(f"Pruning {len(ids)} {label}: {', '.join(ids)}")
                    queryset.delete()
                    pruned += len(ids)

            stale_domains = Domain.objects.using(DB).exclude(id__in=seen_domains)
            for domain in stale_domains:
                if domain.skills.exists():
                    self.stderr.write(
                        f"Warning: domain '{domain.id}' has no _domain.json but still "
                        f"has skills; not pruning."
                    )
                else:
                    self.stdout.write(f"Pruning domain {domain.id}")
                    domain.delete()
                    pruned += 1

            self.stdout.write(f"Pruned {pruned} record(s)")

        self.stdout.write(
            self.style.SUCCESS(
                f"Done: {domain_count} domains, {skill_count} skills, "
                f"{profile_count} profiles, {service_count} services"
            )
        )
