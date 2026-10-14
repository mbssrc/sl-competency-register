#!/usr/bin/env python3
"""Expand demo archetypes into a full literal population snapshot.

The solver is deliberately free of randomness: every level it chooses follows a
rule plus a stable sort order, so identical archetypes always produce an
identical snapshot and any diff traces to a deliberate edit.
"""

import datetime
import json
import zlib
from dataclasses import dataclass, field
from pathlib import Path


def load_json(path):
    with open(path) as handle:
        return json.load(handle)


@dataclass
class Skill:
    id: str
    name: str
    domain_id: str
    category: str
    category_id: str
    status: str
    requires: list
    proficiency: dict


@dataclass
class Taxonomy:
    skills: dict
    domains: dict = field(default_factory=dict)
    profiles: dict = field(default_factory=dict)

    def foundation_ids(self):
        """Active Foundations skill IDs, in stable order."""
        return sorted(
            s.id for s in self.skills.values() if s.domain_id == "FOUND" and s.status == "active"
        )

    def domain_skill_ids(self, domain_id):
        """Active skill IDs of one domain, ordered by category then ID."""
        return [
            s.id
            for s in sorted(
                (
                    s
                    for s in self.skills.values()
                    if s.domain_id == domain_id and s.status == "active"
                ),
                key=lambda s: (s.category, s.id),
            )
        ]


PREREQ_FLOOR = 2


def repair_prerequisites(levels, taxonomy, excluded):
    """Raise every prerequisite of a held skill to at least one level below it.

    Prerequisites are only ever raised and the dependant is never lowered, so
    thresholds satisfied before this step cannot be broken. The taxonomy DAG is
    acyclic (tools/validate.py:check_dag_cycles enforces that), so the
    fixed-point loop terminates.
    """
    result = dict(levels)
    changed = True
    while changed:
        changed = False
        for skill_id in sorted(result):
            level = result[skill_id]
            if level < PREREQ_FLOOR:
                continue
            skill = taxonomy.skills.get(skill_id)
            if skill is None:
                continue
            target = max(level - 1, PREREQ_FLOOR)
            for prereq in skill.requires:
                if prereq in excluded or prereq not in taxonomy.skills:
                    continue
                if result.get(prereq, 0) < target:
                    result[prereq] = target
                    changed = True
    return result


# Lowest level at which a held skill counts towards category breadth. Mirrors
# apps/personnel/services.py:CATEGORY_MIN_LEVEL.
CATEGORY_MIN_LEVEL = 2


def domain_levels(levels, taxonomy, domain_id):
    """Levels of the held skills that belong to one domain."""
    return [
        level
        for skill_id, level in levels.items()
        if skill_id in taxonomy.skills and taxonomy.skills[skill_id].domain_id == domain_id
    ]


def categories_covered(levels, taxonomy, domain_id):
    """Category names of a domain covered at CATEGORY_MIN_LEVEL or above."""
    covered = set()
    for skill_id, level in levels.items():
        skill = taxonomy.skills.get(skill_id)
        if skill is None or skill.domain_id != domain_id:
            continue
        if skill.category and level >= CATEGORY_MIN_LEVEL:
            covered.add(skill.category)
    return covered


def foundation_average(levels, taxonomy):
    """Mean level over every active Foundations skill, unassessed ones as zero."""
    active = taxonomy.foundation_ids()
    if not active:
        return 0.0
    return sum(levels.get(skill_id, 0) for skill_id in active) / len(active)


def thresholds_met(rung, levels, taxonomy, domain_id):
    """Whether a level map satisfies every threshold of one maturity rung.

    Mirrors apps/personnel/services.py:_check_thresholds. The application is
    the authority; demo/verify.py checks the seeded result against it, so any
    divergence here is caught rather than silently shipped.
    """
    thresholds = rung.get("thresholds", {})

    held = domain_levels(levels, taxonomy, domain_id)
    for min_level_str, required_count in thresholds.get("domain_skills_at", {}).items():
        min_level = int(min_level_str)
        if sum(1 for level in held if level >= min_level) < required_count:
            return False

    min_categories = thresholds.get("min_categories")
    if min_categories is not None:
        if len(categories_covered(levels, taxonomy, domain_id)) < min_categories:
            return False

    min_foundation = thresholds.get("foundation_avg")
    if min_foundation is not None:
        if foundation_average(levels, taxonomy) < min_foundation:
            return False

    for pin in rung.get("pinned", []):
        if levels.get(pin["skill"], 0) < pin["minimum_level"]:
            return False

    return True


class UnsatisfiableArchetype(Exception):
    """An archetype cannot be expanded into a level map that meets its target."""


# Mirrors apps/personnel/services.py:MATURITY_LEVELS_ORDERED.
MATURITY_ORDER = ["junior", "practitioner", "senior", "lead", "principal"]

LEVEL_MAX = 5

# Level bands per target rung: the range a category's skills are filled into.
# "strong" and "weak" name category IDs in the archetype; everything else is mid.
# How much of a domain a person holds any record for at all, by rung. A junior
# has not been exposed to every skill in the domain, and claiming otherwise
# would be less credible than claiming none.
COVERAGE_BY_RUNG = {
    "junior": 0.40,
    "practitioner": 0.65,
    "senior": 0.85,
    "lead": 0.95,
    "principal": 1.00,
}

BANDS = {
    "junior": {"strong": (2, 2), "mid": (1, 2), "low": (1, 1)},
    "practitioner": {"strong": (3, 3), "mid": (2, 3), "low": (1, 2)},
    "senior": {"strong": (4, 4), "mid": (3, 4), "low": (1, 2)},
    "lead": {"strong": (4, 5), "mid": (3, 4), "low": (1, 2)},
    "principal": {"strong": (5, 5), "mid": (4, 5), "low": (2, 3)},
}


def _band_level(band, index):
    """A level from a band, cycling by position so a band spreads rather than flattens."""
    low, high = band
    values = list(range(low, high + 1))
    return values[index % len(values)]


def _band_for(category_id, bands, rung):
    table = BANDS[rung]
    if category_id in bands.get("strong", []):
        return table["strong"]
    if category_id in bands.get("weak", []):
        return table["low"]
    return table["mid"]


def _raise_to(levels, skill_id, target, locked, excluded, who, reason):
    """Raise a skill to at least `target`, refusing to fight a locked signature."""
    if skill_id in excluded:
        raise UnsatisfiableArchetype(
            f"{who}: {reason} needs {skill_id} at L{target}, but it is in 'never'"
        )
    current = levels.get(skill_id, 0)
    if current >= target:
        return
    if skill_id in locked:
        raise UnsatisfiableArchetype(
            f"{who}: {reason} needs {skill_id} at L{target}, "
            f"but the signature locks it at L{current}"
        )
    levels[skill_id] = target


def _promotion_order(taxonomy, domain_id, bands, locked, excluded):
    """Candidate skills for threshold promotion: strong categories first, then stable."""

    def key(skill_id):
        skill = taxonomy.skills[skill_id]
        strong = skill.category_id in bands.get("strong", [])
        weak = skill.category_id in bands.get("weak", [])
        return (0 if strong else 2 if weak else 1, skill.category, skill.id)

    return sorted(
        (
            sid
            for sid in taxonomy.domain_skill_ids(domain_id)
            if sid not in locked and sid not in excluded
        ),
        key=key,
    )


def _satisfy_domain_counts(levels, rung, taxonomy, domain_id, candidates, who):
    """Promote until `domain_skills_at` is met, highest-first so promotions are cheap."""
    for min_level_str, required in sorted(
        rung.get("thresholds", {}).get("domain_skills_at", {}).items()
    ):
        min_level = int(min_level_str)
        while True:
            held = domain_levels(levels, taxonomy, domain_id)
            if sum(1 for lvl in held if lvl >= min_level) >= required:
                break
            below = [sid for sid in candidates if levels.get(sid, 0) < min_level]
            if not below:
                raise UnsatisfiableArchetype(
                    f"{who}: domain_skills_at L{min_level}>={required} in {domain_id} "
                    f"cannot be met; no promotable skill is left"
                )
            best = max(below, key=lambda sid: (levels.get(sid, 0), -candidates.index(sid)))
            levels[best] = levels.get(best, 0) + 1


def _satisfy_categories(levels, rung, taxonomy, domain_id, candidates, who):
    """Promote one skill per uncovered category up to the breadth threshold."""
    required = rung.get("thresholds", {}).get("min_categories")
    if required is None:
        return
    while len(categories_covered(levels, taxonomy, domain_id)) < required:
        covered = categories_covered(levels, taxonomy, domain_id)
        pick = next(
            (
                sid
                for sid in candidates
                if taxonomy.skills[sid].category not in covered
                and levels.get(sid, 0) < CATEGORY_MIN_LEVEL
            ),
            None,
        )
        if pick is None:
            raise UnsatisfiableArchetype(
                f"{who}: min_categories={required} in {domain_id} cannot be met; "
                f"only {len(covered)} categories are reachable"
            )
        levels[pick] = CATEGORY_MIN_LEVEL


def _satisfy_foundation_average(levels, rung, taxonomy, locked, excluded, who):
    """Promote Foundations skills until the rung's foundation average is reached."""
    required = rung.get("thresholds", {}).get("foundation_avg")
    if required is None:
        return
    candidates = [
        sid for sid in taxonomy.foundation_ids() if sid not in locked and sid not in excluded
    ]
    while foundation_average(levels, taxonomy) < required:
        below = [sid for sid in candidates if levels.get(sid, 0) < LEVEL_MAX]
        if not below:
            raise UnsatisfiableArchetype(
                f"{who}: foundation_avg>={required} cannot be met; "
                f"every Foundations skill is already at L{LEVEL_MAX}"
            )
        best = max(below, key=lambda sid: (levels.get(sid, 0), -candidates.index(sid)))
        levels[best] = levels.get(best, 0) + 1


def solve_levels(arch, taxonomy):
    """Expand one archetype into a level map.

    Every step only ever raises a level, which is why the overshoot check can
    run last and be trusted.
    """
    who = f"{arch['key']} ({arch['name']})"
    bands = arch.get("bands", {})

    # Two kinds of exclusion. "never" is hard: the skill is absent whatever
    # else needs it. Coverage is soft: it says what the person has been exposed
    # to, and prerequisite repair may pull a dropped skill back in, because you
    # cannot hold a skill at L3 with none of what it is built on.
    never = set(arch.get("never", []))
    excluded = set(never)

    # 1. Lock the signature.
    locked = set(arch.get("signature", {}))
    conflict = locked & excluded
    if conflict:
        raise UnsatisfiableArchetype(
            f"{who}: {sorted(conflict)} appear in both 'signature' and 'never'"
        )
    levels = dict(arch.get("signature", {}))

    targets = arch.get("target_maturity", {})

    # 2b. Apply coverage: the domain skills this person has no record for.
    for domain_id in arch.get("domains", []):  # noqa: PLR1702
        target = targets.get(domain_id)
        if target is None:
            continue
        domain_skills = taxonomy.domain_skill_ids(domain_id)
        coverage = arch.get("coverage", COVERAGE_BY_RUNG[target])
        keep_count = max(1, round(coverage * len(domain_skills)))
        order = _promotion_order(taxonomy, domain_id, bands, locked=set(), excluded=excluded)
        for skill_id in order[keep_count:]:
            if skill_id not in locked:
                excluded.add(skill_id)

    # 3. Satisfy the pinned requirements of the target rung and every rung below.
    for domain_id, target in sorted(targets.items()):
        ladder = taxonomy.profiles[domain_id]["maturity_levels"]
        for rung_key in MATURITY_ORDER[: MATURITY_ORDER.index(target) + 1]:
            for pin in (ladder.get(rung_key) or {}).get("pinned", []):
                _raise_to(
                    levels,
                    pin["skill"],
                    pin["minimum_level"],
                    locked,
                    excluded,
                    who,
                    f"{domain_id} {rung_key} pinned requirement",
                )

    # 4. Fill the assigned domains' skills by band.
    for domain_id in arch.get("domains", []):
        target = targets.get(domain_id)
        if target is None:
            continue
        for index, skill_id in enumerate(taxonomy.domain_skill_ids(domain_id)):
            if skill_id in locked or skill_id in excluded:
                continue
            band = _band_for(taxonomy.skills[skill_id].category_id, bands, target)
            levels[skill_id] = max(levels.get(skill_id, 0), _band_level(band, index))

    # 5. Fill Foundations by band, before thresholds because foundation_avg is one.
    low, high = arch.get("foundations", [1, 1])
    for index, skill_id in enumerate(taxonomy.foundation_ids()):
        if skill_id in locked or skill_id in excluded:
            continue
        levels[skill_id] = max(levels.get(skill_id, 0), _band_level((low, high), index))

    # 6. Satisfy the target rung's thresholds.
    for domain_id, target in sorted(targets.items()):
        rung = taxonomy.profiles[domain_id]["maturity_levels"][target]
        candidates = _promotion_order(taxonomy, domain_id, bands, locked, excluded)
        _satisfy_domain_counts(levels, rung, taxonomy, domain_id, candidates, who)
        _satisfy_categories(levels, rung, taxonomy, domain_id, candidates, who)
        _satisfy_foundation_average(levels, rung, taxonomy, locked, excluded, who)

    # 7. Repair prerequisites. Only "never" blocks a repair; a skill dropped by
    #    coverage comes back when something the person does hold needs it.
    levels = repair_prerequisites(levels, taxonomy, never)

    for skill_id, level in sorted(levels.items()):
        if level < PREREQ_FLOOR:
            continue
        skill = taxonomy.skills.get(skill_id)
        if skill is None:
            continue
        blocked = [p for p in skill.requires if p in never]
        if blocked:
            raise UnsatisfiableArchetype(
                f"{who}: {skill_id} is held at L{level} but its prerequisite "
                f"{blocked[0]} is in 'never'; drop one or the other"
            )

    # 8. Check for overshoot, last, because nothing above ever lowers a level.
    for domain_id, target in sorted(targets.items()):
        ladder = taxonomy.profiles[domain_id]["maturity_levels"]
        next_index = MATURITY_ORDER.index(target) + 1
        if next_index >= len(MATURITY_ORDER):
            continue
        next_key = MATURITY_ORDER[next_index]
        next_rung = ladder.get(next_key)
        if next_rung and thresholds_met(next_rung, levels, taxonomy, domain_id):
            raise UnsatisfiableArchetype(
                f"{who}: targets {domain_id} '{target}' but also satisfies "
                f"'{next_key}'; lower a band or trim the signature"
            )

    return {sid: lvl for sid, lvl in levels.items() if lvl > 0}


def load_taxonomy(root):
    """Build a Taxonomy from the repository's JSON tree.

    Skill files name their domain by directory and their category by display
    name; the database uses short IDs for both. The per-domain `_domain.json`
    carries the mapping, so it is resolved here once rather than at every use.
    """
    root = Path(root)
    skills = {}
    domains = {}

    for domain_file in sorted((root / "taxonomy").glob("*/_domain.json")):
        domain = load_json(domain_file)
        domain_dir = domain_file.parent
        category_ids = {c["name"]: c["id"] for c in domain.get("categories", [])}
        domains[domain["id"]] = {
            "name": domain["name"],
            "directory": domain_dir.name,
            "category_ids": category_ids,
        }

        for skill_file in sorted(domain_dir.rglob("*.json")):
            if skill_file.name.startswith("_"):
                continue
            data = load_json(skill_file)
            category = data.get("category", "")
            skills[data["id"]] = Skill(
                id=data["id"],
                name=data["name"],
                domain_id=domain["id"],
                category=category,
                category_id=category_ids.get(category, ""),
                status=data.get("status", "active"),
                requires=list(data.get("requires", [])),
                proficiency=data.get("proficiency", {}),
            )

    profiles = {}
    for profile_file in sorted((root / "profiles").glob("*.json")):
        profile = load_json(profile_file)
        profiles[profile["id"]] = profile

    return Taxonomy(skills=skills, domains=domains, profiles=profiles)


def load_services(root):
    """Service definitions, keyed by service ID."""
    services = {}
    for path in sorted((Path(root) / "services").glob("*.json")):
        service = load_json(path)
        services[service["id"]] = service
    return services


def resolve_requirements(spec, taxonomy, services):
    """A project's required competencies, from a service template plus adjustments.

    A project initialised from a service copies that service's competencies, the
    way the web UI's "initialize from service" does, and then narrows or widens
    them to its own scope: `drop_categories` removes everything in a category
    (a board-level assessment requires no chip-invasive work), `drop` removes
    named skills, `add` appends, and `levels` overrides minimum levels.
    """
    requirements = {}

    service_id = spec.get("from_service")
    if service_id:
        service = services[service_id]
        for comp in service.get("required_competencies", []):
            requirements[comp["skill"]] = comp["minimum_level"]

    for category_id in spec.get("drop_categories", []):
        for skill_id in list(requirements):
            skill = taxonomy.skills.get(skill_id)
            if skill is not None and skill.category_id == category_id:
                del requirements[skill_id]

    for skill_id in spec.get("drop", []):
        requirements.pop(skill_id, None)

    for comp in spec.get("add", []):
        requirements[comp["skill"]] = comp["minimum_level"]

    for skill_id, level in spec.get("levels", {}).items():
        if skill_id in requirements:
            requirements[skill_id] = level

    order = {sid: i for i, sid in enumerate(taxonomy.skills)}
    return [
        {"skill": skill_id, "minimum_level": requirements[skill_id]}
        for skill_id in sorted(requirements, key=lambda s: (order.get(s, 10**6), s))
    ]


# Who signs off which domain. assessed_by_id holds a username, not a person ID
# (project_assess writes request.user.username), and nothing validates it, so
# these are plausible lab usernames rather than demo account names.
ASSESSORS = {
    "HWSEC": "a.okonkwo",
    "CRYPTO": "r.chandrasekhar",
    "SWSEC": "m.ferreira",
    "WSEC": "f.elmasri",
    "AIML": "m.ferreira",
    "INFRA": "o.nowak",
    "NETSEC": "o.nowak",
}
DEFAULT_ASSESSOR = "e.papadakis"

# The literal the application writes when a self-assessment is promoted into a
# PersonSkill. seed.py keys is_self_assessed off it.
SELF_ASSESSMENT_ASSESSOR = "self-assessment"

AUTHORIZATION_MIN_LEVEL = 3

# Project statuses that count as history and so can be cited as evidence.
FINISHED_STATUSES = ("done", "archived")

# A skill is stale once it has not been practised for a year
# (tools/validate.py:check_warnings uses stale_days=365).
STALE_MIN_DAYS = 400
STALE_SPREAD_DAYS = 120

# No skill is assessed in a person's first six months.
ASSESSMENT_DELAY_DAYS = 180


def _stable_offset(*parts):
    """A deterministic pseudo-offset. crc32 is stable across runs; hash() is not."""
    return zlib.crc32("|".join(parts).encode())


def _assessor_for(skill):
    """The username that signed off this skill. Foundations go to the quality lead."""
    if skill.domain_id == "FOUND":
        return DEFAULT_ASSESSOR
    return ASSESSORS.get(skill.domain_id, DEFAULT_ASSESSOR)


def _routine_assessed_date(arch, skill_id, today):
    """A stable assessment date between the person's first six months and today."""
    start = datetime.date.fromisoformat(arch["start_date"])
    earliest = start + datetime.timedelta(days=ASSESSMENT_DELAY_DAYS)
    window = (today - earliest).days
    if window <= 0:
        return today
    return earliest + datetime.timedelta(days=_stable_offset(arch["key"], skill_id) % window)


def _finished_projects_for(arch, projects, skill_id):
    """Finished projects the person worked on that required this skill, oldest first."""
    worked = []
    for project_id in arch.get("projects", []):
        project = projects[project_id]
        if project["status"] not in FINISHED_STATUSES:
            continue
        if any(r["skill"] == skill_id for r in project.get("required_competencies", [])):
            worked.append(project)
    return sorted(worked, key=lambda p: p["completed_date"])


def _taxonomy_evidence(skill, level):
    """The skill's own first evidence bullet for the level it is held at."""
    rung = (skill.proficiency or {}).get(str(level)) or {}
    bullets = rung.get("evidence") or []
    return bullets[0] if bullets else ""


def _authorization(skill, level, date, assessor):
    """An authorization record, for the levels the proficiency model requires one."""
    if level < AUTHORIZATION_MIN_LEVEL:
        return None
    label = ((skill.proficiency or {}).get(str(level)) or {}).get("label", f"Level {level}")
    return {
        "authorized": True,
        "date": date.isoformat(),
        "authorizer": assessor,
        "scope": f"{skill.name} — {label}",
    }


def _skill_row(arch, skill, level, projects, today, seeded=False):
    """One assessment row, stamped the way the application would have stamped it.

    A `seeded` row is one the "seed from self-assessment" flow would have
    written: the application records the assessor as the literal
    "self-assessment" and flags the row advisory, so seed.py keys off that.
    """
    worked = [] if seeded else _finished_projects_for(arch, projects, skill.id)
    assessor = SELF_ASSESSMENT_ASSESSOR if seeded else _assessor_for(skill)

    if worked:
        # project_assess writes "Project: {name}" markers, newline-joined.
        evidence = "\n".join(f"Project: {p['name']}" for p in worked)
        assessed = datetime.date.fromisoformat(worked[-1]["completed_date"])
    else:
        evidence = _taxonomy_evidence(skill, level)
        assessed = _routine_assessed_date(arch, skill.id, today)

    if skill.id in arch.get("stale_skills", []):
        stale_days = STALE_MIN_DAYS + _stable_offset(arch["key"], skill.id) % STALE_SPREAD_DAYS
        practiced = today - datetime.timedelta(days=stale_days)
    else:
        practiced = assessed

    return {
        "skill": skill.id,
        "level": level,
        "assessed_date": assessed.isoformat(),
        "assessed_by": assessor,
        "last_practiced": practiced.isoformat(),
        "evidence_notes": evidence,
        "authorization": None if seeded else _authorization(skill, level, assessed, assessor),
    }


def _placeholder_row(skill, arch, today):
    """The level-0 row self_assessment_import creates beside a SelfAssessment.

    The person detail table iterates PersonSkill rows, so without this row a
    self-assessed skill has nothing to be displayed on. The application leaves
    it at level 0 with no authorization and no practice date, because nothing
    about it has been ratified.
    """
    # last_practiced is omitted rather than null: nothing has been practised
    # under supervision yet, and schema/person.schema.json types the field as a
    # date string when present.
    return {
        "skill": skill.id,
        "level": 0,
        "assessed_date": _routine_assessed_date(arch, skill.id, today).isoformat(),
        "assessed_by": SELF_ASSESSMENT_ASSESSOR,
        "evidence_notes": "",
        "authorization": None,
    }


def _skill_sort_key(taxonomy, skill_id):
    skill = taxonomy.skills[skill_id]
    return (skill.domain_id, skill.category, skill.id)


def expand_person(arch, taxonomy, projects, today):
    """Expand one archetype into a record conforming to schema/person.schema.json."""
    levels = solve_levels(arch, taxonomy)
    mode = arch.get("self_assessment", {}).get("mode", "none")

    if mode == "only":
        # A new hire has stated a view of their own competence and nobody has
        # ratified any of it, so every row is the level-0 placeholder that
        # self_assessment_import leaves behind.
        rows = [
            _placeholder_row(taxonomy.skills[skill_id], arch, today)
            for skill_id in sorted(levels, key=lambda s: _skill_sort_key(taxonomy, s))
        ]
    else:
        seeded = set(arch.get("self_assessment", {}).get("skills", []))
        rows = [
            _skill_row(
                arch, taxonomy.skills[skill_id], level, projects, today, seeded=skill_id in seeded
            )
            for skill_id, level in sorted(
                levels.items(), key=lambda kv: _skill_sort_key(taxonomy, kv[0])
            )
        ]
        rows += [
            _placeholder_row(taxonomy.skills[skill_id], arch, today)
            for skill_id in _claimed_extras(arch, taxonomy, levels)
        ]
        rows.sort(key=lambda r: _skill_sort_key(taxonomy, r["skill"]))

    return {
        "id": arch["key"],
        "name": arch["name"],
        "profiles": list(arch.get("domains", [])),
        "start_date": arch["start_date"],
        "skills": rows,
        "development_plan": _development_plan(arch, levels),
    }


def _development_plan(arch, levels):
    """Development targets, with current_level read from the solved levels."""
    plan = []
    for target in arch.get("development_plan", []):
        plan.append(
            {
                "skill": target["skill"],
                "current_level": levels.get(target["skill"], 0),
                "target_level": target["target_level"],
                "target_date": target["target_date"],
                "actions": list(target.get("actions", [])),
            }
        )
    return plan


def _claimed_extras(arch, taxonomy, levels):
    """Self-assessed levels for skills the person holds no assessment for.

    Someone can rate themselves on a skill nobody has assessed. These need the
    level-0 placeholder too, which is why they are resolved in one place.
    """
    extras = arch.get("self_assessment", {}).get("extra", {})
    return {
        skill_id: level
        for skill_id, level in sorted(extras.items())
        if skill_id in taxonomy.skills and skill_id not in levels
    }


def expand_self_assessments(arch, taxonomy, today):
    """A person's self-reported levels.

    Self-assessments are advisory: the application ignores them in maturity and
    readiness calculations until a manager ratifies one. The `bias` is what makes
    the person-detail delta indicator show something — positive for someone who
    rates themselves above their assessed level, negative for the reverse.
    """
    config = arch.get("self_assessment", {})
    mode = config.get("mode", "none")
    if mode == "none":
        return []

    bias = config.get("bias", 0)
    # Jitter spreads the divergence across skills. Without it every row sits the
    # same distance from its assessment, which reads as generated rather than
    # as a person being unsure in places and confident in others.
    jitter = config.get("jitter", 0)
    levels = solve_levels(arch, taxonomy)

    rows = []
    for skill_id, level in sorted(levels.items(), key=lambda kv: _skill_sort_key(taxonomy, kv[0])):
        offset = bias
        if jitter:
            span = 2 * jitter + 1
            offset += _stable_offset("sa", arch["key"], skill_id) % span - jitter
        stated = max(0, min(LEVEL_MAX, level + offset))
        rows.append(
            {
                "skill": skill_id,
                "level": stated,
                "assessed_date": _routine_assessed_date(arch, skill_id, today).isoformat(),
                "evidence_notes": _taxonomy_evidence(taxonomy.skills[skill_id], stated),
            }
        )

    for skill_id, stated in _claimed_extras(arch, taxonomy, levels).items():
        rows.append(
            {
                "skill": skill_id,
                "level": stated,
                "assessed_date": _routine_assessed_date(arch, skill_id, today).isoformat(),
                "evidence_notes": _taxonomy_evidence(taxonomy.skills[skill_id], stated),
            }
        )

    return sorted(rows, key=lambda r: _skill_sort_key(taxonomy, r["skill"]))


def load_archetypes(demo_dir):
    """Archetypes in filename order, which is the roster order."""
    return [load_json(path) for path in sorted((Path(demo_dir) / "archetypes").glob("*.json"))]


def expand_projects(demo_dir, taxonomy, services):
    """Projects with their requirements resolved from service templates."""
    projects = {}
    for spec in load_json(Path(demo_dir) / "projects.json"):
        resolved = dict(spec)
        resolved["required_competencies"] = resolve_requirements(
            spec.get("requirements", {}), taxonomy, services
        )
        resolved.pop("requirements", None)
        projects[spec["id"]] = resolved
    return projects


def expand_all(repo_root, demo_dir, today):
    """Expand the whole demo directory into the committed snapshot."""
    taxonomy = load_taxonomy(repo_root)
    services = load_services(repo_root)
    projects = expand_projects(demo_dir, taxonomy, services)

    people = []
    self_assessments = {}
    for arch in load_archetypes(demo_dir):
        people.append(expand_person(arch, taxonomy, projects, today))
        rows = expand_self_assessments(arch, taxonomy, today)
        if rows:
            self_assessments[arch["key"]] = rows

    return {
        "people": people,
        "self_assessments": self_assessments,
        "projects": list(projects.values()),
    }


# The demo is a fixed scenario, so its "today" is fixed too. Deriving dates from
# the real clock would make the committed snapshot stale every midnight.
REFERENCE_DATE = datetime.date(2026, 10, 14)

SNAPSHOT_PATH = Path(__file__).resolve().parent / "generated" / "population.json"
DEMO_DIR = Path(__file__).resolve().parent
REPO_ROOT = DEMO_DIR.parent


def render(snapshot):
    """The snapshot's committed form. Stable, so a diff means a deliberate edit."""
    return json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n"


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(
        description="Expand demo archetypes into demo/generated/population.json"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify the committed snapshot is current; write nothing.",
    )
    args = parser.parse_args(argv)

    snapshot = expand_all(REPO_ROOT, DEMO_DIR, REFERENCE_DATE)
    rendered = render(snapshot)

    if args.check:
        if not SNAPSHOT_PATH.exists():
            print(f"MISSING {SNAPSHOT_PATH}: run python demo/expand.py")
            return 1
        if SNAPSHOT_PATH.read_text() != rendered:
            print(
                f"STALE {SNAPSHOT_PATH}: archetypes have changed since it was "
                f"generated. Run: python demo/expand.py"
            )
            return 1
        print(
            f"Snapshot is current: {len(snapshot['people'])} people, "
            f"{len(snapshot['projects'])} projects."
        )
        return 0

    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(rendered)
    rows = sum(len(p["skills"]) for p in snapshot["people"])
    print(
        f"Wrote {SNAPSHOT_PATH.relative_to(REPO_ROOT)}: "
        f"{len(snapshot['people'])} people, {rows} assessments, "
        f"{len(snapshot['projects'])} projects."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
