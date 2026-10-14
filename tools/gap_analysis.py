"""Gap analysis module: person vs. profile and service readiness."""

import json


def load_json(path):
    with open(path) as f:
        return json.load(f)


def collect_files(root, directory):
    d = root / directory
    if not d.exists():
        return []
    return sorted(
        p
        for p in d.glob("*.json")
        if not p.name.startswith("_") and p.name != "person-template.json"
    )


def load_skill_names(root):
    names = {}
    taxonomy = root / "taxonomy"
    for p in taxonomy.rglob("*.json"):
        if p.name.startswith("_"):
            continue
        data = load_json(p)
        names[data["id"]] = data["name"]
    return names


def compute_gap_analysis(root):
    """Compute gaps: person vs. each assigned profile."""
    skill_names = load_skill_names(root)

    # Load profiles
    profiles = {}
    for path in collect_files(root, "profiles"):
        data = load_json(path)
        # Key by filename without extension (matches progression references)
        key = path.stem
        profiles[key] = data

    # Load personnel
    gaps = []
    for path in collect_files(root, "personnel"):
        person = load_json(path)
        person_skills = {s["skill"]: s["level"] for s in person.get("skills", [])}

        for profile_ref in person.get("profiles", []):
            profile = profiles.get(profile_ref)
            if not profile:
                continue

            for comp in profile.get("competencies", []):
                skill_id = comp["skill"]
                required = comp["minimum_level"]
                current = person_skills.get(skill_id, 0)
                gap = max(0, required - current)

                if gap > 0:
                    gaps.append(
                        {
                            "person": person["id"],
                            "person_name": person["name"],
                            "profile": profile["name"],
                            "skill": skill_id,
                            "skill_name": skill_names.get(skill_id, ""),
                            "required_level": required,
                            "current_level": current,
                            "gap": gap,
                            "criticality": comp.get("criticality", "important"),
                        }
                    )

    gaps.sort(key=lambda g: (g["person"], g["profile"], -g["gap"], g["skill"]))
    return gaps


def compute_service_readiness(root):
    """Compute which personnel qualify for each service's required skills."""
    # Load personnel skill levels
    personnel = []
    for path in collect_files(root, "personnel"):
        personnel.append(load_json(path))

    readiness = []
    for path in collect_files(root, "services"):
        service = load_json(path)
        for comp in service.get("required_competencies", []):
            skill_id = comp["skill"]
            min_level = comp["minimum_level"]

            qualified = []
            for person in personnel:
                for s in person.get("skills", []):
                    if s["skill"] == skill_id and s["level"] >= min_level:
                        qualified.append(f"{person['id']} ({person['name']})")
                        break

            readiness.append(
                {
                    "service": service["name"],
                    "service_id": service["id"],
                    "skill": skill_id,
                    "required_level": min_level,
                    "qualified_personnel": qualified,
                }
            )

    return readiness


def compute_summary(root):
    """Compute summary statistics per person per profile."""
    profiles = {}
    for path in collect_files(root, "profiles"):
        profiles[path.stem] = load_json(path)

    summaries = []
    for path in collect_files(root, "personnel"):
        person = load_json(path)
        person_skills = {s["skill"]: s["level"] for s in person.get("skills", [])}

        for profile_ref in person.get("profiles", []):
            profile = profiles.get(profile_ref)
            if not profile:
                continue

            comps = profile.get("competencies", [])
            essential = [c for c in comps if c.get("criticality") == "essential"]
            important = [c for c in comps if c.get("criticality") == "important"]

            essential_met = sum(
                1 for c in essential if person_skills.get(c["skill"], 0) >= c["minimum_level"]
            )
            important_met = sum(
                1 for c in important if person_skills.get(c["skill"], 0) >= c["minimum_level"]
            )

            summaries.append(
                {
                    "person": person["id"],
                    "person_name": person["name"],
                    "profile": profile["name"],
                    "essential_total": len(essential),
                    "essential_met": essential_met,
                    "essential_pct": round(100 * essential_met / len(essential))
                    if essential
                    else 100,
                    "important_total": len(important),
                    "important_met": important_met,
                    "important_pct": round(100 * important_met / len(important))
                    if important
                    else 100,
                }
            )

    return summaries


def run_gap_analysis(root, args):
    """Entry point from CLI."""
    if args.type == "gaps":
        gaps = compute_gap_analysis(root)
        if not gaps:
            print("No gaps found (or no personnel records).")
            return
        print(
            f"{'Person':<12} {'Profile':<30} {'Skill':<25} {'Required':>8} {'Current':>8} {'Gap':>4} {'Criticality'}"
        )
        print("-" * 100)
        for g in gaps:
            print(
                f"{g['person']:<12} {g['profile']:<30} {g['skill']:<25} {g['required_level']:>8} {g['current_level']:>8} {g['gap']:>4} {g['criticality']}"
            )

    elif args.type == "readiness":
        readiness = compute_service_readiness(root)
        current_svc = None
        for r in readiness:
            if r["service"] != current_svc:
                current_svc = r["service"]
                print(f"\n{'=' * 60}")
                print(f"Service: {current_svc}")
                print(f"{'=' * 60}")
            qualified = (
                ", ".join(r["qualified_personnel"]) if r["qualified_personnel"] else "** NONE **"
            )
            print(f"  {r['skill']:<30} (L{r['required_level']}): {qualified}")

    elif args.type == "summary":
        summaries = compute_summary(root)
        if not summaries:
            print("No personnel records with assigned profiles.")
            return
        print(f"{'Person':<12} {'Profile':<30} {'Essential':>12} {'Important':>12}")
        print("-" * 70)
        for s in summaries:
            ess = f"{s['essential_met']}/{s['essential_total']} ({s['essential_pct']}%)"
            imp = f"{s['important_met']}/{s['important_total']} ({s['important_pct']}%)"
            print(f"{s['person']:<12} {s['profile']:<30} {ess:>12} {imp:>12}")
