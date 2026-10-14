"""Validation module: schema validation, reference integrity, DAG cycle detection."""

import json
import re
from collections import defaultdict

try:
    import jsonschema
except ImportError:
    jsonschema = None


def load_json(path):
    with open(path) as f:
        return json.load(f)


def collect_files(root, directory, pattern="*.json"):
    """Collect all JSON files in a directory tree, skipping _meta.json and _domain.json."""
    d = root / directory
    if not d.exists():
        return []
    return sorted(d.rglob(pattern))


def collect_skill_files(root):
    taxonomy = root / "taxonomy"
    results = []
    for p in taxonomy.rglob("*.json"):
        if p.name.startswith("_"):
            continue
        results.append(p)
    return sorted(results)


def collect_domain_files(root):
    """Collect all _domain.json files in the taxonomy."""
    taxonomy = root / "taxonomy"
    results = []
    for p in taxonomy.rglob("_domain.json"):
        results.append(p)
    return sorted(results)


def collect_typed_files(root, directory, prefix=None):
    d = root / directory
    if not d.exists():
        return []
    results = []
    for p in sorted(d.glob("*.json")):
        if p.name.startswith("_") or p.name == "person-template.json":
            continue
        results.append(p)
    return results


def validate_schema(files, schema, label):
    """Validate files against a JSON Schema. Returns list of error strings."""
    errors = []
    if jsonschema is None:
        errors.append(f"WARNING: jsonschema not installed, skipping {label} schema validation")
        return errors
    for path in files:
        try:
            data = load_json(path)
        except json.JSONDecodeError as e:
            errors.append(f"ERROR [{label}] {path}: Invalid JSON: {e}")
            continue
        try:
            jsonschema.validate(data, schema)
        except jsonschema.ValidationError as e:
            errors.append(f"ERROR [{label}] {path}: {e.message} (at {e.json_path})")
    return errors


def collect_all_skill_ids(root):
    """Return a set of all skill IDs in the taxonomy."""
    ids = {}
    for path in collect_skill_files(root):
        try:
            data = load_json(path)
        except (json.JSONDecodeError, KeyError):
            continue
        skill_id = data.get("id")
        if skill_id:
            if skill_id in ids:
                ids[skill_id].append(path)
            else:
                ids[skill_id] = [path]
    return ids


def check_id_uniqueness(skill_ids):
    """Check for duplicate skill IDs."""
    errors = []
    for sid, paths in skill_ids.items():
        if len(paths) > 1:
            locations = ", ".join(str(p) for p in paths)
            errors.append(f"ERROR [uniqueness] Duplicate skill ID '{sid}' in: {locations}")
    return errors


def check_reference_integrity(root, skill_id_set):
    """Check that all skill ID references resolve to existing skills."""
    errors = []

    # Check requires/recommended in skills
    for path in collect_skill_files(root):
        try:
            data = load_json(path)
        except (json.JSONDecodeError, KeyError):
            continue
        for field in ("requires", "recommended"):
            for ref in data.get(field, []):
                if ref not in skill_id_set:
                    errors.append(f"ERROR [ref] {path}: {field} references unknown skill '{ref}'")
        if data.get("superseded_by") and data["superseded_by"] not in skill_id_set:
            errors.append(
                f"ERROR [ref] {path}: superseded_by references unknown skill '{data['superseded_by']}'"
            )

    # Check skill refs in profiles
    for path in collect_typed_files(root, "profiles"):
        try:
            data = load_json(path)
        except (json.JSONDecodeError, KeyError):
            continue
        for level, pin in iter_pinned(data):
            ref = pin.get("skill")
            if ref and ref not in skill_id_set:
                errors.append(
                    f"ERROR [ref] {path}: {level} pinned skill references unknown skill '{ref}'"
                )

    # Check skill refs in services
    for path in collect_typed_files(root, "services"):
        try:
            data = load_json(path)
        except (json.JSONDecodeError, KeyError):
            continue
        for comp in data.get("required_competencies", []):
            ref = comp.get("skill")
            if ref and ref not in skill_id_set:
                errors.append(
                    f"ERROR [ref] {path}: required_competencies references unknown skill '{ref}'"
                )

    # Check skill refs in personnel
    for path in collect_typed_files(root, "personnel"):
        try:
            data = load_json(path)
        except (json.JSONDecodeError, KeyError):
            continue
        for entry in data.get("skills", []):
            ref = entry.get("skill")
            if ref and ref not in skill_id_set:
                errors.append(
                    f"ERROR [ref] {path}: skill assessment references unknown skill '{ref}'"
                )
        for entry in data.get("development_plan", []):
            ref = entry.get("skill")
            if ref and ref not in skill_id_set:
                errors.append(
                    f"ERROR [ref] {path}: development_plan references unknown skill '{ref}'"
                )

    return errors


def domain_prefixes(root):
    """Skill ID prefixes, taken from the domain IDs in taxonomy/_meta.json."""
    try:
        meta = load_json(root / "taxonomy" / "_meta.json")
    except (json.JSONDecodeError, OSError):
        return set()
    return {d["id"] for d in meta.get("domains", []) if d.get("id")}


# Keys already covered by check_reference_integrity, or holding external
# framework identifiers and tags rather than human-readable prose.
NON_PROSE_KEYS = frozenset(
    {"id", "requires", "recommended", "superseded_by", "framework_mappings", "tags"}
)


def iter_prose(data):
    """Yield every prose string in a skill, skipping non-prose keys."""
    if isinstance(data, dict):
        for key, value in data.items():
            if key not in NON_PROSE_KEYS:
                yield from iter_prose(value)
    elif isinstance(data, list):
        for item in data:
            yield from iter_prose(item)
    elif isinstance(data, str):
        yield data


def check_prose_references(root, skill_id_set):
    """Skill IDs cited in prose must resolve to an existing skill.

    Descriptions carry boundary statements ("... belongs to HWSEC-PCB-BUS")
    that readers follow like links. check_reference_integrity only inspects
    requires/recommended, so an ID that is renamed, deprecated away or never
    written stays broken in prose and silently misdirects whoever follows it.
    """
    errors = []
    prefixes = domain_prefixes(root)
    if not prefixes:
        return errors
    pattern = re.compile(r"\b(?:" + "|".join(sorted(prefixes)) + r")-[A-Z0-9]+(?:-[A-Z0-9]+)*\b")
    for path in collect_skill_files(root):
        try:
            data = load_json(path)
        except (json.JSONDecodeError, KeyError):
            continue
        own_id = data.get("id")
        reported = set()
        for text in iter_prose(data):
            for ref in pattern.findall(text):
                if ref == own_id or ref in skill_id_set or ref in reported:
                    continue
                reported.add(ref)
                errors.append(f"ERROR [prose-ref] {path}: prose cites unknown skill '{ref}'")
    return errors


MATURITY_LEVELS = ("junior", "practitioner", "senior", "lead", "principal")


def iter_pinned(profile):
    """Yield (level, pin) for every pinned skill across a profile's maturity levels."""
    for level, level_def in (profile.get("maturity_levels") or {}).items():
        for pin in level_def.get("pinned", []):
            yield level, pin


def check_categories(root):
    """Each skill's category must name a category in its domain's _domain.json.

    Maturity thresholds count distinct category strings, so a mismatch
    silently inflates or deflates a person's category coverage.
    """
    errors = []
    names_by_dir = {}
    for path in collect_domain_files(root):
        try:
            data = load_json(path)
        except (json.JSONDecodeError, KeyError):
            continue
        names_by_dir[path.parent.name] = {c["name"] for c in data.get("categories", [])}
    for path in collect_skill_files(root):
        try:
            data = load_json(path)
        except (json.JSONDecodeError, KeyError):
            continue
        names = names_by_dir.get(data.get("domain"), set())
        if data.get("category") not in names:
            errors.append(
                f"ERROR [category] {path}: category '{data.get('category')}' is not defined "
                f"in {data.get('domain')}/_domain.json"
            )
    return errors


def check_profile_thresholds(root):
    """Profile thresholds must be achievable and must not loosen as seniority rises.

    Levels are evaluated independently and the highest passing level wins, so a
    senior level that is easier than a junior one ranks people out of order.
    """
    errors = []
    meta = load_json(root / "taxonomy" / "_meta.json")
    dir_by_id = {d["id"]: d["directory"] for d in meta.get("domains", [])}
    skill_count = defaultdict(int)
    categories = defaultdict(set)
    for path in collect_skill_files(root):
        try:
            data = load_json(path)
        except (json.JSONDecodeError, KeyError):
            continue
        # Deprecated skills can no longer be earned, so they cannot satisfy a threshold.
        if data.get("status", "active") != "active":
            continue
        skill_count[data.get("domain")] += 1
        categories[data.get("domain")].add(data.get("category"))

    def at_least(dsa, level):
        """Skills required at `level` or above, given a domain_skills_at map."""
        return max([n for lv, n in dsa.items() if int(lv) >= level] or [0])

    for path in collect_typed_files(root, "profiles"):
        try:
            data = load_json(path)
        except (json.JSONDecodeError, KeyError):
            continue
        domain_dir = dir_by_id.get(data.get("domain"))
        if domain_dir is None:
            errors.append(f"ERROR [profile] {path}: unknown domain '{data.get('domain')}'")
            continue
        n_skills = skill_count[domain_dir]
        n_cats = len(categories[domain_dir])
        levels = data.get("maturity_levels") or {}
        previous = None
        for name in MATURITY_LEVELS:
            if name not in levels:
                continue
            thresholds = levels[name].get("thresholds", {})
            dsa = thresholds.get("domain_skills_at", {})
            for lv, n in dsa.items():
                if n > n_skills:
                    errors.append(
                        f"ERROR [profile] {path}: {name} needs {n} skills at level {lv}+ "
                        f"but the domain has {n_skills}"
                    )
            if thresholds.get("min_categories", 0) > n_cats:
                errors.append(
                    f"ERROR [profile] {path}: {name} needs {thresholds['min_categories']} "
                    f"categories but the domain has {n_cats}"
                )
            if previous:
                prev_name, prev_t = previous
                prev_dsa = prev_t.get("domain_skills_at", {})
                for lv in range(1, 6):
                    if at_least(dsa, lv) < at_least(prev_dsa, lv):
                        errors.append(
                            f"ERROR [profile] {path}: {name} requires fewer skills at level "
                            f"{lv}+ ({at_least(dsa, lv)}) than {prev_name} ({at_least(prev_dsa, lv)})"
                        )
                for key in ("min_categories", "foundation_avg"):
                    if thresholds.get(key, 0) < prev_t.get(key, 0):
                        errors.append(
                            f"ERROR [profile] {path}: {name} {key} is lower than {prev_name}"
                        )
            previous = (name, thresholds)
    return errors


def check_dag_cycles(root):
    """Check for circular dependencies in the requires graph."""
    errors = []
    graph = defaultdict(set)

    for path in collect_skill_files(root):
        try:
            data = load_json(path)
        except (json.JSONDecodeError, KeyError):
            continue
        skill_id = data.get("id")
        if not skill_id:
            continue
        for req in data.get("requires", []):
            graph[skill_id].add(req)

    # Topological sort via DFS
    WHITE, GRAY, BLACK = 0, 1, 2
    color = defaultdict(int)
    cycle_nodes = []

    def dfs(node, path):
        color[node] = GRAY
        path.append(node)
        for neighbor in graph.get(node, []):
            if color[neighbor] == GRAY:
                cycle_start = path.index(neighbor)
                cycle = path[cycle_start:] + [neighbor]
                cycle_nodes.append(cycle)
            elif color[neighbor] == WHITE:
                dfs(neighbor, path)
        path.pop()
        color[node] = BLACK

    all_nodes = set(graph.keys())
    for edges in graph.values():
        all_nodes.update(edges)

    for node in all_nodes:
        if color[node] == WHITE:
            dfs(node, [])

    for cycle in cycle_nodes:
        errors.append(f"ERROR [dag] Circular dependency: {' -> '.join(cycle)}")

    return errors


def check_warnings(root, skill_id_set, stale_days=365):
    """Generate warnings (non-blocking)."""
    warnings = []

    # Orphan skills: not required by any service nor pinned by any profile.
    # Profiles otherwise cover their whole domain through thresholds.
    referenced_skills = set()
    for path in collect_typed_files(root, "profiles"):
        try:
            data = load_json(path)
        except (json.JSONDecodeError, KeyError):
            continue
        for _, pin in iter_pinned(data):
            referenced_skills.add(pin.get("skill"))
    for path in collect_typed_files(root, "services"):
        try:
            data = load_json(path)
        except (json.JSONDecodeError, KeyError):
            continue
        for comp in data.get("required_competencies", []):
            referenced_skills.add(comp.get("skill"))

    orphans = skill_id_set - referenced_skills
    if orphans:
        for sid in sorted(orphans):
            warnings.append(
                f"WARNING [orphan] Skill '{sid}' not required by any service or pinned by any profile"
            )

    # Deprecated skills still referenced
    for path in collect_skill_files(root):
        try:
            data = load_json(path)
        except (json.JSONDecodeError, KeyError):
            continue
        if data.get("status") == "deprecated" and data.get("id") in referenced_skills:
            warnings.append(
                f"WARNING [deprecated] Deprecated skill '{data['id']}' is still referenced by profiles/services"
            )

    # Stale assessments: personnel skill entries older than threshold
    from datetime import date, timedelta

    cutoff = date.today() - timedelta(days=stale_days)
    for path in collect_typed_files(root, "personnel"):
        try:
            data = load_json(path)
        except (json.JSONDecodeError, KeyError):
            continue
        person_id = data.get("id", path.stem)
        for entry in data.get("skills", []):
            assessed = entry.get("assessed_date")
            if assessed:
                try:
                    assessed_date = date.fromisoformat(assessed)
                    if assessed_date < cutoff:
                        warnings.append(
                            f"WARNING [stale] {person_id}: skill '{entry['skill']}' last assessed {assessed} (>{stale_days} days ago)"
                        )
                except ValueError:
                    pass

    # Domains without a maturity profile
    profile_domains = set()
    for path in collect_typed_files(root, "profiles"):
        try:
            profile_domains.add(load_json(path).get("domain"))
        except (json.JSONDecodeError, KeyError):
            continue
    for path in collect_domain_files(root):
        try:
            domain_id = load_json(path).get("id")
        except (json.JSONDecodeError, KeyError):
            continue
        # Foundations are measured inside every other ladder (foundation_avg, pins).
        if domain_id not in profile_domains and domain_id != "FOUND":
            warnings.append(f"WARNING [coverage] Domain '{domain_id}' has no maturity profile")

    return warnings


def run_validate(root, warnings=True):
    """Run all validation checks. Returns exit code (0=ok, 1=errors)."""
    all_errors = []
    all_warnings = []

    # Load schemas
    schema_dir = root / "schema"
    schemas = {}
    for name in ("skill", "profile", "service", "person", "domain"):
        schema_path = schema_dir / f"{name}.schema.json"
        if schema_path.exists():
            schemas[name] = load_json(schema_path)

    # Schema validation
    if "skill" in schemas:
        all_errors.extend(validate_schema(collect_skill_files(root), schemas["skill"], "skill"))
    if "domain" in schemas:
        all_errors.extend(validate_schema(collect_domain_files(root), schemas["domain"], "domain"))
    if "profile" in schemas:
        all_errors.extend(
            validate_schema(collect_typed_files(root, "profiles"), schemas["profile"], "profile")
        )
    if "service" in schemas:
        all_errors.extend(
            validate_schema(collect_typed_files(root, "services"), schemas["service"], "service")
        )
    if "person" in schemas:
        all_errors.extend(
            validate_schema(collect_typed_files(root, "personnel"), schemas["person"], "person")
        )

    # ID uniqueness + reference integrity + DAG
    skill_ids = collect_all_skill_ids(root)
    skill_id_set = set(skill_ids.keys())
    all_errors.extend(check_id_uniqueness(skill_ids))
    all_errors.extend(check_reference_integrity(root, skill_id_set))
    all_errors.extend(check_prose_references(root, skill_id_set))
    all_errors.extend(check_dag_cycles(root))
    all_errors.extend(check_categories(root))
    all_errors.extend(check_profile_thresholds(root))

    # Warnings
    if warnings:
        all_warnings = check_warnings(root, skill_id_set)

    # Report
    for msg in all_errors:
        print(msg)
    for msg in all_warnings:
        print(msg)

    error_count = len([e for e in all_errors if e.startswith("ERROR")])
    warning_count = len(all_warnings)

    print(f"\n{'=' * 60}")
    if error_count == 0 and warning_count == 0:
        print(f"Validation passed. {len(skill_id_set)} skills found.")
    elif error_count == 0:
        print(
            f"Validation passed with {warning_count} warning(s). {len(skill_id_set)} skills found."
        )
    else:
        print(f"Validation FAILED: {error_count} error(s), {warning_count} warning(s).")

    return 1 if error_count > 0 else 0
