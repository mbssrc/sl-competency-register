import io
import logging
import tarfile
import tempfile

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import connections
from django.http import HttpResponse, HttpResponseNotAllowed, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounts.decorators import admin_required, role_required
from apps.accounts.models import User
from apps.core.export import (
    generate_personnel_workbook,
    generate_reports_workbook,
    generate_taxonomy_workbook,
)
from apps.personnel.models import Person, PersonSkill, Project
from apps.personnel.services import compute_project_coverage
from apps.taxonomy.models import Domain, Service, Skill

logger = logging.getLogger("personnel.audit")


def health(request):
    failed = []
    for alias in ("default", "taxonomy"):
        try:
            connections[alias].ensure_connection()
        except Exception:
            logger.exception("health check failed for database %s", alias)
            failed.append(alias)
    if failed:
        return JsonResponse({"status": "error", "databases": failed}, status=503)
    return JsonResponse({"status": "ok"})


@role_required("user")
def dashboard(request):
    is_manager = request.user.is_manager

    # --- Shared: projects and taxonomy ---
    open_projects = Project.objects.filter(status="planning")
    open_count = open_projects.count()
    done_count = Project.objects.filter(status="done").count()

    context = {
        "is_manager": is_manager,
        "open_count": open_count,
        "done_count": done_count,
        "skill_active": Skill.objects.filter(status="active").count(),
        "domain_count": Domain.objects.count(),
        "service_count": Service.objects.count(),
        "my_person": None,
        "project_data": [],
        "projects_with_gaps": 0,
        "person_count": None,
        "assessment_count": None,
    }

    if is_manager:
        # Counts only. The roster used to live here and no longer does, so
        # nothing needs the skills or development-plan rows prefetched.
        context["person_count"] = Person.objects.count()
        context["assessment_count"] = PersonSkill.objects.count()

        project_data = []
        projects_with_gaps = 0
        for proj in open_projects.order_by("-updated_at")[:5]:
            comps = proj.required_competencies or []
            coverage = compute_project_coverage(proj) if comps else []
            covered = sum(1 for c in coverage if c["is_covered"])
            pct = round(100 * covered / len(comps)) if comps else 0
            if comps and pct < 100:
                projects_with_gaps += 1
            project_data.append(
                {
                    "project": proj,
                    "comp_count": len(comps),
                    "coverage_pct": pct,
                }
            )
        context["project_data"] = project_data
        context["projects_with_gaps"] = projects_with_gaps
    else:
        # A user sees only their own record, and only if their account is linked.
        person = request.user.person
        context["my_person"] = person
        if person:
            context["my_skill_count"] = person.skills.filter(level__gte=1).count()

    return render(request, "core/dashboard.html", context)


# ---------------------------------------------------------------------------
# Admin Tools
# ---------------------------------------------------------------------------


@admin_required
def admin_tools(request):
    return render(request, "core/admin_tools.html")


@admin_required
def admin_seed(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    out = io.StringIO()
    err = io.StringIO()
    try:
        call_command("seed_taxonomy", stdout=out, stderr=err, verbosity=1)
        result = out.getvalue()
        success = True
    except Exception as e:
        result = f"Error: {e}\n{err.getvalue()}"
        success = False
    return render(
        request,
        "core/admin_tools.html",
        {
            "seed_result": result,
            "seed_success": success,
        },
    )


@admin_required
def admin_export_json(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    out = io.StringIO()
    err = io.StringIO()
    target = settings.TAXONOMY_JSON_DIR
    try:
        call_command("export_taxonomy", str(target), stdout=out, stderr=err, verbosity=1)
        result = f"Wrote JSON files to {target}\n\n{out.getvalue()}"
        success = True
    except Exception as e:
        result = f"Error: {e}\n{err.getvalue()}"
        success = False
    return render(
        request,
        "core/admin_tools.html",
        {
            "export_result": result,
            "export_success": success,
        },
    )


@admin_required
def admin_export_download(request):
    """Export taxonomy DB to JSON files and serve as a .tar.gz download."""
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    buf = io.BytesIO()
    with tempfile.TemporaryDirectory() as tmpdir:
        out = io.StringIO()
        err = io.StringIO()
        try:
            call_command("export_taxonomy", tmpdir, stdout=out, stderr=err, verbosity=1)
        except Exception as e:
            return HttpResponse(f"Export failed: {e}\n{err.getvalue()}", status=500)

        # Package tmpdir contents into a .tar.gz
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            import os

            for root, dirs, files in os.walk(tmpdir):
                for fname in sorted(files):
                    filepath = os.path.join(root, fname)
                    # export_taxonomy already writes taxonomy/, profiles/ and
                    # services/, so the archive unpacks to the repo layout.
                    arcname = os.path.relpath(filepath, tmpdir)
                    tar.add(filepath, arcname=arcname)

    buf.seek(0)
    response = HttpResponse(buf.read(), content_type="application/gzip")
    response["Content-Disposition"] = 'attachment; filename="taxonomy-export.tar.gz"'
    return response


@admin_required
def admin_check_integrity(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    out = io.StringIO()
    err = io.StringIO()
    try:
        call_command("check_integrity", stdout=out, stderr=err, verbosity=1)
        result = out.getvalue()
        errors_output = err.getvalue()
        if errors_output:
            result = errors_output + "\n" + result
        success = True
    except SystemExit:
        # check_integrity calls sys.exit(1) on failure
        result = err.getvalue()
        success = False
    except Exception as e:
        result = f"Error: {e}\n{err.getvalue()}"
        success = False
    return render(
        request,
        "core/admin_tools.html",
        {
            "integrity_result": result,
            "integrity_success": success,
        },
    )


# ---------------------------------------------------------------------------
# User Management
# ---------------------------------------------------------------------------


@admin_required
def user_list(request):
    users = User.objects.select_related("person").order_by("username")
    return render(request, "core/user_list.html", {"users": users})


def _is_htmx(request):
    return request.headers.get("HX-Request") == "true"


def _user_form_template(request):
    return "core/partials/user_form.html" if _is_htmx(request) else "core/user_form.html"


@admin_required
def user_create(request):
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        email = request.POST.get("email", "").strip()
        password = request.POST.get("password", "")
        role = request.POST.get("role", "user")
        person_id = request.POST.get("person", "")

        errors = []
        if not username:
            errors.append("Username is required.")
        if not password:
            errors.append("Password is required.")
        else:
            probe = User(username=username, email=email)
            try:
                validate_password(password, user=probe)
            except ValidationError as e:
                errors.extend(e.messages)
        if User.objects.filter(username=username).exists():
            errors.append("Username already exists.")
        if role not in dict(User.ROLE_CHOICES):
            errors.append("Invalid role.")

        if errors:
            unlinked_persons = Person.objects.filter(user_account__isnull=True).order_by("name")
            return render(
                request,
                _user_form_template(request),
                {
                    "errors": errors,
                    "form_data": request.POST,
                    "persons": unlinked_persons,
                    "roles": User.ROLE_CHOICES,
                    "editing": False,
                },
            )

        user = User.objects.create_user(
            username=username, email=email, password=password, role=role
        )
        if person_id:
            try:
                person = Person.objects.get(id=person_id)
                user.person = person
                user.save()
            except Person.DoesNotExist:
                pass

        if _is_htmx(request):
            resp = HttpResponse()
            resp["HX-Redirect"] = "/users/"
            return resp
        return redirect("user-list")

    unlinked_persons = Person.objects.filter(user_account__isnull=True).order_by("name")
    return render(
        request,
        _user_form_template(request),
        {
            "persons": unlinked_persons,
            "roles": User.ROLE_CHOICES,
            "editing": False,
        },
    )


@admin_required
def user_edit(request, user_id):
    edit_user = get_object_or_404(User, pk=user_id)

    if request.method == "POST":
        email = request.POST.get("email", "").strip()
        role = request.POST.get("role", edit_user.role)
        person_id = request.POST.get("person", "")
        password = request.POST.get("password", "")

        errors = []
        if role not in dict(User.ROLE_CHOICES):
            errors.append("Invalid role.")
        if edit_user.is_admin and role != "admin" and User.objects.active_admin_count() <= 1:
            errors.append("Cannot remove the last admin. Promote another account first.")
        if password:
            try:
                validate_password(password, user=edit_user)
            except ValidationError as e:
                errors.extend(e.messages)

        if errors:
            unlinked_persons = Person.objects.filter(user_account__isnull=True).order_by("name")
            if edit_user.person:
                unlinked_persons = (
                    unlinked_persons | Person.objects.filter(id=edit_user.person_id)
                ).order_by("name")
            return render(
                request,
                _user_form_template(request),
                {
                    "errors": errors,
                    "form_data": request.POST,
                    "edit_user": edit_user,
                    "persons": unlinked_persons,
                    "roles": User.ROLE_CHOICES,
                    "editing": True,
                },
            )

        edit_user.email = email
        edit_user.role = role

        if password:
            edit_user.set_password(password)

        # Handle person linking
        if person_id:
            try:
                person = Person.objects.get(id=person_id)
                edit_user.person = person
            except Person.DoesNotExist:
                edit_user.person = None
        else:
            edit_user.person = None

        edit_user.save()
        if _is_htmx(request):
            resp = HttpResponse()
            resp["HX-Redirect"] = "/users/"
            return resp
        return redirect("user-list")

    # Unlinked persons + this user's current person
    unlinked_persons = Person.objects.filter(user_account__isnull=True).order_by("name")
    if edit_user.person:
        unlinked_persons = (
            unlinked_persons | Person.objects.filter(id=edit_user.person_id)
        ).order_by("name")

    return render(
        request,
        _user_form_template(request),
        {
            "edit_user": edit_user,
            "persons": unlinked_persons,
            "roles": User.ROLE_CHOICES,
            "editing": True,
        },
    )


@admin_required
def user_toggle_active(request, user_id):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    user = get_object_or_404(User, pk=user_id)

    deactivating = user.is_active
    if deactivating:
        if user.pk == request.user.pk:
            messages.error(request, "You cannot deactivate your own account.")
            return redirect("user-list")
        if user.is_admin and User.objects.active_admin_count() <= 1:
            messages.error(request, "Cannot deactivate the last active admin account.")
            return redirect("user-list")

    user.is_active = not user.is_active
    user.save()
    return redirect("user-list")


# ---------------------------------------------------------------------------
# Excel Export
# ---------------------------------------------------------------------------

XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@role_required("manager")
def export_page(request):
    return render(request, "core/export.html")


@role_required("manager")
def export_taxonomy_xlsx(request):
    wb = generate_taxonomy_workbook()
    response = HttpResponse(content_type=XLSX_CONTENT_TYPE)
    response["Content-Disposition"] = 'attachment; filename="taxonomy-export.xlsx"'
    wb.save(response)
    return response


@role_required("manager")
def export_personnel_xlsx(request):
    wb = generate_personnel_workbook()
    response = HttpResponse(content_type=XLSX_CONTENT_TYPE)
    response["Content-Disposition"] = 'attachment; filename="personnel-export.xlsx"'
    wb.save(response)
    return response


@role_required("manager")
def export_reports_xlsx(request):
    wb = generate_reports_workbook()
    response = HttpResponse(content_type=XLSX_CONTENT_TYPE)
    response["Content-Disposition"] = 'attachment; filename="reports-export.xlsx"'
    wb.save(response)
    return response
