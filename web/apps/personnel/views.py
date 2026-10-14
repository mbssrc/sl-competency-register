import datetime

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounts.decorators import owner_or_role, role_required
from apps.core.export import generate_self_assessment_workbook
from apps.core.validators import parse_choice, parse_date, parse_level
from apps.taxonomy.models import Domain, Service, Skill

from .models import (
    Person,
    PersonSkill,
    Project,
    SelfAssessment,
    unique_person_id,
    unique_project_id,
)
from .services import (
    DEFAULT_MINIMUM_LEVEL,
    compute_all_domain_maturities,
    compute_domain_coverage,
    compute_person_project_fitness,
    compute_project_coverage,
    compute_service_readiness,
    project_skill_table,
)

# Foundations is the shared base every ladder measures against, not a domain
# anyone is assigned to.
FOUNDATIONS_DOMAIN_ID = "FOUND"


@role_required("manager")
def person_list(request):
    people = Person.objects.prefetch_related("skills", "development_plans").all()

    # Look up domain names from taxonomy DB
    all_domain_ids = set()
    for person in people:
        all_domain_ids.update(person.domains or [])

    domain_names = {}
    if all_domain_ids:
        domains = Domain.objects.using("taxonomy").filter(id__in=all_domain_ids)
        domain_names = {d.id: d.name for d in domains}

    person_data = []
    for person in people:
        skill_count = person.skills.filter(level__gte=1).count()
        plan_count = person.development_plans.count()
        # Foundations is the shared base, not a specialism: the person form
        # does not offer it and no ladder grades it. Records written before
        # that rule still carry it, so it is filtered here rather than shown
        # as a domain the person is assigned to.
        domains_info = [
            {"id": did, "name": domain_names.get(did, did)}
            for did in (person.domains or [])
            if did != FOUNDATIONS_DOMAIN_ID
        ]
        person_data.append(
            {
                "person": person,
                "skill_count": skill_count,
                "plan_count": plan_count,
                "domains": domains_info,
            }
        )

    return render(request, "personnel/person_list.html", {"person_data": person_data})


@owner_or_role("manager")
def person_detail(request, person_id):
    person = get_object_or_404(Person, pk=person_id)

    # Domain maturity
    domain_maturities = compute_all_domain_maturities(person)

    # Skills with taxonomy names and domain info
    show_zero = request.GET.get("show_zero", "") == "1"
    show_managed = request.GET.get("managed", "1") == "1"
    show_self = request.GET.get("self", "1") == "1"

    # Get self-assessment skill IDs with level > 0
    self_assessed_ids = set(
        person.self_assessments.filter(level__gt=0).values_list("skill_id", flat=True)
    )

    person_skills = person.skills.all().order_by("skill_id")
    if not show_zero:
        if show_managed and show_self:
            # Show skills where either managed level > 0 OR self-assessment > 0
            from django.db.models import Q

            person_skills = person_skills.filter(Q(level__gt=0) | Q(skill_id__in=self_assessed_ids))
        elif show_managed:
            person_skills = person_skills.exclude(level=0)
        elif show_self:
            person_skills = person_skills.filter(skill_id__in=self_assessed_ids)
        else:
            person_skills = person_skills.none()
    skill_ids = [ps.skill_id for ps in person_skills]
    skill_info = {}
    if skill_ids:
        for s in Skill.objects.using("taxonomy").filter(id__in=skill_ids).select_related("domain"):
            prof = s.proficiency or {}
            level_labels = {}
            for n in range(6):
                entry = prof.get(str(n), {})
                level_labels[n] = entry.get("label", "")
            skill_info[s.id] = {
                "name": s.name,
                "domain_id": s.domain_id,
                "domain_name": s.domain.name,
                "level_labels": level_labels,
            }

    # Self-assessments
    self_assessments = {sa.skill_id: sa for sa in person.self_assessments.all()}

    # Group skills by domain, ordered by taxonomy meta
    from collections import OrderedDict

    from apps.core.models import TaxonomyMeta

    domain_order = TaxonomyMeta.domain_sort_key()

    skills_by_domain = {}
    for ps in person_skills:
        info = skill_info.get(ps.skill_id, {})
        domain_id = info.get("domain_id", "")
        domain_name = info.get("domain_name", "Unknown")
        sa = self_assessments.get(ps.skill_id)
        self_level = sa.level if sa else None
        delta = self_level - ps.level if self_level is not None else None
        level_labels = info.get("level_labels", {})
        entry = {
            "person_skill": ps,
            "skill_name": info.get("name", ps.skill_id),
            "skill_exists": ps.skill_id in skill_info,
            "self_level": self_level,
            "delta": delta,
            "level_label": level_labels.get(ps.level, ""),
            "self_label": level_labels.get(self_level, "") if self_level is not None else "",
        }
        skills_by_domain.setdefault((domain_order.get(domain_id, 999), domain_name), []).append(
            entry
        )

    skills_by_domain = OrderedDict(
        (name, skills) for (_, name), skills in sorted(skills_by_domain.items())
    )
    total_visible = sum(len(v) for v in skills_by_domain.values())

    # Development plans with skill names
    dev_plans = person.development_plans.all().order_by("target_date")
    plan_skill_ids = [dp.skill_id for dp in dev_plans]
    plan_skill_names = {}
    if plan_skill_ids:
        plan_skills = Skill.objects.using("taxonomy").filter(id__in=plan_skill_ids)
        plan_skill_names = {s.id: s.name for s in plan_skills}

    enriched_plans = []
    for dp in dev_plans:
        enriched_plans.append(
            {
                "plan": dp,
                "skill_name": plan_skill_names.get(dp.skill_id, dp.skill_id),
            }
        )

    # Project fitness — how well does this person match each open project?
    project_fitness = [
        fitness
        for fitness in (
            compute_person_project_fitness(person, proj)
            for proj in Project.objects.filter(status="planning").order_by("-updated_at")
        )
        if fitness is not None
    ]

    return render(
        request,
        "personnel/person_detail.html",
        {
            "person": person,
            "domain_maturities": domain_maturities,
            "skills_by_domain": skills_by_domain,
            "total_visible": total_visible,
            "total_skills": person.skills.count(),
            "show_zero": show_zero,
            "show_managed": show_managed,
            "show_self": show_self,
            "project_fitness": project_fitness,
            "plans": enriched_plans,
        },
    )


def _is_htmx(request):
    return request.headers.get("HX-Request") == "true"


def _person_form_template(request):
    return (
        "personnel/partials/person_form.html" if _is_htmx(request) else "personnel/person_form.html"
    )


def _all_domains():
    """Return all domains from taxonomy DB, ordered by name."""
    return list(Domain.objects.using("taxonomy").order_by("name").values_list("id", "name"))


@role_required("manager")
def person_create(request):
    all_domains = _all_domains()

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        selected_domains = request.POST.getlist("domains")

        errors = []
        if not name:
            errors.append("Name is required.")

        start_date = None
        try:
            start_date = parse_date(request.POST.get("start_date"), "start date")
        except ValidationError as e:
            errors.extend(e.messages)

        # Auto-generate ID from name
        person_id = unique_person_id(name) if not errors else ""

        if errors:
            return render(
                request,
                _person_form_template(request),
                {
                    "errors": errors,
                    "form_data": request.POST,
                    "all_domains": all_domains,
                    "selected_domains": selected_domains,
                    "editing": False,
                },
            )

        if "FOUND" not in selected_domains:
            selected_domains.insert(0, "FOUND")
        Person.objects.create(
            id=person_id,
            name=name,
            start_date=start_date,
            domains=selected_domains,
        )
        return redirect("personnel:person-detail", person_id=person_id)

    return render(
        request,
        _person_form_template(request),
        {
            "all_domains": all_domains,
            "editing": False,
        },
    )


@role_required("manager")
def person_edit(request, person_id):
    person = get_object_or_404(Person, pk=person_id)
    all_domains = _all_domains()

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        selected_domains = request.POST.getlist("domains")

        errors = []
        if not name:
            errors.append("Name is required.")

        start_date = None
        try:
            start_date = parse_date(request.POST.get("start_date"), "start date")
        except ValidationError as e:
            errors.extend(e.messages)

        if errors:
            return render(
                request,
                _person_form_template(request),
                {
                    "errors": errors,
                    "form_data": request.POST,
                    "edit_person": person,
                    "all_domains": all_domains,
                    "selected_domains": selected_domains,
                    "editing": True,
                },
            )

        if "FOUND" not in selected_domains:
            selected_domains.insert(0, "FOUND")
        person.name = name
        person.start_date = start_date
        person.domains = selected_domains
        person.save()
        return redirect("personnel:person-detail", person_id=person.id)

    return render(
        request,
        _person_form_template(request),
        {
            "edit_person": person,
            "all_domains": all_domains,
            "selected_domains": person.domains or [],
            "editing": True,
        },
    )


@role_required("manager")
def person_skill_add(request, person_id):
    person = get_object_or_404(Person, pk=person_id)
    all_skills = (
        Skill.objects.using("taxonomy")
        .filter(status="active")
        .select_related("domain")
        .order_by("domain_id", "name")
    )

    # Exclude skills already assigned
    existing_skill_ids = set(person.skills.values_list("skill_id", flat=True))
    available_skills = [s for s in all_skills if s.id not in existing_skill_ids]
    template = (
        "personnel/partials/skill_add_form.html"
        if _is_htmx(request)
        else "personnel/skill_add_form.html"
    )
    context = {"person": person, "available_skills": available_skills}

    if request.method == "POST":
        skill_id = request.POST.get("skill_id", "").strip()
        errors = []
        if not skill_id:
            errors.append("Skill is required.")
        try:
            level = parse_level(request.POST.get("level"), "level", default=0)
        except ValidationError as e:
            errors.extend(e.messages)
        try:
            assessed_date = parse_date(request.POST.get("assessed_date"), "assessed date")
        except ValidationError as e:
            errors.extend(e.messages)

        if not errors:
            person_skill = PersonSkill(
                person=person,
                skill_id=skill_id,
                level=level,
                assessed_date=assessed_date,
                assessed_by_id=request.user.username,
                evidence_notes=request.POST.get("evidence_notes", "").strip(),
            )
            # Checks the skill exists in the taxonomy and is not yet assigned.
            try:
                person_skill.full_clean()
            except ValidationError as e:
                errors.extend(e.messages)

        if errors:
            return render(
                request, template, {**context, "errors": errors, "form_data": request.POST}
            )
        person_skill.save()
        return redirect("personnel:person-detail", person_id=person.id)

    return render(request, template, context)


@role_required("manager")
def person_skill_edit(request, person_id, skill_id):
    person = get_object_or_404(Person, pk=person_id)
    person_skill = get_object_or_404(PersonSkill, person=person, skill_id=skill_id)

    try:
        skill = Skill.objects.using("taxonomy").get(id=skill_id)
        skill_name = skill.name
    except Skill.DoesNotExist:
        skill_name = skill_id

    if request.method == "POST":
        errors = []
        level = person_skill.level
        assessed_date = person_skill.assessed_date
        try:
            level = parse_level(request.POST.get("level"), "level")
        except ValidationError as e:
            errors.extend(e.messages)
        try:
            assessed_date = parse_date(request.POST.get("assessed_date"), "assessed date")
        except ValidationError as e:
            errors.extend(e.messages)

        if errors:
            return render(
                request,
                "personnel/partials/skill_edit_modal.html",
                {
                    "person_skill": person_skill,
                    "skill_name": skill_name,
                    "person": person,
                    "errors": errors,
                },
            )

        person_skill.level = level
        person_skill.assessed_date = assessed_date
        person_skill.assessed_by_id = request.user.username
        person_skill.evidence_notes = request.POST.get("evidence_notes", "")
        person_skill.is_self_assessed = False
        try:
            person_skill.full_clean()
        except ValidationError as e:
            return render(
                request,
                "personnel/partials/skill_edit_modal.html",
                {
                    "person_skill": person_skill,
                    "skill_name": skill_name,
                    "person": person,
                    "errors": e.messages,
                },
            )
        person_skill.save()
        return redirect("personnel:person-detail", person_id=person.id)

    return render(
        request,
        "personnel/partials/skill_edit_modal.html",
        {
            "person_skill": person_skill,
            "skill_name": skill_name,
            "person": person,
        },
    )


@role_required("admin")
def person_delete(request, person_id):
    if request.method != "POST":
        return redirect("personnel:person-detail", person_id=person_id)
    person = get_object_or_404(Person, pk=person_id)
    person.delete()
    return redirect("personnel:person-list")


@role_required("manager")
def person_skill_delete(request, person_id, skill_id):
    if request.method != "POST":
        return redirect("personnel:person-detail", person_id=person_id)
    PersonSkill.objects.filter(person_id=person_id, skill_id=skill_id).delete()
    return redirect("personnel:person-detail", person_id=person_id)


@role_required("manager")
def gap_analysis(request):
    people = Person.objects.prefetch_related("skills").all()

    # --- Personnel maturity gaps ---
    all_data = []
    for person in people:
        maturities = compute_all_domain_maturities(person)
        for m in maturities:
            if m["next_gaps"] and m["next_gaps"].get("gaps"):
                all_data.append(
                    {
                        "person_id": person.id,
                        "person_name": person.name,
                        "domain_id": m["domain_id"],
                        "domain_name": m["domain_name"],
                        "current_level": m["level"] or "none",
                        "current_title": m["title"] or "Below Junior",
                        "next_title": m["next_gaps"]["title"],
                        "gaps": m["next_gaps"]["gaps"],
                    }
                )

    filter_person = request.GET.get("person", "")
    filter_domain = request.GET.get("domain", "")

    filtered = all_data
    if filter_person:
        filtered = [d for d in filtered if d["person_id"] == filter_person]
    if filter_domain:
        filtered = [d for d in filtered if d["domain_id"] == filter_domain]

    unique_persons = sorted({(d["person_id"], d["person_name"]) for d in all_data})
    unique_domains = sorted({(d["domain_id"], d["domain_name"]) for d in all_data})

    # --- Domain coverage ---
    domain_coverage = compute_domain_coverage()
    total_skills = sum(d["total_skills"] for d in domain_coverage)
    total_covered_l1 = sum(d["covered_l1"] for d in domain_coverage)
    total_covered_l3 = sum(d["covered_l3"] for d in domain_coverage)
    uncovered_skills = total_skills - total_covered_l1

    return render(
        request,
        "personnel/gap_analysis.html",
        {
            "gaps": filtered,
            "total_gaps": len(all_data),
            "people_with_gaps": len({d["person_id"] for d in all_data}),
            "unique_persons": unique_persons,
            "unique_domains": unique_domains,
            "filter_person": filter_person,
            "filter_domain": filter_domain,
            "domain_coverage": domain_coverage,
            "total_skills": total_skills,
            "total_covered_l1": total_covered_l1,
            "total_covered_l3": total_covered_l3,
            "uncovered_skills": uncovered_skills,
        },
    )


@role_required("manager")
def gap_analysis_export(request):
    from apps.core.export import generate_gap_analysis_workbook

    wb = generate_gap_analysis_workbook()
    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = 'attachment; filename="gap-analysis-export.xlsx"'
    wb.save(response)
    return response


@role_required("manager")
def service_readiness(request):
    results = compute_service_readiness()

    fully_staffable = sum(1 for r in results if r["fully_staffable"])
    with_gaps = sum(1 for r in results if not r["fully_staffable"])

    return render(
        request,
        "personnel/service_readiness.html",
        {
            "services": results,
            "fully_staffable": fully_staffable,
            "with_gaps": with_gaps,
            "total_services": len(results),
        },
    )


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------


@role_required("user")
def project_list(request):
    filter_status = request.GET.get("status", "")
    projects = Project.objects.all()
    if filter_status:
        projects = projects.filter(status=filter_status)

    project_data = []
    for proj in projects:
        comps = proj.required_competencies or []
        coverage = compute_project_coverage(proj) if comps else []
        covered = sum(1 for c in coverage if c["is_covered"])
        project_data.append(
            {
                "project": proj,
                "comp_count": len(comps),
                "coverage_pct": round(100 * covered / len(comps)) if comps else 0,
            }
        )

    return render(
        request,
        "personnel/project_list.html",
        {
            "projects": project_data,
            "filter_status": filter_status,
            "status_choices": Project.STATUS_CHOICES,
        },
    )


@role_required("manager")
def project_create(request):
    services = Service.objects.using("taxonomy").all()
    svc_data = [
        {"id": s.id, "name": s.name, "comp_count": len(s.required_competencies or [])}
        for s in services
    ]

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        description = request.POST.get("description", "").strip()
        selected_services = request.POST.getlist("source_services")

        errors = []
        if not name:
            errors.append("Project name is required.")

        if errors:
            return render(
                request,
                "personnel/partials/project_form.html",
                {
                    "errors": errors,
                    "form_data": request.POST,
                    "services": svc_data,
                    "editing": False,
                },
            )

        # Auto-generate ID
        proj_id = unique_project_id(name)

        # Merge competencies from selected service templates
        competencies = []
        seen_skills = set()
        source_ids = []
        for svc_id in selected_services:
            try:
                svc = Service.objects.using("taxonomy").get(id=svc_id)
                source_ids.append(svc.id)
                for comp in svc.required_competencies or []:
                    if comp["skill"] not in seen_skills:
                        seen_skills.add(comp["skill"])
                        competencies.append(comp)
            except Service.DoesNotExist:
                pass

        Project.objects.create(
            id=proj_id,
            name=name,
            description=description,
            required_competencies=competencies,
            source_service_id=", ".join(source_ids),
            created_by_id=request.user.username,
        )
        return redirect("personnel:project-detail", project_id=proj_id)

    return render(
        request,
        "personnel/partials/project_form.html",
        {
            "services": svc_data,
            "editing": False,
        },
    )


@role_required("manager")
def project_edit(request, project_id):
    project = get_object_or_404(Project, pk=project_id)

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        description = request.POST.get("description", "").strip()

        errors = []
        if not name:
            errors.append("Project name is required.")

        status = project.status
        try:
            status = parse_choice(
                request.POST.get("status"),
                "status",
                Project.STATUS_CHOICES,
                default=project.status,
            )
        except ValidationError as e:
            errors.extend(e.messages)

        if errors:
            return render(
                request,
                "personnel/partials/project_form.html",
                {
                    "errors": errors,
                    "form_data": request.POST,
                    "edit_project": project,
                    "status_choices": Project.STATUS_CHOICES,
                    "editing": True,
                },
            )

        old_status = project.status
        project.name = name
        project.description = description
        project.status = status
        project.save()

        # Transition to "done" → redirect to assessment page
        if status == "done" and old_status != "done" and project.required_competencies:
            return redirect("personnel:project-assess", project_id=project.id)

        return redirect("personnel:project-detail", project_id=project.id)

    return render(
        request,
        "personnel/partials/project_form.html",
        {
            "edit_project": project,
            "status_choices": Project.STATUS_CHOICES,
            "editing": True,
        },
    )


@role_required("user")
def project_detail(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    return _render_project_detail(request, project)


def _render_project_detail(request, project, selection=None, errors=None):
    is_manager = request.user.is_manager

    coverage = compute_project_coverage(project, include_personnel=is_manager)
    comp_count = len(coverage)
    covered = sum(1 for c in coverage if c["is_covered"])
    coverage_pct = round(100 * covered / comp_count) if comp_count else None

    # Managers get the full skill table; it names colleagues, so users don't.
    skill_rows = skill_holders = None
    if is_manager:
        skill_rows, skill_holders = project_skill_table(project, selection)

    # A user sees their own standing against the project instead of the roster.
    my_fitness = None
    if not is_manager and request.user.person_id:
        my_fitness = compute_person_project_fitness(request.user.person, project)

    return render(
        request,
        "personnel/project_detail.html",
        {
            "project": project,
            "coverage": coverage,
            "coverage_pct": coverage_pct,
            "is_manager": is_manager,
            "my_fitness": my_fitness,
            "skill_rows": skill_rows,
            "skill_holders": skill_holders,
            "errors": errors,
        },
    )


@role_required("manager")
def project_skills(request, project_id):
    """Replace a project's required skills with the ticked rows of its skill table."""
    project = get_object_or_404(Project, pk=project_id)
    if request.method != "POST":
        return redirect("personnel:project-detail", project_id=project.id)

    current = {c["skill"]: c["minimum_level"] for c in project.required_competencies or []}
    ticked = list(dict.fromkeys(filter(None, (s.strip() for s in request.POST.getlist("skill")))))
    statuses = dict(
        Skill.objects.using("taxonomy").filter(id__in=ticked).values_list("id", "status")
    )

    errors = []
    selection = {}
    for skill_id in ticked:
        # Deprecated or vanished skills may stay on a project, but not be added.
        if skill_id not in current and statuses.get(skill_id) != "active":
            if skill_id in statuses:
                errors.append(f"Skill '{skill_id}' is deprecated and can't be added.")
            else:
                errors.append(f"Skill '{skill_id}' does not exist in taxonomy.")
            continue
        try:
            selection[skill_id] = parse_level(
                request.POST.get(f"level_{skill_id}"),
                f"Minimum level for {skill_id}",
                default=DEFAULT_MINIMUM_LEVEL,
            )
        except ValidationError as e:
            errors.extend(e.messages)
            selection[skill_id] = current.get(skill_id, DEFAULT_MINIMUM_LEVEL)

    if errors:
        return _render_project_detail(request, project, selection=selection, errors=errors)

    # Kept requirements hold their position (it orders the assessment grid); new ones follow.
    kept = [skill_id for skill_id in current if skill_id in selection]
    added = [skill_id for skill_id in selection if skill_id not in current]
    project.required_competencies = [
        {"skill": skill_id, "minimum_level": selection[skill_id]} for skill_id in kept + added
    ]
    project.save()
    return redirect("personnel:project-detail", project_id=project.id)


@role_required("manager")
def project_assess(request, project_id):
    """After marking a project done, assess personnel skills."""
    project = get_object_or_404(Project, pk=project_id)
    requirements = project.required_competencies or []
    skill_ids = [c["skill"] for c in requirements]
    skill_names = {}
    if skill_ids:
        for s in Skill.objects.using("taxonomy").filter(id__in=skill_ids):
            skill_names[s.id] = s.name

    people = Person.objects.all().order_by("name")
    today = datetime.date.today()

    if request.method == "POST":
        marker = f"Project: {project.name}"
        updates = []
        for person in people:
            for comp in requirements:
                field = f"person_{person.id}_skill_{comp['skill']}"
                level_str = (request.POST.get(field) or "").strip()
                if not level_str or level_str == "-":
                    continue
                try:
                    level = parse_level(level_str, f"level for {person.name}")
                except ValidationError:
                    continue
                updates.append((person, comp["skill"], level))

        with transaction.atomic():
            for person, skill_id, level in updates:
                try:
                    ps = PersonSkill.objects.get(person=person, skill_id=skill_id)
                except PersonSkill.DoesNotExist:
                    PersonSkill.objects.create(
                        person=person,
                        skill_id=skill_id,
                        level=level,
                        assessed_date=today,
                        assessed_by_id=request.user.username,
                        last_practiced=today,
                        evidence_notes=marker,
                        is_self_assessed=False,
                    )
                    continue

                if ps.level == level:
                    # The form preselects current levels; an untouched cell is
                    # not a new assessment and must not be stamped as one.
                    continue

                ps.level = level
                ps.assessed_date = today
                ps.assessed_by_id = request.user.username
                ps.last_practiced = today
                ps.is_self_assessed = False
                existing = (ps.evidence_notes or "").strip()
                if marker not in existing:
                    ps.evidence_notes = f"{existing}\n{marker}".strip() if existing else marker
                ps.save()

        return redirect("personnel:project-detail", project_id=project.id)

    # GET: build assessment matrix
    # For each person, get their current levels for the project's skills
    assessment_data = []
    for person in people:
        current = {ps.skill_id: ps.level for ps in person.skills.filter(skill_id__in=skill_ids)}
        person_skills = []
        for comp in requirements:
            person_skills.append(
                {
                    "skill_id": comp["skill"],
                    "skill_name": skill_names.get(comp["skill"], comp["skill"]),
                    "minimum_level": comp["minimum_level"],
                    "current_level": current.get(comp["skill"]),
                }
            )
        assessment_data.append(
            {
                "person": person,
                "skills": person_skills,
            }
        )

    return render(
        request,
        "personnel/project_assess.html",
        {
            "project": project,
            "assessment_data": assessment_data,
            "requirements": requirements,
            "skill_names": skill_names,
        },
    )


# ---------------------------------------------------------------------------
# Self-Assessment
# ---------------------------------------------------------------------------

XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@owner_or_role("manager")
def self_assessment_export(request, person_id):
    person = get_object_or_404(Person, pk=person_id)
    wb = generate_self_assessment_workbook(person)
    filename = f"{person.name.lower().replace(' ', '-')}-self-assessment.xlsx"
    response = HttpResponse(content_type=XLSX_CONTENT_TYPE)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    wb.save(response)
    return response


EXPECTED_SHEET = "Self-Assessment"
# Column order written by generate_self_assessment_workbook.
EXPECTED_HEADERS = ["Skill ID", "Skill Name", "Domain", "Category", "Level"]
COL_SKILL_ID = 0
COL_LEVEL = 4
COL_NOTES = 6
MAX_IMPORT_ERRORS_SHOWN = 50


def _uncompressed_size(uploaded):
    """Total size the .xlsx zip expands to, read from its directory alone.

    openpyxl loads xl/sharedStrings.xml fully even in read_only mode, so a
    small upload can still expand to hundreds of megabytes; this check runs
    before any XML is parsed. Returns None for a file that is not a zip.
    """
    import zipfile

    try:
        with zipfile.ZipFile(uploaded) as archive:
            return sum(info.file_size for info in archive.infolist())
    except zipfile.BadZipFile:
        return None
    finally:
        uploaded.seek(0)


def _render_import(request, person, **extra):
    return render(
        request,
        "personnel/partials/self_assessment_import.html",
        {"person": person, **extra},
    )


@owner_or_role("manager")
def self_assessment_import(request, person_id):
    person = get_object_or_404(Person, pk=person_id)

    if request.method != "POST":
        return _render_import(request, person)

    uploaded = request.FILES.get("file")
    if not uploaded:
        return _render_import(request, person, errors=["No file uploaded."])

    limit = settings.MAX_IMPORT_FILE_SIZE
    if uploaded.size > limit:
        return _render_import(
            request,
            person,
            errors=[f"File is too large ({uploaded.size} bytes); the limit is {limit} bytes."],
        )

    expanded = _uncompressed_size(uploaded)
    if expanded is None:
        return _render_import(request, person, errors=["Invalid Excel file."])
    expanded_limit = settings.MAX_IMPORT_UNCOMPRESSED_SIZE
    if expanded > expanded_limit:
        return _render_import(
            request,
            person,
            errors=[
                f"Workbook is too large uncompressed ({expanded} bytes); "
                f"the limit is {expanded_limit} bytes."
            ],
        )

    from openpyxl import load_workbook

    try:
        wb = load_workbook(uploaded, read_only=True, data_only=True)
    except Exception:
        return _render_import(request, person, errors=["Invalid Excel file."])

    try:
        if EXPECTED_SHEET not in wb.sheetnames:
            return _render_import(
                request,
                person,
                errors=[
                    f"Workbook has no '{EXPECTED_SHEET}' sheet. Export a self-assessment "
                    f"workbook from this person's page and fill that in."
                ],
            )
        ws = wb[EXPECTED_SHEET]

        rows = ws.iter_rows(values_only=True)
        header = next(rows, None)
        if header is None:
            return _render_import(request, person, errors=["Workbook is empty."])
        actual = [str(c).strip() if c is not None else "" for c in header[: len(EXPECTED_HEADERS)]]
        if actual != EXPECTED_HEADERS:
            return _render_import(
                request,
                person,
                errors=[
                    "Unexpected column layout. Expected the first columns to be "
                    f"{', '.join(EXPECTED_HEADERS)} but found {', '.join(actual) or '(blank)'}."
                ],
            )

        valid_skill_ids = set(Skill.objects.using("taxonomy").values_list("id", flat=True))

        parsed = []
        errors = []
        max_rows = settings.MAX_IMPORT_ROWS
        for row_number, row in enumerate(rows, start=2):
            if row_number - 1 > max_rows:
                return _render_import(
                    request,
                    person,
                    errors=[
                        f"Workbook has more than {max_rows} rows; "
                        f"a self-assessment export has one row per skill."
                    ],
                )
            if len(row) <= COL_LEVEL:
                continue
            raw_id = row[COL_SKILL_ID]
            raw_level = row[COL_LEVEL]
            if raw_id is None and raw_level is None:
                continue  # genuinely blank row
            if raw_id is None:
                errors.append(f"Row {row_number}: no skill ID.")
                continue

            skill_id = str(raw_id).strip()
            if raw_level is None:
                continue  # left blank on purpose
            try:
                level = parse_level(raw_level, f"row {row_number} level")
            except ValidationError as e:
                errors.append(f"{skill_id}: {' '.join(e.messages)}")
                continue
            if skill_id not in valid_skill_ids:
                errors.append(f"{skill_id}: not found in taxonomy.")
                continue

            notes = row[COL_NOTES] if len(row) > COL_NOTES and row[COL_NOTES] else ""
            parsed.append((skill_id, level, str(notes).strip()))
    finally:
        wb.close()

    today = datetime.date.today()
    with transaction.atomic():
        for skill_id, level, notes in parsed:
            SelfAssessment.objects.update_or_create(
                person=person,
                skill_id=skill_id,
                defaults={
                    "level": level,
                    "assessed_date": today,
                    "evidence_notes": notes,
                },
            )
            PersonSkill.objects.get_or_create(
                person=person,
                skill_id=skill_id,
                defaults={
                    "level": 0,
                    "assessed_date": today,
                    "assessed_by_id": "self-assessment",
                },
            )

    if errors:
        shown = errors[:MAX_IMPORT_ERRORS_SHOWN]
        if len(errors) > len(shown):
            shown.append(f"… and {len(errors) - len(shown)} more not shown.")
        return _render_import(request, person, errors=shown, imported=len(parsed))
    return redirect("personnel:person-detail", person_id=person.id)


def _seedable_skills(person):
    """Determine which self-assessments can be seeded into PersonSkill.

    Seedable: no PersonSkill exists, or PersonSkill exists but has never been
    formally assessed (is_self_assessed=True or level=0 with assessed_by="self-assessment").
    Skipped: a formal assessment exists (is_self_assessed=False with a real assessor).
    """
    existing = {ps.skill_id: ps for ps in person.skills.all()}
    self_assessments = list(person.self_assessments.filter(level__gt=0))
    seedable, skipped = [], []
    for sa in self_assessments:
        ps = existing.get(sa.skill_id)
        if ps is None:
            # No managed record at all
            seedable.append(sa)
        elif ps.is_self_assessed or (ps.level == 0 and ps.assessed_by_id == "self-assessment"):
            # Exists but was auto-created or previously seeded — safe to update
            seedable.append(sa)
        else:
            # Formally assessed — never overwrite
            skipped.append(sa)
    return seedable, skipped


@role_required("manager")
def seed_self_assessment(request, person_id):
    """Copy self-assessments into PersonSkill where no formal assessment exists."""
    person = get_object_or_404(Person, pk=person_id)
    seedable, skipped = _seedable_skills(person)

    if request.method == "GET":
        return render(
            request,
            "personnel/partials/seed_confirm.html",
            {
                "person": person,
                "seedable_count": len(seedable),
                "skipped_count": len(skipped),
            },
        )

    if request.method == "POST":
        existing = {ps.skill_id: ps for ps in person.skills.all()}
        with transaction.atomic():
            for sa in seedable:
                ps = existing.get(sa.skill_id)
                if ps:
                    # Update existing placeholder
                    ps.level = sa.level
                    ps.assessed_date = sa.assessed_date
                    ps.assessed_by_id = "self-assessment"
                    ps.evidence_notes = sa.evidence_notes
                    ps.is_self_assessed = True
                    ps.save()
                else:
                    # Create new
                    PersonSkill.objects.create(
                        person=person,
                        skill_id=sa.skill_id,
                        level=sa.level,
                        assessed_date=sa.assessed_date,
                        assessed_by_id="self-assessment",
                        evidence_notes=sa.evidence_notes,
                        is_self_assessed=True,
                    )
        return redirect("personnel:person-detail", person_id=person.id)

    return redirect("personnel:person-detail", person_id=person.id)
