"""Management command to validate cross-DB references and DAG integrity."""

import sys
from collections import defaultdict

from django.core.management.base import BaseCommand

from apps.personnel.models import DevelopmentPlan, Person, PersonSkill
from apps.taxonomy.models import Domain, Service, Skill

DB_TAXONOMY = "taxonomy"
DB_DEFAULT = "default"


class Command(BaseCommand):
    help = "Validate cross-DB references and DAG integrity."

    def handle(self, *args, **options):
        errors = []
        warnings = []

        # Collect all skill IDs and domain IDs from taxonomy DB
        skill_ids = set(Skill.objects.using(DB_TAXONOMY).values_list("id", flat=True))
        domain_ids = set(Domain.objects.using(DB_TAXONOMY).values_list("id", flat=True))

        # 1. Cross-DB references: PersonSkill.skill_id must exist in taxonomy
        for ps in PersonSkill.objects.using(DB_DEFAULT).all():
            if ps.skill_id not in skill_ids:
                errors.append(
                    f"ERROR [cross-db] PersonSkill {ps.person_id}/{ps.skill_id}: "
                    f"skill_id not found in taxonomy DB"
                )

        # 2. Cross-DB references: DevelopmentPlan.skill_id must exist in taxonomy
        for dp in DevelopmentPlan.objects.using(DB_DEFAULT).all():
            if dp.skill_id not in skill_ids:
                errors.append(
                    f"ERROR [cross-db] DevelopmentPlan {dp.person_id}/{dp.skill_id}: "
                    f"skill_id not found in taxonomy DB"
                )

        # 3. Domain references: Person.domains entries must exist in taxonomy
        for person in Person.objects.using(DB_DEFAULT).all():
            for domain_id in person.domains or []:
                if domain_id not in domain_ids:
                    errors.append(
                        f"ERROR [cross-db] Person {person.id}: "
                        f"domain '{domain_id}' not found in taxonomy DB"
                    )

        # 4. DAG cycle detection on requires relationships
        graph = defaultdict(set)
        for skill in Skill.objects.using(DB_TAXONOMY).prefetch_related("requires"):
            for req in skill.requires.all():
                graph[skill.id].add(req.id)

        WHITE, GRAY, BLACK = 0, 1, 2
        color = defaultdict(int)
        cycles = []

        def dfs(node, path):
            color[node] = GRAY
            path.append(node)
            for neighbor in graph.get(node, set()):
                if color[neighbor] == GRAY:
                    cycle_start = path.index(neighbor)
                    cycles.append(path[cycle_start:] + [neighbor])
                elif color[neighbor] == WHITE:
                    dfs(neighbor, path)
            path.pop()
            color[node] = BLACK

        all_nodes = set(graph.keys())
        for edges in graph.values():
            all_nodes.update(edges)

        for node in sorted(all_nodes):
            if color[node] == WHITE:
                dfs(node, [])

        for cycle in cycles:
            errors.append(f"ERROR [dag] Circular dependency: {' -> '.join(cycle)}")

        # 5. Orphan warnings: skills not referenced by any Service or personnel record
        referenced_skills = set()
        for service in Service.objects.using(DB_TAXONOMY).all():
            for comp in service.required_competencies or []:
                skill_ref = comp.get("skill")
                if skill_ref:
                    referenced_skills.add(skill_ref)
        assessed_skills = set(
            PersonSkill.objects.using(DB_DEFAULT).values_list("skill_id", flat=True)
        )
        referenced_skills.update(assessed_skills)

        orphans = skill_ids - referenced_skills
        for sid in sorted(orphans):
            warnings.append(
                f"WARNING [orphan] Skill '{sid}' not referenced by any service or personnel record"
            )

        # Report
        for msg in errors:
            self.stderr.write(msg)
        for msg in warnings:
            self.stderr.write(msg)

        error_count = len(errors)
        warning_count = len(warnings)

        if error_count == 0 and warning_count == 0:
            self.stdout.write(
                self.style.SUCCESS(f"Integrity check passed. {len(skill_ids)} skills verified.")
            )
        elif error_count == 0:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Integrity check passed with {warning_count} warning(s). "
                    f"{len(skill_ids)} skills verified."
                )
            )
        else:
            self.stderr.write(
                self.style.ERROR(
                    f"Integrity check FAILED: {error_count} error(s), {warning_count} warning(s)."
                )
            )
            sys.exit(1)
