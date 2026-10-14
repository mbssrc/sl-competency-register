import json
from collections import OrderedDict

from django.core.exceptions import ValidationError
from django.db.models import Count
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounts.decorators import role_required
from apps.core.models import TaxonomyMeta
from apps.core.validators import (
    LEVEL_MAX,
    LEVEL_MIN,
    parse_bounded_int,
    parse_choice,
    parse_json_object,
    parse_level,
)

from .models import Domain, Profile, Service, Skill

MAX_REORDER_ENTRIES = 500


def _parse_id_list(request):
    """Parse a drag-and-drop reorder payload: a JSON array of string IDs."""
    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
        raise ValidationError("Request body must be valid JSON.")
    if not isinstance(payload, list):
        raise ValidationError("Expected a JSON array of IDs.")
    if len(payload) > MAX_REORDER_ENTRIES:
        raise ValidationError(f"At most {MAX_REORDER_ENTRIES} entries allowed.")
    if not all(isinstance(entry, str) for entry in payload):
        raise ValidationError("Every entry must be a string ID.")
    return payload


def _parse_skill_levels(raw, field_name):
    """Parse "SKILL-ID:level" lines into [{"skill", "minimum_level"}].

    Returns (entries, errors); a line that cannot be read is reported by
    line, never dropped, and every skill must exist in the taxonomy.
    """
    entries, errors = [], []
    for number, line in enumerate((raw or "").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        if ":" not in line:
            errors.append(f"{field_name} line {number}: expected SKILL-ID:level, got {line!r}.")
            continue
        skill_id, level_raw = (part.strip() for part in line.split(":", 1))
        try:
            level = parse_level(level_raw, f"{field_name} level for {skill_id}")
        except ValidationError as e:
            errors.extend(e.messages)
            continue
        entries.append({"skill": skill_id, "minimum_level": level})

    known = set(
        Skill.objects.filter(id__in=[e["skill"] for e in entries]).values_list("id", flat=True)
    )
    for entry in entries:
        if entry["skill"] not in known:
            errors.append(f"{field_name}: skill {entry['skill']!r} not found in taxonomy.")
    return entries, errors


def _is_htmx(request):
    return request.headers.get("HX-Request") == "true"


@role_required("user")
def domain_list(request):
    domain_order = TaxonomyMeta.domain_sort_key()
    domains = Domain.objects.annotate(skill_count=Count("skills")).all()
    domain_data = []
    for domain in domains:
        category_count = len(domain.categories) if domain.categories else 0
        domain_data.append(
            {
                "domain": domain,
                "skill_count": domain.skill_count,
                "category_count": category_count,
                "sort_key": domain_order.get(domain.id, 999),
            }
        )
    domain_data.sort(key=lambda d: d["sort_key"])
    return render(request, "taxonomy/domain_list.html", {"domain_data": domain_data})


@role_required("manager")
def domain_reorder(request):
    """Save new domain order from drag-and-drop."""
    if request.method != "POST":
        return redirect("taxonomy:domain-list")
    try:
        order = _parse_id_list(request)
    except ValidationError as e:
        return HttpResponseBadRequest("; ".join(e.messages))

    meta = TaxonomyMeta.load()
    # Build a lookup from current domains
    domain_lookup = {d["id"]: d for d in meta.domains or []}
    # Reorder based on the new ID list
    new_domains = []
    for domain_id in order:
        if domain_id in domain_lookup:
            new_domains.append(domain_lookup.pop(domain_id))
    # Append any domains not in the new order (shouldn't happen, but safe)
    for d in domain_lookup.values():
        new_domains.append(d)
    meta.domains = new_domains
    meta.save()
    return JsonResponse({"ok": True})


@role_required("manager")
def service_reorder(request):
    """Save new service order from drag-and-drop."""
    if request.method != "POST":
        return redirect("taxonomy:service-list")
    try:
        order = _parse_id_list(request)
    except ValidationError as e:
        return HttpResponseBadRequest("; ".join(e.messages))
    meta = TaxonomyMeta.load()
    meta.service_order = order
    meta.save()
    return JsonResponse({"ok": True})


@role_required("manager")
def domain_edit(request, domain_id):
    domain = get_object_or_404(Domain, pk=domain_id)

    if request.method == "POST":
        domain.name = request.POST.get("name", domain.name).strip()
        domain.description = request.POST.get("description", domain.description).strip()
        domain.note = request.POST.get("note", "").strip()

        # Categories: parse rows of "id: name"
        cats_raw = request.POST.get("categories", "").strip()
        if cats_raw:
            categories = []
            for line in cats_raw.splitlines():
                line = line.strip()
                if not line:
                    continue
                if ":" in line:
                    cid, cname = line.split(":", 1)
                    categories.append({"id": cid.strip(), "name": cname.strip()})
                else:
                    categories.append({"id": line, "name": line})
            domain.categories = categories
        else:
            domain.categories = []

        domain.save()
        return redirect("taxonomy:domain-detail", domain_id=domain.id)

    # Build categories text
    cats_str = ""
    if domain.categories:
        cats_str = "\n".join(f"{c.get('id', '')}: {c.get('name', '')}" for c in domain.categories)

    template = (
        "taxonomy/partials/domain_form.html"
        if _is_htmx(request)
        else "taxonomy/partials/domain_form.html"
    )
    return render(
        request,
        template,
        {
            "domain": domain,
            "cats_str": cats_str,
        },
    )


@role_required("user")
def domain_detail(request, domain_id):
    domain = get_object_or_404(Domain, pk=domain_id)
    skills = Skill.objects.filter(domain=domain).order_by("category", "id")

    # Group skills by category
    grouped = OrderedDict()
    for skill in skills:
        cat = skill.category or "Uncategorized"
        grouped.setdefault(cat, []).append(skill)

    # Build a category name lookup from the domain's categories JSON
    category_names = {}
    if domain.categories:
        for cat_info in domain.categories:
            category_names[cat_info.get("id", "")] = cat_info.get("name", cat_info.get("id", ""))

    return render(
        request,
        "taxonomy/domain_detail.html",
        {
            "domain": domain,
            "grouped_skills": grouped,
            "category_names": category_names,
            "skill_count": skills.count(),
        },
    )


@role_required("user")
def skill_detail(request, skill_id):
    skill = get_object_or_404(Skill, pk=skill_id)
    prerequisites = skill.requires.all()
    recommendations = skill.recommended.all()
    required_by = skill.required_by.all()
    recommended_for = skill.recommended_for.all()

    # Build sorted proficiency levels from the JSON dict
    proficiency_levels = []
    if skill.proficiency:
        for level_key in sorted(skill.proficiency.keys(), key=int):
            entry = skill.proficiency[level_key]
            proficiency_levels.append(
                {
                    "level": int(level_key),
                    "label": entry.get("label", ""),
                    "description": entry.get("description", ""),
                    "evidence": entry.get("evidence", []),
                    "authorization": entry.get("authorization", False),
                }
            )

    return render(
        request,
        "taxonomy/skill_detail.html",
        {
            "skill": skill,
            "prerequisites": prerequisites,
            "recommendations": recommendations,
            "required_by": required_by,
            "recommended_for": recommended_for,
            "proficiency_levels": proficiency_levels,
            "framework_rows": _framework_display(skill.framework_mappings),
            "can_edit": request.user.is_manager,
        },
    )


FRAMEWORK_LABELS = {
    "mitre_attack": "MITRE ATT&CK",
    "nice": "NICE",
    "crest": "CREST",
    "sfia": "SFIA",
    "owasp": "OWASP",
}
METHOD_TYPES = [
    "controlled_exercise",
    "direct_observation",
    "portfolio_review",
    "practical_exam",
    "peer_review",
    "written_exam",
    "interview",
]


def _proficiency_rows(skill):
    rows = []
    for i in range(6):
        entry = (skill.proficiency or {}).get(str(i), {})
        rows.append(
            {
                "num": i,
                "label": entry.get("label", ""),
                "description": entry.get("description", ""),
            }
        )
    return rows


def _display_values(value):
    """A mapping value as a list of strings to show as chips."""
    items = value if isinstance(value, list) else [value]
    return ["yes" if v is True else "no" if v is False else str(v) for v in items]


def _framework_display(mappings):
    """Flatten framework mappings into rows the detail template can render.

    A framework maps to a list of codes, an object of sub-lists (e.g. nice
    tks/work_roles), or a scalar, so each becomes a list of (key, values)
    pairs with an empty key where there is no sub-key.
    """
    rows = []
    for framework, mapping in (mappings or {}).items():
        if isinstance(mapping, dict):
            entries = [(key, _display_values(value)) for key, value in mapping.items()]
        else:
            entries = [("", _display_values(mapping))]
        rows.append(
            {
                "key": framework,
                "label": FRAMEWORK_LABELS.get(framework, framework),
                "entries": entries,
            }
        )
    return rows


def _mappings_json(mappings):
    return json.dumps(mappings or {}, indent=2, ensure_ascii=False)


@role_required("manager")
def skill_edit(request, skill_id):
    skill = get_object_or_404(Skill, pk=skill_id)

    if request.method == "POST":
        errors = []
        try:
            status = parse_choice(
                request.POST.get("status"),
                "status",
                Skill.STATUS_CHOICES,
                default=skill.status,
            )
        except ValidationError as e:
            errors.extend(e.messages)
            status = skill.status

        try:
            method_count = parse_bounded_int(
                request.POST.get("method_count"),
                "assessment method count",
                0,
                50,
                default=0,
            )
        except ValidationError as e:
            errors.extend(e.messages)
            method_count = 0

        # Absent from the POST means the form didn't send it: keep what is stored.
        mappings_raw = request.POST.get("framework_mappings")
        mappings = skill.framework_mappings
        if mappings_raw is not None:
            try:
                mappings = parse_json_object(mappings_raw, "framework mappings")
            except ValidationError as e:
                errors.extend(e.messages)

        if errors:
            return render(
                request,
                "taxonomy/skill_form.html",
                {
                    "skill": skill,
                    "errors": errors,
                    "tags_str": request.POST.get("tags", ""),
                    "proficiency_levels": _proficiency_rows(skill),
                    "assessment_methods": skill.assessment_methods or [],
                    "method_types": METHOD_TYPES,
                    "equipment_str": request.POST.get("equipment", ""),
                    "framework_mappings_json": (
                        mappings_raw
                        if mappings_raw is not None
                        else _mappings_json(skill.framework_mappings)
                    ),
                },
            )

        skill.name = request.POST.get("name", skill.name)
        skill.category = request.POST.get("category", skill.category)
        skill.description = request.POST.get("description", skill.description)
        skill.status = status

        skill.tags = [t.strip() for t in request.POST.get("tags", "").split(",") if t.strip()]
        skill.equipment = [
            e.strip() for e in request.POST.get("equipment", "").splitlines() if e.strip()
        ]

        # Proficiency levels. The form edits only label and description, so
        # merge into the stored level to keep its evidence and authorization.
        existing_prof = skill.proficiency or {}
        prof = {}
        for i in range(6):
            label = request.POST.get(f"prof_{i}_label", "").strip()
            desc = request.POST.get(f"prof_{i}_description", "").strip()
            if label or desc:
                prof[str(i)] = {
                    **existing_prof.get(str(i), {}),
                    "label": label,
                    "description": desc,
                }
        skill.proficiency = prof

        # Assessment methods
        methods = []
        for i in range(method_count):
            mtype = request.POST.get(f"method_{i}_type", "").strip()
            mdesc = request.POST.get(f"method_{i}_desc", "").strip()
            if mtype and mdesc:
                methods.append({"type": mtype, "description": mdesc})
        skill.assessment_methods = methods

        skill.framework_mappings = mappings

        skill.save()
        return redirect("taxonomy:skill-detail", skill_id=skill.id)

    return render(
        request,
        "taxonomy/skill_form.html",
        {
            "skill": skill,
            "tags_str": ", ".join(skill.tags) if skill.tags else "",
            "proficiency_levels": _proficiency_rows(skill),
            "assessment_methods": skill.assessment_methods or [],
            "method_types": METHOD_TYPES,
            "equipment_str": "\n".join(skill.equipment) if skill.equipment else "",
            "framework_mappings_json": _mappings_json(skill.framework_mappings),
        },
    )


@role_required("user")
def profile_list(request):
    meta = TaxonomyMeta.load()
    profile_order = {pid: idx for idx, pid in enumerate(meta.profile_order or [])}

    profiles = Profile.objects.select_related("domain").all()
    profile_data = []
    for profile in profiles:
        level_count = len(profile.maturity_levels) if profile.maturity_levels else 0
        profile_data.append(
            {
                "profile": profile,
                "domain_name": profile.domain.name if profile.domain else "---",
                "level_count": level_count,
                "sort_key": profile_order.get(profile.id, 999),
            }
        )
    profile_data.sort(key=lambda d: d["sort_key"])
    return render(request, "taxonomy/profile_list.html", {"profile_data": profile_data})


@role_required("manager")
def profile_reorder(request):
    """Save new profile order from drag-and-drop."""
    if request.method != "POST":
        return redirect("taxonomy:profile-list")
    try:
        order = _parse_id_list(request)
    except ValidationError as e:
        return HttpResponseBadRequest("; ".join(e.messages))
    meta = TaxonomyMeta.load()
    meta.profile_order = order
    meta.save()
    return JsonResponse({"ok": True})


MATURITY_LEVEL_KEYS = ["junior", "practitioner", "senior", "lead", "principal"]
# level_forms context field -> posted input suffix (ml_<level>_<suffix>)
LEVEL_FORM_FIELDS = {
    "title": "title",
    "description": "description",
    "dsa_str": "dsa",
    "min_categories": "min_categories",
    "foundation_avg": "foundation_avg",
    "pinned_str": "pinned",
}


@role_required("manager")
def profile_edit(request, profile_id):
    profile = get_object_or_404(Profile, pk=profile_id)

    if request.method == "POST":
        profile.name = request.POST.get("name", profile.name).strip()
        profile.description = request.POST.get("description", profile.description).strip()

        maturity_levels = {}
        errors = []
        for level_key in MATURITY_LEVEL_KEYS:
            title = request.POST.get(f"ml_{level_key}_title", "").strip()
            desc = request.POST.get(f"ml_{level_key}_description", "").strip()
            if not title:
                continue  # Skip levels with no title (disabled)
            label = level_key.title()

            # Thresholds
            thresholds = {}

            # domain_skills_at: "level:count" lines
            dsa = {}
            for line in request.POST.get(f"ml_{level_key}_dsa", "").splitlines():
                line = line.strip()
                if not line:
                    continue
                if ":" not in line:
                    errors.append(f"{label} skills-at line: expected level:count, got {line!r}.")
                    continue
                level_raw, count_raw = (part.strip() for part in line.split(":", 1))
                try:
                    level = parse_level(level_raw, f"{label} skills-at level")
                    dsa[str(level)] = parse_bounded_int(
                        count_raw, f"{label} skills-at count for level {level}", 0, 1000
                    )
                except ValidationError as e:
                    errors.extend(e.messages)
            if dsa:
                thresholds["domain_skills_at"] = dsa

            min_cats = request.POST.get(f"ml_{level_key}_min_categories", "").strip()
            if min_cats:
                try:
                    thresholds["min_categories"] = parse_bounded_int(
                        min_cats, f"{label} minimum categories", 0, 100
                    )
                except ValidationError as e:
                    errors.extend(e.messages)

            found_avg = request.POST.get(f"ml_{level_key}_foundation_avg", "").strip()
            if found_avg:
                try:
                    avg = float(found_avg)
                except ValueError:
                    errors.append(
                        f"{label} foundation average must be a number, got {found_avg!r}."
                    )
                else:
                    if LEVEL_MIN <= avg <= LEVEL_MAX:
                        thresholds["foundation_avg"] = avg
                    else:
                        errors.append(
                            f"{label} foundation average must be between "
                            f"{LEVEL_MIN} and {LEVEL_MAX}, got {avg}."
                        )

            # Pinned skills: "SKILL-ID:level" lines
            pinned, pinned_errors = _parse_skill_levels(
                request.POST.get(f"ml_{level_key}_pinned", ""), f"{label} pinned skills"
            )
            errors.extend(pinned_errors)

            level_data = {"title": title}
            if desc:
                level_data["description"] = desc
            if thresholds:
                level_data["thresholds"] = thresholds
            if pinned:
                level_data["pinned"] = pinned

            maturity_levels[level_key] = level_data

        if errors:
            return render(
                request,
                "taxonomy/partials/profile_form.html",
                {
                    "profile": profile,
                    "errors": errors,
                    # Echo what was posted, so a correction does not mean retyping.
                    "level_forms": [
                        {
                            "key": key,
                            "label": key.title(),
                            **{
                                field: request.POST.get(f"ml_{key}_{posted}", "")
                                for field, posted in LEVEL_FORM_FIELDS.items()
                            },
                        }
                        for key in MATURITY_LEVEL_KEYS
                    ],
                },
            )

        profile.maturity_levels = maturity_levels
        profile.save()
        return redirect("taxonomy:profile-detail", profile_id=profile.id)

    # Build template context for each maturity level
    level_forms = []
    existing = profile.maturity_levels or {}
    for level_key in MATURITY_LEVEL_KEYS:
        level_def = existing.get(level_key, {})
        thresholds = level_def.get("thresholds", {})
        dsa = thresholds.get("domain_skills_at", {})
        pinned = level_def.get("pinned", [])

        dsa_str = "\n".join(f"{k}:{v}" for k, v in dsa.items()) if dsa else ""
        pinned_str = (
            "\n".join(f"{p['skill']}:{p.get('minimum_level', 0)}" for p in pinned) if pinned else ""
        )

        level_forms.append(
            {
                "key": level_key,
                "label": level_key.title(),
                "title": level_def.get("title", ""),
                "description": level_def.get("description", ""),
                "dsa_str": dsa_str,
                "min_categories": thresholds.get("min_categories", ""),
                "foundation_avg": thresholds.get("foundation_avg", ""),
                "pinned_str": pinned_str,
            }
        )

    return render(
        request,
        "taxonomy/partials/profile_form.html",
        {
            "profile": profile,
            "level_forms": level_forms,
        },
    )


@role_required("user")
def profile_detail(request, profile_id):
    profile = get_object_or_404(Profile, pk=profile_id)

    maturity_data = []
    for level_name in ["junior", "practitioner", "senior", "lead", "principal"]:
        level_def = (profile.maturity_levels or {}).get(level_name)
        if level_def:
            maturity_data.append(
                {
                    "level": level_name,
                    "title": level_def.get("title", level_name.title()),
                    "description": level_def.get("description", ""),
                    "thresholds": level_def.get("thresholds", {}),
                    "pinned": level_def.get("pinned", []),
                }
            )

    # Enrich pinned entries with skill names
    pinned_skill_ids = set()
    for md in maturity_data:
        for p in md["pinned"]:
            pinned_skill_ids.add(p["skill"])
    pinned_names = {}
    if pinned_skill_ids:
        for s in Skill.objects.using("taxonomy").filter(id__in=pinned_skill_ids):
            pinned_names[s.id] = s.name

    # Add skill_name to each pinned entry for easy template access
    for md in maturity_data:
        for p in md["pinned"]:
            p["skill_name"] = pinned_names.get(p["skill"], p["skill"])

    return render(
        request,
        "taxonomy/profile_detail.html",
        {
            "profile": profile,
            "maturity_data": maturity_data,
        },
    )


@role_required("user")
def service_list(request):
    meta = TaxonomyMeta.load()
    service_order = {sid: idx for idx, sid in enumerate(meta.service_order or [])}

    services = Service.objects.all()
    service_data = []
    for service in services:
        competency_count = (
            len(service.required_competencies) if service.required_competencies else 0
        )
        standards_count = len(service.standards) if service.standards else 0
        service_data.append(
            {
                "service": service,
                "competency_count": competency_count,
                "standards_count": standards_count,
                "sort_key": service_order.get(service.id, 999),
            }
        )
    service_data.sort(key=lambda d: d["sort_key"])
    return render(request, "taxonomy/service_list.html", {"service_data": service_data})


@role_required("manager")
def service_edit(request, service_id):
    service = get_object_or_404(Service, pk=service_id)

    if request.method == "POST":
        service.name = request.POST.get("name", service.name).strip()
        service.description = request.POST.get("description", service.description).strip()
        service.scope_reference = request.POST.get("scope_reference", "").strip()

        # Standards: one per line
        standards_raw = request.POST.get("standards", "").strip()
        service.standards = (
            [s.strip() for s in standards_raw.splitlines() if s.strip()] if standards_raw else []
        )

        # Required competencies: "SKILL-ID:level" per line
        comps_raw = request.POST.get("competencies", "")
        competencies, errors = _parse_skill_levels(comps_raw, "Required competencies")
        if errors:
            return render(
                request,
                "taxonomy/partials/service_form.html",
                {
                    "service": service,
                    "errors": errors,
                    "comps_str": comps_raw,
                    "standards_str": standards_raw,
                },
            )
        service.required_competencies = competencies

        service.save()
        return redirect("taxonomy:service-detail", service_id=service.id)

    # Build context
    comps_str = ""
    if service.required_competencies:
        comps_str = "\n".join(
            f"{c['skill']}:{c.get('minimum_level', 0)}" for c in service.required_competencies
        )

    standards_str = "\n".join(service.standards) if service.standards else ""

    return render(
        request,
        "taxonomy/partials/service_form.html",
        {
            "service": service,
            "comps_str": comps_str,
            "standards_str": standards_str,
        },
    )


@role_required("user")
def service_detail(request, service_id):
    service = get_object_or_404(Service, pk=service_id)

    # Enrich required competencies with skill names
    enriched_competencies = []
    if service.required_competencies:
        skill_ids = [c["skill"] for c in service.required_competencies]
        skills_map = {s.id: s for s in Skill.objects.filter(id__in=skill_ids)}
        for comp in service.required_competencies:
            skill_obj = skills_map.get(comp["skill"])
            enriched_competencies.append(
                {
                    "skill_id": comp["skill"],
                    "skill_name": skill_obj.name if skill_obj else comp["skill"],
                    "skill_exists": skill_obj is not None,
                    "minimum_level": comp.get("minimum_level", 0),
                }
            )

    # Check for qualified personnel per competency
    has_personnel = False
    try:
        from apps.personnel.models import PersonSkill

        for comp in enriched_competencies:
            count = PersonSkill.objects.filter(
                skill_id=comp["skill_id"],
                level__gte=comp["minimum_level"],
            ).count()
            comp["qualified_count"] = count
        has_personnel = True
    except Exception:
        pass

    return render(
        request,
        "taxonomy/service_detail.html",
        {
            "service": service,
            "competencies": enriched_competencies,
            "has_personnel": has_personnel,
        },
    )
