"""Scaffold module: generate skeleton JSON files from minimal input."""

import json


def load_json(path):
    with open(path) as f:
        return json.load(f)


def load_meta(root):
    """Load taxonomy _meta.json for default proficiency templates."""
    return load_json(root / "taxonomy" / "_meta.json")


def default_proficiency(meta):
    """Build default proficiency levels from _meta.json templates."""
    prof = {}
    for level, info in meta["proficiency_model"]["levels"].items():
        entry = {
            "label": info["label"],
            "description": info["description"],
        }
        if info.get("default_evidence"):
            entry["evidence"] = list(info["default_evidence"])
        if info.get("authorization_required"):
            entry["authorization"] = True
        prof[level] = entry
    return prof


def write_json(path, data):
    """Write JSON to file, refusing to overwrite."""
    if path.exists():
        print(f"SKIP: {path} already exists")
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    print(f"CREATED: {path}")
    return True


def resolve_category_name(root, domain, category_dir):
    """Resolve a category directory name to its display name from _domain.json."""
    domain_path = root / "taxonomy" / domain / "_domain.json"
    if domain_path.exists():
        domain_data = load_json(domain_path)
        for cat in domain_data.get("categories", []):
            cat_dir = (
                cat["name"]
                .lower()
                .replace(" ", "-")
                .replace("&", "")
                .replace("(", "")
                .replace(")", "")
                .replace("--", "-")
                .strip("-")
            )
            if cat_dir == category_dir or cat["id"].lower().replace("_", "-").endswith(
                category_dir
            ):
                return cat["name"]
    return category_dir


def scaffold_skill(root, skill_id, name, domain, category):
    """Create a skeleton skill file."""
    meta = load_meta(root)
    filename = name.lower().replace(" ", "-").replace("/", "-") + ".json"
    path = root / "taxonomy" / domain / category / filename
    category_display = resolve_category_name(root, domain, category)

    data = {
        "id": skill_id,
        "name": name,
        "domain": domain,
        "category": category_display,
        "status": "active",
        "description": f"TODO: Describe {name}",
        "requires": [],
        "recommended": [],
        "proficiency": default_proficiency(meta),
        "assessment_methods": [],
        "framework_mappings": {},
        "tags": [],
    }
    return write_json(path, data)


def scaffold_profile(root, profile_id, name):
    """Create a skeleton profile file."""
    filename = name.lower().replace(" ", "-").replace("/", "-") + ".json"
    path = root / "profiles" / filename

    data = {
        "id": profile_id,
        "name": name,
        "description": f"TODO: Describe {name}",
        "requirements": {
            "education": [],
            "qualifications": [],
            "experience": {"minimum_years": 0, "description": "TODO"},
        },
        "competencies": [
            {
                "skill": "FOUND-REPORT",
                "minimum_level": 2,
                "criticality": "essential",
            }
        ],
        "progression": {},
    }
    return write_json(path, data)


def scaffold_service(root, service_id, name):
    """Create a skeleton service file."""
    filename = name.lower().replace(" ", "-").replace("/", "-") + ".json"
    path = root / "services" / filename

    data = {
        "id": service_id,
        "name": name,
        "description": f"TODO: Describe {name}",
        "scope_reference": "",
        "required_competencies": [
            {
                "skill": "FOUND-REPORT",
                "minimum_level": 3,
            }
        ],
        "standards": [],
    }
    return write_json(path, data)


def scaffold_batch(root, domain, category, batch_file):
    """Scaffold multiple skills from a batch file (id|name per line)."""
    count = 0
    with open(batch_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("|", 1)
            if len(parts) != 2:
                print(f"SKIP: Invalid line format (expected 'id|name'): {line}")
                continue
            skill_id, name = parts[0].strip(), parts[1].strip()
            if scaffold_skill(root, skill_id, name, domain, category):
                count += 1
    print(f"\nScaffolded {count} skill(s)")


def run_scaffold(root, args):
    """Entry point from CLI."""
    if args.type == "skill":
        if args.batch:
            scaffold_batch(root, args.domain, args.category, args.batch)
        else:
            scaffold_skill(root, args.id, args.name, args.domain, args.category)
    elif args.type == "profile":
        scaffold_profile(root, args.id, args.name)
    elif args.type == "service":
        scaffold_service(root, args.id, args.name)
