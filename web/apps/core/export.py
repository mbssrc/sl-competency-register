"""Excel export: generate openpyxl Workbooks from Django ORM data."""

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from apps.core.models import TaxonomyMeta
from apps.personnel.models import DevelopmentPlan, Person, PersonSkill
from apps.personnel.services import (
    compute_all_domain_maturities,
    compute_domain_coverage,
    compute_service_readiness,
)
from apps.taxonomy.models import Domain, Skill

# ---------- Shared styles ----------

HEADER_FONT = Font(bold=True, color="FFFFFF", size=11)
HEADER_FILL = PatternFill(start_color="2F5496", end_color="2F5496", fill_type="solid")
HEADER_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True)
WRAP_ALIGN = Alignment(vertical="top", wrap_text=True)
THIN_BORDER = Border(
    left=Side(style="thin"),
    right=Side(style="thin"),
    top=Side(style="thin"),
    bottom=Side(style="thin"),
)
GAP_RED = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
GAP_YELLOW = PatternFill(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid")
FILL_YELLOW = PatternFill(start_color="FFFFCC", end_color="FFFFCC", fill_type="solid")


def _style_header(ws, row=1, max_col=None):
    if max_col is None:
        max_col = ws.max_column
    for col in range(1, max_col + 1):
        cell = ws.cell(row=row, column=col)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = HEADER_ALIGN
        cell.border = THIN_BORDER


def _auto_width(ws, min_width=10, max_width=50):
    for col in ws.columns:
        length = min_width
        for cell in col:
            if cell.value:
                length = max(length, min(len(str(cell.value)), max_width))
        ws.column_dimensions[get_column_letter(col[0].column)].width = length + 2


# ---------- Taxonomy ----------


def generate_taxonomy_workbook():
    """One sheet per domain with all skills listed."""
    wb = Workbook()
    wb.remove(wb.active)

    meta = TaxonomyMeta.load()
    domain_order = {d["directory"]: d["name"] for d in (meta.domains or [])}

    # Fall back to DB domains if meta has no entries
    domains = Domain.objects.using("taxonomy").all()
    for domain in domains:
        sheet_name = domain_order.get(domain.id, domain.name)[:31]
        skills = Skill.objects.using("taxonomy").filter(domain=domain).order_by("id")
        if not skills.exists():
            continue

        ws = wb.create_sheet(title=sheet_name)
        headers = [
            "ID",
            "Name",
            "Category",
            "Status",
            "Description",
            "Requires",
            "Recommended",
            "Tags",
        ]
        for col, h in enumerate(headers, 1):
            ws.cell(row=1, column=col, value=h)
        _style_header(ws, max_col=len(headers))

        for row_idx, skill in enumerate(skills, 2):
            ws.cell(row=row_idx, column=1, value=skill.id)
            ws.cell(row=row_idx, column=2, value=skill.name)
            ws.cell(row=row_idx, column=3, value=skill.category)
            ws.cell(row=row_idx, column=4, value=skill.status)
            ws.cell(row=row_idx, column=5, value=skill.description).alignment = WRAP_ALIGN
            ws.cell(
                row=row_idx,
                column=6,
                value=", ".join(skill.requires.using("taxonomy").values_list("id", flat=True)),
            )
            ws.cell(
                row=row_idx,
                column=7,
                value=", ".join(skill.recommended.using("taxonomy").values_list("id", flat=True)),
            )
            ws.cell(row=row_idx, column=8, value=", ".join(skill.tags or []))

        _auto_width(ws)
        ws.auto_filter.ref = ws.dimensions

    return wb


# ---------- Personnel ----------


def generate_personnel_workbook():
    """Skill details, development plans, and profile assignments."""
    wb = Workbook()

    # --- Sheet 1: Skill Details ---
    ws_detail = wb.active
    ws_detail.title = "Skill Details"
    detail_headers = [
        "Person ID",
        "Name",
        "Domain",
        "Skill",
        "Level",
        "Self Level",
        "Delta",
        "Assessed Date",
        "Assessed By",
        "Last Practiced",
        "Evidence Notes",
        "Authorized",
    ]
    for col, h in enumerate(detail_headers, 1):
        ws_detail.cell(row=1, column=col, value=h)
    _style_header(ws_detail, max_col=len(detail_headers))

    # Build skill→domain lookup
    all_skill_ids = set(PersonSkill.objects.values_list("skill_id", flat=True))
    skill_domains = {}
    if all_skill_ids:
        for s in (
            Skill.objects.using("taxonomy").filter(id__in=all_skill_ids).select_related("domain")
        ):
            skill_domains[s.id] = s.domain.name

    persons = Person.objects.prefetch_related("skills", "self_assessments").order_by("id")
    row_idx = 2
    for person in persons:
        self_map = {sa.skill_id: sa.level for sa in person.self_assessments.all()}
        for ps in person.skills.order_by("skill_id"):
            ws_detail.cell(row=row_idx, column=1, value=person.id)
            ws_detail.cell(row=row_idx, column=2, value=person.name)
            ws_detail.cell(row=row_idx, column=3, value=skill_domains.get(ps.skill_id, ""))
            ws_detail.cell(row=row_idx, column=4, value=ps.skill_id)
            ws_detail.cell(row=row_idx, column=5, value=ps.level)
            self_lvl = self_map.get(ps.skill_id)
            ws_detail.cell(row=row_idx, column=6, value=self_lvl if self_lvl is not None else "")
            ws_detail.cell(
                row=row_idx, column=7, value=self_lvl - ps.level if self_lvl is not None else ""
            )
            ws_detail.cell(
                row=row_idx, column=8, value=str(ps.assessed_date) if ps.assessed_date else ""
            )
            ws_detail.cell(row=row_idx, column=9, value=ps.assessed_by_id)
            ws_detail.cell(
                row=row_idx, column=10, value=str(ps.last_practiced) if ps.last_practiced else ""
            )
            ws_detail.cell(row=row_idx, column=11, value=ps.evidence_notes)
            auth = ps.authorization
            ws_detail.cell(
                row=row_idx,
                column=12,
                value=auth.get("authorized", False) if isinstance(auth, dict) else False,
            )
            row_idx += 1

    _auto_width(ws_detail)
    ws_detail.auto_filter.ref = ws_detail.dimensions

    # --- Sheet 2: Development Plans ---
    ws_dev = wb.create_sheet("Development Plans")
    dev_headers = [
        "Person ID",
        "Name",
        "Skill",
        "Current Level",
        "Target Level",
        "Target Date",
        "Actions",
    ]
    for col, h in enumerate(dev_headers, 1):
        ws_dev.cell(row=1, column=col, value=h)
    _style_header(ws_dev, max_col=len(dev_headers))

    plans = DevelopmentPlan.objects.select_related("person").order_by("person__id", "skill_id")
    row_idx = 2
    for plan in plans:
        ws_dev.cell(row=row_idx, column=1, value=plan.person.id)
        ws_dev.cell(row=row_idx, column=2, value=plan.person.name)
        ws_dev.cell(row=row_idx, column=3, value=plan.skill_id)
        ws_dev.cell(row=row_idx, column=4, value=plan.current_level)
        ws_dev.cell(row=row_idx, column=5, value=plan.target_level)
        ws_dev.cell(row=row_idx, column=6, value=str(plan.target_date) if plan.target_date else "")
        ws_dev.cell(row=row_idx, column=7, value="; ".join(plan.actions or []))
        row_idx += 1

    _auto_width(ws_dev)

    # --- Sheet 3: Domains ---
    ws_prof = wb.create_sheet("Domains")
    prof_headers = ["Person ID", "Name", "Assigned Domains"]
    for col, h in enumerate(prof_headers, 1):
        ws_prof.cell(row=1, column=col, value=h)
    _style_header(ws_prof, max_col=len(prof_headers))

    for row_idx, person in enumerate(Person.objects.order_by("id"), 2):
        ws_prof.cell(row=row_idx, column=1, value=person.id)
        ws_prof.cell(row=row_idx, column=2, value=person.name)
        ws_prof.cell(row=row_idx, column=3, value=", ".join(person.domains or []))

    _auto_width(ws_prof)

    return wb


# ---------- Reports ----------


def generate_reports_workbook():
    """Gap analysis and service readiness."""
    wb = Workbook()

    # --- Sheet 1: Domain Maturity Gaps ---
    ws_gap = wb.active
    ws_gap.title = "Domain Maturity Gaps"
    gap_headers = [
        "Person",
        "Domain",
        "Current Level",
        "Current Title",
        "Next Level",
        "What's Needed",
    ]
    for col, h in enumerate(gap_headers, 1):
        ws_gap.cell(row=1, column=col, value=h)
    _style_header(ws_gap, max_col=len(gap_headers))

    row_idx = 2
    for person in Person.objects.prefetch_related("skills").order_by("id"):
        maturities = compute_all_domain_maturities(person)
        for m in maturities:
            if m["next_gaps"] and m["next_gaps"].get("gaps"):
                ws_gap.cell(row=row_idx, column=1, value=person.name)
                ws_gap.cell(row=row_idx, column=2, value=m["domain_name"])
                ws_gap.cell(row=row_idx, column=3, value=m["level"] or "none")
                ws_gap.cell(row=row_idx, column=4, value=m["title"] or "Below Junior")
                ws_gap.cell(row=row_idx, column=5, value=m["next_gaps"]["title"])
                ws_gap.cell(row=row_idx, column=6, value="; ".join(m["next_gaps"]["gaps"]))

                for c in range(1, len(gap_headers) + 1):
                    ws_gap.cell(row=row_idx, column=c).fill = GAP_YELLOW
                row_idx += 1

    _auto_width(ws_gap)
    ws_gap.auto_filter.ref = ws_gap.dimensions

    # --- Sheet 2: Service Readiness ---
    ws_svc = wb.create_sheet("Service Readiness")
    svc_headers = [
        "Service",
        "Skill",
        "Min Level",
        "Qualified Count",
        "Qualified Personnel",
    ]
    for col, h in enumerate(svc_headers, 1):
        ws_svc.cell(row=1, column=col, value=h)
    _style_header(ws_svc, max_col=len(svc_headers))

    row_idx = 2
    for svc in compute_service_readiness():
        for comp in svc["competencies"]:
            ws_svc.cell(row=row_idx, column=1, value=svc["service_name"])
            ws_svc.cell(row=row_idx, column=2, value=comp["skill_name"])
            ws_svc.cell(row=row_idx, column=3, value=comp["minimum_level"])
            ws_svc.cell(row=row_idx, column=4, value=comp["qualified_count"])
            ws_svc.cell(
                row=row_idx,
                column=5,
                value=", ".join(comp["qualified_people"]),
            )
            if comp["qualified_count"] == 0:
                for c in range(1, len(svc_headers) + 1):
                    ws_svc.cell(row=row_idx, column=c).fill = GAP_RED
            row_idx += 1

    _auto_width(ws_svc)
    ws_svc.auto_filter.ref = ws_svc.dimensions

    return wb


# ---------- Self-Assessment Questionnaire ----------


def generate_self_assessment_workbook(person):
    """Questionnaire with domain row-grouping for a person to self-assess."""
    from collections import OrderedDict

    wb = Workbook()

    # Include all active skills regardless of assigned domains
    skill_ids = set(
        Skill.objects.using("taxonomy").filter(status="active").values_list("id", flat=True)
    )

    skills = (
        Skill.objects.using("taxonomy")
        .filter(id__in=skill_ids)
        .select_related("domain")
        .order_by("domain__name", "category", "name")
    )
    existing_self = {sa.skill_id: sa for sa in person.self_assessments.all()}

    # Group skills by domain, ordered by taxonomy meta
    domain_order = TaxonomyMeta.domain_sort_key()
    skills_grouped = {}
    for skill in skills:
        key = (domain_order.get(skill.domain_id, 999), skill.domain.name)
        skills_grouped.setdefault(key, []).append(skill)
    skills_by_domain = OrderedDict((name, sks) for (_, name), sks in sorted(skills_grouped.items()))

    # --- Sheet 1: Self-Assessment form ---
    ws = wb.active
    ws.title = "Self-Assessment"
    headers = [
        "Skill ID",
        "Skill Name",
        "Domain",
        "Category",
        "Level",
        "Level Description",
        "Notes",
    ]
    for col, h in enumerate(headers, 1):
        ws.cell(row=1, column=col, value=h)
    _style_header(ws, max_col=len(headers))

    # Summary level for outline: collapse groups below the domain header
    ws.sheet_properties.outlinePr.summaryBelow = False

    row_idx = 2
    ref_rows = []

    for domain_name, domain_skills in skills_by_domain.items():
        # Domain header row
        header_cell = ws.cell(row=row_idx, column=1, value=domain_name)
        header_cell.font = Font(bold=True, size=11)
        ws.merge_cells(start_row=row_idx, start_column=1, end_row=row_idx, end_column=len(headers))
        row_idx += 1

        group_start = row_idx
        for skill in domain_skills:
            ws.cell(row=row_idx, column=1, value=skill.id)
            ws.cell(row=row_idx, column=2, value=skill.name)
            ws.cell(row=row_idx, column=3, value=domain_name)
            ws.cell(row=row_idx, column=4, value=skill.category)

            # Dropdown with proficiency labels
            prof = skill.proficiency or {}
            labels = []
            for n in range(6):
                entry = prof.get(str(n), {})
                label = entry.get("label", f"Level {n}")
                labels.append(f"{n} — {label}")

            dv = DataValidation(type="list", formula1=f'"{",".join(labels)}"', allow_blank=True)
            ws.add_data_validation(dv)

            sa = existing_self.get(skill.id)
            level_val = sa.level if sa and sa.level > 0 else 0
            level_cell = ws.cell(row=row_idx, column=5, value=labels[level_val])
            level_cell.fill = FILL_YELLOW
            dv.add(level_cell)

            desc_cell = ws.cell(
                row=row_idx,
                column=6,
                value=f'=IFERROR(VLOOKUP(A{row_idx}&"|"&LEFT(E{row_idx},1),\'Proficiency Reference\'!$A:$B,2,FALSE),"")',
            )
            desc_cell.alignment = WRAP_ALIGN

            notes_cell = ws.cell(row=row_idx, column=7, value=sa.evidence_notes if sa else None)
            notes_cell.fill = FILL_YELLOW

            # Collect reference data
            for level_num in range(6):
                entry = prof.get(str(level_num), {})
                ref_rows.append(
                    (
                        f"{skill.id}|{level_num}",
                        entry.get("description", ""),
                        skill.id,
                        skill.name,
                        level_num,
                        entry.get("label", ""),
                    )
                )

            row_idx += 1

        # Group the skill rows under this domain (collapsible, collapsed by default)
        if group_start < row_idx:
            ws.row_dimensions.group(group_start, row_idx - 1, outline_level=1, hidden=True)

    _auto_width(ws)

    # --- Sheet 2: Proficiency Reference (lookup table) ---
    ws_ref = wb.create_sheet("Proficiency Reference")
    ref_headers = ["Key", "Description", "Skill ID", "Skill Name", "Level", "Label"]
    for col, h in enumerate(ref_headers, 1):
        ws_ref.cell(row=1, column=col, value=h)
    _style_header(ws_ref, max_col=len(ref_headers))

    for ridx, row_data in enumerate(ref_rows, 2):
        for col, val in enumerate(row_data, 1):
            cell = ws_ref.cell(row=ridx, column=col, value=val)
            if col == 2:
                cell.alignment = WRAP_ALIGN

    _auto_width(ws_ref)
    return wb


# ---------- Gap Analysis ----------


FILL_GREEN = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")


def generate_gap_analysis_workbook():
    """Domain coverage summary, skill-level detail, and person x skill matrix."""
    wb = Workbook()

    coverage = compute_domain_coverage()

    # --- Sheet 1: Domain Coverage Summary ---
    ws_summary = wb.active
    ws_summary.title = "Domain Coverage"
    headers = [
        "Domain",
        "Total Skills",
        "Covered L1+",
        "Covered L2+",
        "Covered L3+",
        "% L1+",
        "% L3+",
        "Uncovered",
    ]
    for col, h in enumerate(headers, 1):
        ws_summary.cell(row=1, column=col, value=h)
    _style_header(ws_summary, max_col=len(headers))

    row_idx = 2
    for dc in coverage:
        ws_summary.cell(row=row_idx, column=1, value=dc["domain_name"])
        ws_summary.cell(row=row_idx, column=2, value=dc["total_skills"])
        ws_summary.cell(row=row_idx, column=3, value=dc["covered_l1"])
        ws_summary.cell(row=row_idx, column=4, value=dc["covered_l2"])
        ws_summary.cell(row=row_idx, column=5, value=dc["covered_l3"])
        ws_summary.cell(row=row_idx, column=6, value=dc["pct_l1"] / 100).number_format = "0%"
        ws_summary.cell(row=row_idx, column=7, value=dc["pct_l3"] / 100).number_format = "0%"
        uncovered = dc["total_skills"] - dc["covered_l1"]
        cell = ws_summary.cell(row=row_idx, column=8, value=uncovered)
        if uncovered > 0:
            cell.fill = GAP_RED
        row_idx += 1

    _auto_width(ws_summary)
    ws_summary.auto_filter.ref = ws_summary.dimensions

    # --- Sheet 2: Skill Coverage Detail ---
    ws_detail = wb.create_sheet("Skill Coverage")
    headers = [
        "Domain",
        "Category",
        "Skill ID",
        "Skill Name",
        "Best Level",
        "Best Person",
        "Total Personnel",
        "Personnel Detail",
    ]
    for col, h in enumerate(headers, 1):
        ws_detail.cell(row=1, column=col, value=h)
    _style_header(ws_detail, max_col=len(headers))

    row_idx = 2
    for dc in coverage:
        for s in dc["skills"]:
            ws_detail.cell(row=row_idx, column=1, value=dc["domain_name"])
            ws_detail.cell(row=row_idx, column=2, value=s["category"])
            ws_detail.cell(row=row_idx, column=3, value=s["skill_id"])
            ws_detail.cell(row=row_idx, column=4, value=s["skill_name"])
            ws_detail.cell(row=row_idx, column=5, value=s["best_level"])
            ws_detail.cell(row=row_idx, column=6, value=s["best_person"] or "")
            ws_detail.cell(row=row_idx, column=7, value=len(s["personnel"]))
            ws_detail.cell(
                row=row_idx,
                column=8,
                value=", ".join(f"{p['name']} (L{p['level']})" for p in s["personnel"]),
            )
            if s["best_level"] == 0:
                for c in range(1, len(headers) + 1):
                    ws_detail.cell(row=row_idx, column=c).fill = GAP_RED
            elif s["best_level"] >= 3:
                for c in range(1, len(headers) + 1):
                    ws_detail.cell(row=row_idx, column=c).fill = FILL_GREEN
            row_idx += 1

    _auto_width(ws_detail)
    ws_detail.auto_filter.ref = ws_detail.dimensions

    # --- Sheet 3: Person x Skill Matrix ---
    ws_matrix = wb.create_sheet("Person x Skill Matrix")

    persons = list(Person.objects.order_by("id"))
    all_skills_flat = []
    for dc in coverage:
        for s in dc["skills"]:
            all_skills_flat.append(s)

    # Header row: empty + person names
    ws_matrix.cell(row=1, column=1, value="Skill ID")
    ws_matrix.cell(row=1, column=2, value="Skill Name")
    ws_matrix.cell(row=1, column=3, value="Domain")
    for col, person in enumerate(persons, 4):
        ws_matrix.cell(row=1, column=col, value=person.name)
    _style_header(ws_matrix, max_col=3 + len(persons))

    # Build person skill lookup: {(person_name, skill_id): level}
    person_skill_lookup = {}
    for ps in PersonSkill.objects.filter(level__gte=1).select_related("person"):
        person_skill_lookup[(ps.person.name, ps.skill_id)] = ps.level

    row_idx = 2
    for s in all_skills_flat:
        ws_matrix.cell(row=row_idx, column=1, value=s["skill_id"])
        ws_matrix.cell(row=row_idx, column=2, value=s["skill_name"])
        # Find domain name from coverage data
        domain_name = ""
        for dc in coverage:
            if any(sk["skill_id"] == s["skill_id"] for sk in dc["skills"]):
                domain_name = dc["domain_name"]
                break
        ws_matrix.cell(row=row_idx, column=3, value=domain_name)

        for col, person in enumerate(persons, 4):
            level = person_skill_lookup.get((person.name, s["skill_id"]), 0)
            cell = ws_matrix.cell(row=row_idx, column=col, value=level if level > 0 else "")
            if level >= 3:
                cell.fill = FILL_GREEN
            elif level == 0:
                pass  # leave blank
            else:
                cell.fill = GAP_YELLOW

        row_idx += 1

    _auto_width(ws_matrix, max_width=15)
    ws_matrix.auto_filter.ref = ws_matrix.dimensions
    ws_matrix.freeze_panes = "D2"

    return wb

    return wb
