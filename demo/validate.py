#!/usr/bin/env python3
"""Check the committed demo snapshot before it is seeded.

Runs without Django: it reads the JSON tree directly, so a stale or
inconsistent snapshot is caught before any database is touched.
"""

import sys
from pathlib import Path

import expand

LEVEL_MIN, LEVEL_MAX = 0, 5

PROJECT_MARKER = "Project: "
FINISHED_STATUSES = expand.FINISHED_STATUSES


def _rows(snapshot):
    """Every (person, skill row) pair in the snapshot."""
    for person in snapshot["people"]:
        for row in person["skills"]:
            yield person, row


def check_known_skills(snapshot, skill_ids):
    """Every skill referenced anywhere must exist in the taxonomy."""
    errors = []
    for person, row in _rows(snapshot):
        if row["skill"] not in skill_ids:
            errors.append(
                f"{person['id']} ({person['name']}): skill '{row['skill']}' is not in the taxonomy"
            )
    for person in snapshot["people"]:
        for target in person.get("development_plan", []):
            if target["skill"] not in skill_ids:
                errors.append(
                    f"{person['id']} ({person['name']}): development plan skill "
                    f"'{target['skill']}' is not in the taxonomy"
                )
    for project in snapshot["projects"]:
        for comp in project["required_competencies"]:
            if comp["skill"] not in skill_ids:
                errors.append(
                    f"{project['id']}: required skill '{comp['skill']}' is not in the taxonomy"
                )
    return errors


def check_levels_in_range(snapshot):
    """Levels must sit on the 0-5 proficiency scale the model defines."""
    errors = []
    for person, row in _rows(snapshot):
        if not LEVEL_MIN <= row["level"] <= LEVEL_MAX:
            errors.append(
                f"{person['id']} ({person['name']}): {row['skill']} has level "
                f"{row['level']}, outside {LEVEL_MIN}-{LEVEL_MAX}"
            )
    for person in snapshot["people"]:
        for target in person.get("development_plan", []):
            for field in ("current_level", "target_level"):
                if not LEVEL_MIN <= target[field] <= LEVEL_MAX:
                    errors.append(
                        f"{person['id']} ({person['name']}): development plan "
                        f"{target['skill']} {field}={target[field]} is out of range"
                    )
    return errors


def check_evidence_markers(snapshot):
    """A cited project must be finished and must have required the skill.

    The application only ever writes a "Project: X" marker when completing X's
    assessment matrix, so seeded history that cites a planned project, or a
    project that never required the skill, is history that could not have
    happened.
    """
    by_name = {p["name"]: p for p in snapshot["projects"]}
    errors = []
    for person, row in _rows(snapshot):
        for line in (row.get("evidence_notes") or "").splitlines():
            if not line.startswith(PROJECT_MARKER):
                continue
            name = line[len(PROJECT_MARKER) :]
            project = by_name.get(name)
            where = f"{person['id']} ({person['name']}) {row['skill']}"
            if project is None:
                errors.append(f"{where}: cites unknown project '{name}'")
                continue
            if project["status"] not in FINISHED_STATUSES:
                errors.append(
                    f"{where}: cites '{name}', which is not finished (status {project['status']})"
                )
                continue
            if not any(c["skill"] == row["skill"] for c in project["required_competencies"]):
                errors.append(f"{where}: cites '{name}', which did not require that skill")
    return errors


def check_prerequisites(snapshot, taxonomy):
    """A held skill's prerequisites must be held too, one level below at least."""
    errors = []
    for person in snapshot["people"]:
        levels = {row["skill"]: row["level"] for row in person["skills"]}
        for skill_id, level in sorted(levels.items()):
            if level < expand.PREREQ_FLOOR:
                continue
            skill = taxonomy.skills.get(skill_id)
            if skill is None:
                continue
            for prereq in skill.requires:
                if prereq not in taxonomy.skills:
                    continue
                required = max(level - 1, expand.PREREQ_FLOOR)
                held = levels.get(prereq)
                if held is None:
                    errors.append(
                        f"{person['id']} ({person['name']}): {skill_id} at L{level} "
                        f"but prerequisite {prereq} is not held"
                    )
                elif held < required:
                    errors.append(
                        f"{person['id']} ({person['name']}): {skill_id} at L{level} "
                        f"but prerequisite {prereq} is only L{held} (needs L{required})"
                    )
    return errors


def check_never_absent(snapshot, archetypes):
    """A skill an archetype marks 'never' must not appear in the expansion."""
    by_key = {a["key"]: a for a in archetypes}
    errors = []
    for person in snapshot["people"]:
        never = set(by_key[person["id"]].get("never", []))
        for row in person["skills"]:
            if row["skill"] in never:
                errors.append(
                    f"{person['id']} ({person['name']}): {row['skill']} is listed "
                    f"in 'never' but appears in the expansion"
                )
    return errors


def check_development_plans(snapshot):
    """A plan's current_level must match the level the person actually holds."""
    errors = []
    for person in snapshot["people"]:
        levels = {row["skill"]: row["level"] for row in person["skills"]}
        for target in person.get("development_plan", []):
            held = levels.get(target["skill"], 0)
            if target["current_level"] != held:
                errors.append(
                    f"{person['id']} ({person['name']}): development plan for "
                    f"{target['skill']} says current L{target['current_level']}, "
                    f"but the person holds L{held}"
                )
            if target["target_level"] <= held:
                errors.append(
                    f"{person['id']} ({person['name']}): development plan for "
                    f"{target['skill']} targets L{target['target_level']}, "
                    f"which is not above the held L{held}"
                )
    return errors


def check_schema(snapshot, repo_root):
    """Validate each person record against the repository's person schema."""
    try:
        import jsonschema
    except ImportError:
        return ["jsonschema is not installed; cannot validate the person schema"]

    schema = expand.load_json(Path(repo_root) / "schema" / "person.schema.json")
    validator = jsonschema.Draft202012Validator(schema)
    errors = []
    for person in snapshot["people"]:
        for error in validator.iter_errors(person):
            path = "/".join(str(part) for part in error.absolute_path)
            errors.append(f"{person['id']}: schema: {path or '<root>'}: {error.message}")
    return errors


def check_snapshot_is_current(repo_root, demo_dir):
    """The committed snapshot must match what the archetypes expand to now."""
    path = Path(demo_dir) / "generated" / "population.json"
    if not path.exists():
        return [f"{path} is missing; run: python demo/expand.py"]
    expected = expand.render(expand.expand_all(repo_root, demo_dir, expand.REFERENCE_DATE))
    if path.read_text() != expected:
        return [
            f"{path} is stale: the archetypes have changed since it was "
            f"generated. Run: python demo/expand.py"
        ]
    return []


def run(repo_root, demo_dir):
    """Every check, in cheapest-first order. Returns a list of error strings."""
    errors = list(check_snapshot_is_current(repo_root, demo_dir))
    if errors:
        return errors

    snapshot = expand.load_json(Path(demo_dir) / "generated" / "population.json")
    taxonomy = expand.load_taxonomy(repo_root)
    archetypes = expand.load_archetypes(demo_dir)
    skill_ids = set(taxonomy.skills)

    errors += check_schema(snapshot, repo_root)
    errors += check_known_skills(snapshot, skill_ids)
    errors += check_levels_in_range(snapshot)
    errors += check_evidence_markers(snapshot)
    errors += check_prerequisites(snapshot, taxonomy)
    errors += check_never_absent(snapshot, archetypes)
    errors += check_development_plans(snapshot)
    return errors


def main():
    errors = run(expand.REPO_ROOT, expand.DEMO_DIR)
    if errors:
        print(f"demo/validate.py: {len(errors)} problem(s):", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    snapshot = expand.load_json(expand.SNAPSHOT_PATH)
    rows = sum(len(p["skills"]) for p in snapshot["people"])
    print(
        f"Demo data is valid: {len(snapshot['people'])} people, {rows} assessments, "
        f"{len(snapshot['projects'])} projects."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
