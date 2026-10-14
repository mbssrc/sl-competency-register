"""Domain maturity analysis, service readiness, and project staffing services."""

from django.db.models import Q

from apps.taxonomy.models import Profile, Service, Skill

from .models import PersonSkill

MATURITY_LEVELS_ORDERED = ["junior", "practitioner", "senior", "lead", "principal"]

# Lowest level at which a held skill counts towards category breadth.
CATEGORY_MIN_LEVEL = 2


def compute_domain_maturity(person, profile):
    """Compute a person's maturity level within a domain based on threshold rules.

    Args:
        person: Person instance with skills relation.
        profile: Profile instance with maturity_levels JSONField and domain FK.

    Returns:
        dict with level, level_index, title, next_level, next_gaps, and detail.
    """
    maturity_levels = profile.maturity_levels or {}
    domain_id = profile.domain_id  # e.g. "HWSEC"

    # --- Query once, reuse everywhere ---
    # Self-assessments are advisory: only management-assessed levels count.
    person_skills = list(person.skills.filter(is_self_assessed=False))
    person_skill_map = {ps.skill_id: ps.level for ps in person_skills}
    person_skill_ids = set(person_skill_map.keys())

    # Taxonomy lookup: get domain_id and category for every skill the person has
    taxonomy_skills = Skill.objects.using("taxonomy").filter(id__in=person_skill_ids)
    skill_info = {s.id: s for s in taxonomy_skills}

    # --- Domain skill analysis ---
    domain_skill_levels = []  # levels of person skills that belong to this domain
    categories_covered = set()

    for skill_id, level in person_skill_map.items():
        info = skill_info.get(skill_id)
        if info and info.domain_id == domain_id:
            domain_skill_levels.append(level)
            # Breadth means supervised practice, not awareness.
            if info.category and level >= CATEGORY_MIN_LEVEL:
                categories_covered.add(info.category)

    # --- Foundation average ---
    # Averaged over every active Foundations skill, unassessed ones as 0, so a
    # single strong skill cannot stand in for the whole set.
    active_foundations = list(
        Skill.objects.using("taxonomy")
        .filter(domain_id="FOUND", status="active")
        .values_list("id", flat=True)
    )
    foundation_avg = (
        sum(person_skill_map.get(sid, 0) for sid in active_foundations) / len(active_foundations)
        if active_foundations
        else 0.0
    )

    detail = {
        "domain_skill_count": len(domain_skill_levels),
        "categories_covered": len(categories_covered),
        "category_names": sorted(categories_covered),
        "foundation_avg": round(foundation_avg, 2),
    }

    # --- Check each maturity level in order ---
    achieved_level = None
    achieved_index = -1

    for idx, level_key in enumerate(MATURITY_LEVELS_ORDERED):
        level_def = maturity_levels.get(level_key)
        if level_def is None:
            continue

        thresholds = level_def.get("thresholds", {})
        pinned = level_def.get("pinned", [])

        if _check_thresholds(
            thresholds,
            pinned,
            domain_skill_levels,
            categories_covered,
            foundation_avg,
            person_skill_map,
        ):
            achieved_level = level_key
            achieved_index = idx

    # --- Build result ---
    if achieved_level is not None:
        title = maturity_levels[achieved_level].get("title", achieved_level)
    else:
        title = None

    # Determine next level
    next_level = None
    next_gaps = None
    if achieved_index < len(MATURITY_LEVELS_ORDERED) - 1:
        next_idx = achieved_index + 1
        next_key = MATURITY_LEVELS_ORDERED[next_idx]
        next_def = maturity_levels.get(next_key)
        if next_def is not None:
            next_level = next_key
            next_gaps = _compute_gaps(
                next_key,
                next_def,
                domain_skill_levels,
                categories_covered,
                foundation_avg,
                person_skill_map,
            )

    return {
        "level": achieved_level,
        "level_index": achieved_index,
        "title": title,
        "next_level": next_level,
        "next_gaps": next_gaps,
        "detail": detail,
    }


def _check_thresholds(
    thresholds,
    pinned,
    domain_skill_levels,
    categories_covered,
    foundation_avg,
    person_skill_map,
):
    """Check whether ALL thresholds for a maturity level are met."""
    # domain_skills_at: {"3": 8} means >= 8 domain skills at level 3+
    domain_skills_at = thresholds.get("domain_skills_at", {})
    for min_level_str, required_count in domain_skills_at.items():
        min_level = int(min_level_str)
        count = sum(1 for lvl in domain_skill_levels if lvl >= min_level)
        if count < required_count:
            return False

    # min_categories
    min_categories = thresholds.get("min_categories")
    if min_categories is not None and len(categories_covered) < min_categories:
        return False

    # foundation_avg
    min_foundation = thresholds.get("foundation_avg")
    if min_foundation is not None and foundation_avg < min_foundation:
        return False

    # pinned skills: each entry is {"skill": "SKILL-ID", "minimum_level": 3}
    for pin in pinned:
        skill_id = pin["skill"]
        required = pin["minimum_level"]
        if person_skill_map.get(skill_id, 0) < required:
            return False

    return True


def _compute_gaps(
    level_key,
    level_def,
    domain_skill_levels,
    categories_covered,
    foundation_avg,
    person_skill_map,
):
    """Compute human-readable gap descriptions for the next maturity level."""
    thresholds = level_def.get("thresholds", {})
    pinned = level_def.get("pinned", [])
    gaps = []

    # domain_skills_at gaps
    domain_skills_at = thresholds.get("domain_skills_at", {})
    for min_level_str, required_count in domain_skills_at.items():
        min_level = int(min_level_str)
        count = sum(1 for lvl in domain_skill_levels if lvl >= min_level)
        if count < required_count:
            deficit = required_count - count
            gaps.append(f"{deficit} more skill{'s' if deficit != 1 else ''} at L{min_level}+")

    # min_categories gap
    min_categories = thresholds.get("min_categories")
    if min_categories is not None and len(categories_covered) < min_categories:
        deficit = min_categories - len(categories_covered)
        gaps.append(f"{deficit} more category coverage")

    # foundation_avg gap
    min_foundation = thresholds.get("foundation_avg")
    if min_foundation is not None and foundation_avg < min_foundation:
        gaps.append(f"foundation avg {foundation_avg:.1f} < {min_foundation:.1f}")

    # pinned skill gaps
    for pin in pinned:
        skill_id = pin["skill"]
        required = pin["minimum_level"]
        current = person_skill_map.get(skill_id, 0)
        if current < required:
            gaps.append(f"{skill_id} at L{required}+")

    return {
        "level": level_key,
        "title": level_def.get("title", level_key),
        "gaps": gaps,
    }


def compute_all_domain_maturities(person):
    """Compute maturity results for every domain the person is assigned to.

    Args:
        person: Person instance with domains JSONField (list of domain IDs).

    Returns:
        List of maturity result dicts, each augmented with domain_id and domain_name.
    """
    results = []
    for domain_id in person.domains or []:
        try:
            profile = Profile.objects.using("taxonomy").get(domain_id=domain_id)
        except Profile.DoesNotExist:
            continue

        maturity = compute_domain_maturity(person, profile)
        maturity["domain_id"] = domain_id
        maturity["domain_name"] = profile.name
        results.append(maturity)

    return results


def compute_service_readiness():
    """For each service, check which personnel are qualified for each competency."""
    services = Service.objects.using("taxonomy").all()
    results = []

    for service in services:
        competencies = []
        for comp in service.required_competencies or []:
            skill_id = comp["skill"]
            min_level = comp["minimum_level"]

            qualified = PersonSkill.objects.filter(
                skill_id=skill_id, level__gte=min_level
            ).select_related("person")
            qualified_people = [ps.person.name for ps in qualified]

            try:
                skill = Skill.objects.using("taxonomy").get(id=skill_id)
                skill_name = skill.name
            except Skill.DoesNotExist:
                skill_name = skill_id

            competencies.append(
                {
                    "skill_id": skill_id,
                    "skill_name": skill_name,
                    "minimum_level": min_level,
                    "qualified_count": len(qualified_people),
                    "qualified_people": qualified_people,
                }
            )

        results.append(
            {
                "service_id": service.id,
                "service_name": service.name,
                "competencies": competencies,
                "fully_staffable": all(c["qualified_count"] > 0 for c in competencies),
            }
        )

    return results


def _skill_name_map(skill_ids):
    """Batch lookup of skill names from taxonomy DB."""
    skills = Skill.objects.using("taxonomy").filter(id__in=skill_ids)
    return {s.id: s.name for s in skills}


def compute_project_coverage(project, include_personnel=True):
    """For each required competency, report coverage across all personnel.

    With include_personnel=False the per-skill dicts carry no names and no
    counts — only whether the requirement is covered at all. That is what a
    `user` may see: a project's shape, without reading colleagues' levels.
    """
    requirements = project.required_competencies or []
    if not requirements:
        return []

    skill_ids = [c["skill"] for c in requirements]
    names = _skill_name_map(skill_ids)

    all_skills = PersonSkill.objects.filter(skill_id__in=skill_ids).select_related("person")
    skill_people = {}
    for ps in all_skills:
        skill_people.setdefault(ps.skill_id, []).append((ps.person.name, ps.level))

    results = []
    for comp in requirements:
        skill_id = comp["skill"]
        min_level = comp["minimum_level"]
        people = skill_people.get(skill_id, [])

        qualified = [name for name, lvl in people if lvl >= min_level]
        entry = {
            "skill_id": skill_id,
            "skill_name": names.get(skill_id, skill_id),
            "minimum_level": min_level,
            "is_covered": len(qualified) > 0,
        }
        if include_personnel:
            entry["qualified"] = qualified
            entry["qualified_count"] = len(qualified)
            entry["close"] = [name for name, lvl in people if lvl == min_level - 1]
        results.append(entry)

    return results


DEFAULT_MINIMUM_LEVEL = 3


def project_skill_table(project, selection=None):
    """Every skill a project could require, for the manager's edit table.

    Lists all active skills, plus any the project already requires that have
    since been deprecated or dropped from the taxonomy, so a save never loses
    them silently. `selection` ({skill_id: level}) stands in for the saved
    requirements when redisplaying a rejected submission.

    Returns (rows, holders): rows in display order, and who holds each listed
    skill as {skill_id: [[name, level], ...]} for live coverage in the page.
    Holders name colleagues, so only managers may be shown them.
    """
    saved = {c["skill"]: c["minimum_level"] for c in project.required_competencies or []}
    chosen = saved if selection is None else selection

    def row(skill_id, name, domain, status, category="", tags=()):
        return {
            "id": skill_id,
            "name": name,
            "domain": domain,
            "category": category,
            "tags": list(tags),
            "status": status,
            "required": skill_id in chosen,
            "level": chosen.get(skill_id, saved.get(skill_id, DEFAULT_MINIMUM_LEVEL)),
            "saved_level": saved.get(skill_id),
        }

    skills = (
        Skill.objects.using("taxonomy")
        .select_related("domain")
        .filter(Q(status="active") | Q(id__in=saved))
        .order_by("domain__name", "name")
    )
    found = [row(s.id, s.name, s.domain.name, s.status, s.category, s.tags or []) for s in skills]
    known = {r["id"] for r in found}
    missing = [
        row(skill_id, skill_id, "Not in taxonomy", "missing")
        for skill_id in saved
        if skill_id not in known
    ]
    rows = missing + found

    holders = {}
    for ps in (
        PersonSkill.objects.filter(skill_id__in=[r["id"] for r in rows])
        .select_related("person")
        .order_by("person__name")
    ):
        holders.setdefault(ps.skill_id, []).append([ps.person.name, ps.level])
    return rows, holders


def compute_person_project_fitness(person, project):
    """How well one person meets one project's requirements.

    Returns None when the project has no requirements, so callers can skip it.
    """
    requirements = project.required_competencies or []
    if not requirements:
        return None

    levels = {ps.skill_id: ps.level for ps in person.skills.all()}
    names = _skill_name_map([c["skill"] for c in requirements])

    skills = []
    met = 0
    for comp in requirements:
        skill_id = comp["skill"]
        current = levels.get(skill_id, 0)
        is_met = current >= comp["minimum_level"]
        if is_met:
            met += 1
        skills.append(
            {
                "skill_id": skill_id,
                "skill_name": names.get(skill_id, skill_id),
                "minimum_level": comp["minimum_level"],
                "current_level": current,
                "is_met": is_met,
            }
        )

    return {
        "project": project,
        "met": met,
        "total": len(requirements),
        "pct": round(100 * met / len(requirements)),
        "skills": skills,
    }


def compute_domain_coverage():
    """Compute skill coverage across all personnel for each domain.

    Returns a list of domain dicts with skill-level detail.
    """
    from apps.core.models import TaxonomyMeta
    from apps.taxonomy.models import Domain

    domain_order = TaxonomyMeta.domain_sort_key()

    all_skills = (
        Skill.objects.using("taxonomy")
        .filter(status="active")
        .select_related("domain")
        .order_by("domain_id", "category", "name")
    )

    # {skill_id: [(person_name, level), ...]}
    person_skills = {}
    for ps in PersonSkill.objects.filter(level__gte=1).select_related("person"):
        person_skills.setdefault(ps.skill_id, []).append((ps.person.name, ps.level))

    domain_skills = {}
    for skill in all_skills:
        domain_skills.setdefault(skill.domain_id, []).append(skill)

    results = []
    for domain in Domain.objects.using("taxonomy").all():
        skills = domain_skills.get(domain.id, [])
        total = len(skills)
        if total == 0:
            continue

        skill_details = []
        covered_l1 = covered_l2 = covered_l3 = 0
        level_dist = {i: 0 for i in range(6)}  # count of skills with best_level == i

        for skill in skills:
            personnel = person_skills.get(skill.id, [])
            personnel_sorted = sorted(personnel, key=lambda x: -x[1])
            best_level = personnel_sorted[0][1] if personnel_sorted else 0
            best_person = personnel_sorted[0][0] if personnel_sorted else None

            level_dist[min(best_level, 5)] += 1

            if best_level >= 1:
                covered_l1 += 1
            if best_level >= 2:
                covered_l2 += 1
            if best_level >= 3:
                covered_l3 += 1

            skill_details.append(
                {
                    "skill_id": skill.id,
                    "skill_name": skill.name,
                    "category": skill.category or "",
                    "best_level": best_level,
                    "best_person": best_person,
                    "personnel": [{"name": n, "level": lvl} for n, lvl in personnel_sorted],
                }
            )

        # Convert to list of (level, count, pct) for template
        level_distribution = [
            {
                "level": i,
                "count": level_dist[i],
                "pct": round(100 * level_dist[i] / total) if total else 0,
            }
            for i in range(6)
        ]

        results.append(
            {
                "domain_id": domain.id,
                "domain_name": domain.name,
                "total_skills": total,
                "covered_l1": covered_l1,
                "covered_l2": covered_l2,
                "covered_l3": covered_l3,
                "pct_l1": round(100 * covered_l1 / total) if total else 0,
                "pct_l2": round(100 * covered_l2 / total) if total else 0,
                "pct_l3": round(100 * covered_l3 / total) if total else 0,
                "level_distribution": level_distribution,
                "skills": skill_details,
                "sort_key": domain_order.get(domain.id, 999),
            }
        )

    results.sort(key=lambda d: d["sort_key"])
    return results
