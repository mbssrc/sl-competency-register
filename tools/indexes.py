"""Index generation module: produce reverse-index mappings from taxonomy data."""

import json
from collections import defaultdict


def load_json(path):
    with open(path) as f:
        return json.load(f)


def collect_skill_files(root):
    taxonomy = root / "taxonomy"
    results = []
    for p in taxonomy.rglob("*.json"):
        if p.name.startswith("_"):
            continue
        results.append(p)
    return sorted(results)


def write_index(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")
    print(f"GENERATED: {path}")


def run_generate_indexes(root):
    """Generate all reverse-index files in mappings/."""
    mappings_dir = root / "mappings"
    mappings_dir.mkdir(exist_ok=True)

    # Relationship reverse indexes
    requires_reverse = defaultdict(list)
    recommended_reverse = defaultdict(list)

    # Framework reverse indexes
    nice_index = defaultdict(list)
    sfia_index = defaultdict(list)
    crest_index = defaultdict(list)
    mitre_index = defaultdict(list)
    owasp_index = defaultdict(list)

    for path in collect_skill_files(root):
        try:
            data = load_json(path)
        except (json.JSONDecodeError, KeyError):
            print(f"WARNING: Could not read {path}")
            continue

        skill_id = data.get("id")
        if not skill_id:
            continue

        # Relationship inverses
        for req in data.get("requires", []):
            requires_reverse[req].append(skill_id)
        for rec in data.get("recommended", []):
            recommended_reverse[rec].append(skill_id)

        # Framework mappings
        fm = data.get("framework_mappings", {})

        if "nice" in fm:
            nice = fm["nice"]
            if isinstance(nice, dict):
                for role in nice.get("work_roles", []):
                    nice_index[role].append(skill_id)
                for tk in nice.get("tks", []):
                    nice_index[tk].append(skill_id)

        if "sfia" in fm:
            sfia = fm["sfia"]
            if isinstance(sfia, dict):
                skill_code = sfia.get("skill")
                if skill_code:
                    sfia_index[skill_code].append(skill_id)

        if "crest" in fm:
            crest = fm["crest"]
            if isinstance(crest, list):
                items = crest
            else:
                items = crest.get("areas", crest.get("syllabus", []))
            for item in items:
                crest_index[item].append(skill_id)

        # CREST CCT APP syllabus references, prefixed so they don't collide
        # with the area names above
        for item in fm.get("crest_cct_app", []):
            crest_index[f"CCT APP {item}"].append(skill_id)

        if "mitre_attack" in fm:
            mitre = fm["mitre_attack"]
            if isinstance(mitre, list):
                techs = mitre
            else:
                techs = mitre.get("techniques", [])
            for tech in techs:
                mitre_index[tech].append(skill_id)

        if "owasp" in fm:
            owasp = fm["owasp"]
            if isinstance(owasp, list):
                items = owasp
            else:
                items = owasp.get("top10", [])
            for item in items:
                owasp_index[item].append(skill_id)

    # Write all indexes
    write_index(mappings_dir / "requires-reverse.json", dict(requires_reverse))
    write_index(mappings_dir / "recommended-reverse.json", dict(recommended_reverse))
    write_index(mappings_dir / "nice.json", dict(nice_index))
    write_index(mappings_dir / "sfia.json", dict(sfia_index))
    write_index(mappings_dir / "crest.json", dict(crest_index))
    write_index(mappings_dir / "mitre-attack.json", dict(mitre_index))
    write_index(mappings_dir / "owasp.json", dict(owasp_index))

    print(f"\nGenerated 7 index files in {mappings_dir}/")
