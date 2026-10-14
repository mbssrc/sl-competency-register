#!/usr/bin/env python3
"""Check the seeded demo against the application's own calculations.

demo/expand.py reads only JSON and reimplements nothing from
apps/personnel/services.py, so it approximates the maturity ladders. This
script checks the seeded result using the real compute_domain_maturity, which
is what the pages will show. When the two disagree, the archetype is wrong, not
the application.
"""

import os
import sys
from pathlib import Path

DEMO_DIR = Path(__file__).resolve().parent
REPO_ROOT = DEMO_DIR.parent
WEB_DIR = REPO_ROOT / "web"

# The skills that make invasive analysis a single-point-of-failure story.
INVASIVE_SKILLS = [
    "HWSEC-INV-DECAP",
    "HWSEC-INV-DELAYER",
    "HWSEC-INV-PROBE",
    "HWSEC-INV-FIB",
    "HWSEC-INV-TAMPER",
]

# Planning projects that must each have at least one requirement nobody meets.
EXPECTED_GAPS = ["PRJ-SAT-OS", "PRJ-SAT-CP-INV", "PRJ-MEDGRANT-WEB"]

# A self-assessment rollout that only reached a handful of people does not
# demonstrate the workflow.
MIN_SELF_ASSESSED_PEOPLE = 15


def setup_django():
    sys.path.insert(0, str(WEB_DIR))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    os.environ.setdefault("DJANGO_DEBUG", "true")
    import django

    django.setup()


def check_counts(snapshot):
    from apps.personnel.models import Person, PersonSkill, Project

    failures = []
    expected_people = len(snapshot["people"])
    expected_rows = sum(len(p["skills"]) for p in snapshot["people"])
    expected_projects = len(snapshot["projects"])

    for label, expected, actual in [
        ("people", expected_people, Person.objects.count()),
        ("assessments", expected_rows, PersonSkill.objects.count()),
        ("projects", expected_projects, Project.objects.count()),
    ]:
        if expected != actual:
            failures.append(f"{label}: snapshot has {expected}, database has {actual}")
    return failures


def check_maturity(archetypes):
    """Every person must compute as the rung their archetype targets."""
    from apps.personnel.models import Person, sanitize_id
    from apps.personnel.services import compute_domain_maturity
    from apps.taxonomy.models import Profile

    failures = []
    for arch in archetypes:
        person = Person.objects.get(pk=sanitize_id(arch["name"]))
        targets = arch.get("target_maturity", {})

        # A person whose levels are all self-reported has had nothing ratified,
        # so the ladder cannot place them. That is the intended state.
        if arch.get("self_assessment", {}).get("mode") == "only":
            for domain_id in targets:
                profile = Profile.objects.using("taxonomy").get(domain_id=domain_id)
                result = compute_domain_maturity(person, profile)
                if result["level"] is not None:
                    failures.append(
                        f"{person.name}: holds only self-assessments but computes as "
                        f"'{result['level']}' in {domain_id}"
                    )
            continue

        for domain_id, target in sorted(targets.items()):
            profile = Profile.objects.using("taxonomy").get(domain_id=domain_id)
            result = compute_domain_maturity(person, profile)
            if result["level"] != target:
                failures.append(
                    f"{person.name}: {domain_id} targets '{target}' but the "
                    f"application computes '{result['level']}'"
                )
    return failures


def check_project_coverage():
    """Finished work must have been staffable; the gap projects must not be."""
    from apps.personnel.models import Project
    from apps.personnel.services import compute_project_coverage

    failures = []
    for project in Project.objects.all():
        coverage = compute_project_coverage(project) or []
        uncovered = [c["skill_id"] for c in coverage if not c["is_covered"]]

        if project.status in ("done", "archived") and uncovered:
            failures.append(
                f"{project.id} is {project.status} but {len(uncovered)} "
                f"requirement(s) have nobody qualified: {', '.join(uncovered)}"
            )
        if project.id in EXPECTED_GAPS and not uncovered:
            failures.append(
                f"{project.id} is meant to show a capability gap, but every requirement is covered"
            )
    return failures


def check_key_person_risk():
    """Invasive analysis must rest on exactly one person."""
    from apps.personnel.models import PersonSkill

    failures = []
    for skill_id in INVASIVE_SKILLS:
        holders = PersonSkill.objects.filter(skill_id=skill_id, level__gte=3)
        names = sorted(h.person.name for h in holders)
        if len(names) != 1:
            failures.append(
                f"{skill_id} should have exactly one holder at L3+, found "
                f"{len(names)}: {', '.join(names) or 'nobody'}"
            )
    return failures


def check_self_assessments():
    """The self-assessment layer must be broad, visible and promotable."""
    from apps.personnel.models import Person, PersonSkill, SelfAssessment

    failures = []

    assessed = Person.objects.filter(self_assessments__isnull=False).distinct().count()
    if assessed < MIN_SELF_ASSESSED_PEOPLE:
        failures.append(
            f"only {assessed} people have self-assessments; at least "
            f"{MIN_SELF_ASSESSED_PEOPLE} should, to show the workflow"
        )

    # The person detail table iterates PersonSkill and only filters by
    # self-assessed IDs, so a SelfAssessment with no PersonSkill row is
    # invisible on the page. self_assessment_import always creates the level-0
    # placeholder; seeded data must too.
    held = set(PersonSkill.objects.values_list("person_id", "skill_id"))
    orphans = [
        f"{person_id}/{skill_id}"
        for person_id, skill_id in SelfAssessment.objects.values_list("person_id", "skill_id")
        if (person_id, skill_id) not in held
    ]
    if orphans:
        failures.append(
            f"{len(orphans)} self-assessment(s) have no PersonSkill row and so "
            f"cannot be seen on the person page: {', '.join(orphans[:3])}"
            + (" ..." if len(orphans) > 3 else "")
        )

    # Something must be left for a manager to promote, or the "seed from
    # self-assessment" action has nothing to act on in the demo.
    from apps.personnel.views import _seedable_skills

    promotable = [p.name for p in Person.objects.all() if _seedable_skills(p)[0]]
    if not promotable:
        failures.append(
            "no person has a promotable self-assessment, so the "
            "'seed from self-assessment' flow cannot be shown"
        )
    return failures


def summary():
    from apps.personnel.models import DevelopmentPlan, Person, PersonSkill, Project, SelfAssessment
    from apps.personnel.services import compute_service_readiness

    readiness = compute_service_readiness()
    thin = [r["service_id"] for r in readiness if not r["fully_staffable"]]

    print("Demo population:")
    print(
        f"  {Person.objects.count()} people, "
        f"{PersonSkill.objects.count()} assessments, "
        f"{SelfAssessment.objects.count()} self-assessments, "
        f"{DevelopmentPlan.objects.count()} development targets"
    )
    print(
        f"  {Project.objects.count()} projects "
        f"({Project.objects.filter(status='planning').count()} planning, "
        f"{Project.objects.filter(status='done').count()} done, "
        f"{Project.objects.filter(status='archived').count()} archived)"
    )
    print(
        f"  {len(thin)} of {len(readiness)} services are not fully staffable"
        + (f": {', '.join(sorted(thin))}" if thin else "")
    )

    from apps.personnel.views import _seedable_skills

    assessed = Person.objects.filter(self_assessments__isnull=False).distinct().count()
    placeholders = PersonSkill.objects.filter(level=0, assessed_by_id="self-assessment").count()
    promoted = PersonSkill.objects.filter(is_self_assessed=True).count()
    promotable = sum(1 for p in Person.objects.all() if _seedable_skills(p)[0])
    print(
        f"  self-assessments: {assessed} of {Person.objects.count()} people, "
        f"{placeholders} unassessed claims, {promoted} promoted, "
        f"{promotable} people with something to promote"
    )


def main():
    sys.path.insert(0, str(DEMO_DIR))
    import expand
    from seed import guard_data_dir

    # Reading the real database here would only produce confusing "person does
    # not exist" errors, so fail with the same message seed.py gives.
    problem = guard_data_dir()
    if problem:
        print(f"demo/verify.py refused to run: {problem}", file=sys.stderr)
        return 2

    snapshot = expand.load_json(expand.SNAPSHOT_PATH)
    archetypes = expand.load_archetypes(DEMO_DIR)

    setup_django()

    failures = (
        check_counts(snapshot)
        + check_maturity(archetypes)
        + check_project_coverage()
        + check_key_person_risk()
        + check_self_assessments()
    )

    if failures:
        print(f"demo/verify.py: {len(failures)} problem(s):", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1

    summary()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
