"""Management command to export taxonomy DB back to JSON files."""

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils.text import slugify

from apps.core.models import TaxonomyMeta
from apps.taxonomy.models import Domain, Profile, Service, Skill

DB = "taxonomy"


def to_json(data):
    """Deterministic JSON serialisation for clean git diffs."""
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_json_file(path, data):
    """Write deterministic UTF-8 JSON, independent of the process locale."""
    path.write_text(to_json(data), encoding="utf-8")


def read_json_file(path):
    return json.loads(path.read_text(encoding="utf-8"))


def index_by_id(paths):
    """Map each record id to the file that already holds it.

    Exporting into an existing tree (the repo's own, via TAXONOMY_JSON_DIR)
    must rewrite those files in place: repo file names are descriptive slugs,
    not derived from ids, so writing to a computed name would duplicate every
    record and the next seed would load the stale copy as well.
    """
    index = {}
    for path in paths:
        try:
            record_id = read_json_file(path).get("id")
        except (ValueError, OSError, AttributeError):
            continue
        if record_id:
            index[record_id] = path
    return index


# Export sorts these by id; the file's own order is kept when only order differs.
ID_LISTS = ("requires", "recommended")


def merge_record(path, data):
    """Overlay `data` (every key export manages) onto the file at `path`.

    Keys the database does not model are kept. An empty value is not added to
    an existing file that lacks the key, and None removes the key.
    """
    exists = path.exists()
    record = read_json_file(path) if exists else {}
    for key, new in data.items():
        old = record.get(key)
        if new is None:
            record.pop(key, None)
        elif not new and exists and key not in record:
            continue
        elif key in ID_LISTS and isinstance(old, list) and sorted(old) == sorted(new):
            continue
        else:
            record[key] = new
    return record


class Command(BaseCommand):
    help = "Export taxonomy DB to JSON files matching the seed directory structure."

    def add_arguments(self, parser):
        parser.add_argument(
            "output_dir",
            nargs="?",
            default=None,
            help="Directory to write taxonomy/, profiles/ and services/ into. "
            "Defaults to settings.TAXONOMY_JSON_DIR.",
        )

    def handle(self, *args, **options):
        output = Path(options["output_dir"] or settings.TAXONOMY_JSON_DIR)
        # Same layout seed_taxonomy reads (and the repo uses): domain trees
        # under taxonomy/, with profiles/ and services/ beside it.
        taxonomy_out = output / "taxonomy"
        taxonomy_out.mkdir(parents=True, exist_ok=True)

        meta = TaxonomyMeta.load()

        profiles_out = output / "profiles"
        services_out = output / "services"
        existing_domains = index_by_id(taxonomy_out.glob("*/_domain.json"))
        existing_skills = index_by_id(
            p for p in taxonomy_out.glob("*/**/*.json") if not p.name.startswith("_")
        )
        existing_profiles = index_by_id(profiles_out.glob("*.json"))
        existing_services = index_by_id(services_out.glob("*.json"))

        # Build domain ID -> directory name mapping from meta.domains
        id_to_dir = {}
        for entry in meta.domains:
            id_to_dir[entry["id"]] = entry["directory"]

        # 1. Export _meta.json
        meta_path = taxonomy_out / "_meta.json"
        meta_data = (
            read_json_file(meta_path)
            if meta_path.exists()
            else {
                "title": "Security Laboratory Personnel Skill Taxonomy",
                "description": (
                    "Comprehensive competency taxonomy for a full-spectrum "
                    "security laboratory, aligned with ISO 17025 competence "
                    "management principles."
                ),
            }
        )
        meta_data.update(
            {
                "version": meta.version,
                "proficiency_model": meta.proficiency_model,
                "domains": meta.domains,
                "relationship_types": meta.relationship_types,
            }
        )
        write_json_file(meta_path, meta_data)
        self.stdout.write("Exported _meta.json")

        # 2. Export _domain.json for each Domain
        domain_count = 0
        for domain in Domain.objects.using(DB).all():
            dirname = id_to_dir.get(domain.id, slugify(domain.name))
            domain_path = existing_domains.get(domain.id, taxonomy_out / dirname / "_domain.json")
            domain_path.parent.mkdir(parents=True, exist_ok=True)

            write_json_file(
                domain_path,
                merge_record(
                    domain_path,
                    {
                        "id": domain.id,
                        "name": domain.name,
                        "description": domain.description,
                        "categories": domain.categories,
                        "note": domain.note,
                        "attack_tiers": domain.attack_tiers,
                    },
                ),
            )
            domain_count += 1
        self.stdout.write(f"Exported {domain_count} domains")

        # 3. Export skill JSON files
        skill_count = 0
        for skill in Skill.objects.using(DB).all():
            domain_dirname = id_to_dir.get(skill.domain_id, slugify(skill.domain.name))
            category_slug = slugify(skill.category)
            skill_slug = skill.id.lower()

            # New skills go to <domain-dir>/<category-slug>/<id>.json; existing
            # ones are rewritten where they already live.
            skill_path = existing_skills.get(
                skill.id, taxonomy_out / domain_dirname / category_slug / f"{skill_slug}.json"
            )
            skill_path.parent.mkdir(parents=True, exist_ok=True)

            write_json_file(
                skill_path,
                merge_record(
                    skill_path,
                    {
                        "id": skill.id,
                        "name": skill.name,
                        "domain": domain_dirname,
                        "category": skill.category,
                        "status": skill.status,
                        "description": skill.description,
                        "requires": list(
                            skill.requires.using(DB).values_list("id", flat=True).order_by("id")
                        ),
                        "recommended": list(
                            skill.recommended.using(DB).values_list("id", flat=True).order_by("id")
                        ),
                        "superseded_by": skill.superseded_by_id,
                        "proficiency": skill.proficiency,
                        "assessment_methods": skill.assessment_methods,
                        "framework_mappings": skill.framework_mappings,
                        "tags": skill.tags,
                        "equipment": skill.equipment,
                    },
                ),
            )
            skill_count += 1
        self.stdout.write(f"Exported {skill_count} skills")

        # 4. Export profiles
        profiles_out.mkdir(parents=True, exist_ok=True)
        profile_count = 0
        for profile in Profile.objects.using(DB).all():
            profile_path = existing_profiles.get(
                profile.id, profiles_out / f"{slugify(profile.id)}.json"
            )
            write_json_file(
                profile_path,
                merge_record(
                    profile_path,
                    {
                        "id": profile.id,
                        "name": profile.name,
                        "description": profile.description,
                        "domain": profile.domain_id,
                        "maturity_levels": profile.maturity_levels,
                    },
                ),
            )
            profile_count += 1
        self.stdout.write(f"Exported {profile_count} profiles")

        # 5. Export services
        services_out.mkdir(parents=True, exist_ok=True)
        service_count = 0
        for service in Service.objects.using(DB).all():
            service_path = existing_services.get(
                service.id, services_out / f"{slugify(service.id)}.json"
            )
            write_json_file(
                service_path,
                merge_record(
                    service_path,
                    {
                        "id": service.id,
                        "name": service.name,
                        "description": service.description,
                        "required_competencies": service.required_competencies,
                        "scope_reference": service.scope_reference,
                        "standards": service.standards,
                    },
                ),
            )
            service_count += 1
        self.stdout.write(f"Exported {service_count} services")

        self.stdout.write(
            self.style.SUCCESS(
                f"Done: {domain_count} domains, {skill_count} skills, "
                f"{profile_count} profiles, {service_count} services"
            )
        )
