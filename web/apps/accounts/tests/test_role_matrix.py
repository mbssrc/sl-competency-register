"""The role -> view permission matrix.

A representative URL for each threshold appears here and is exercised against
all three roles. Separately, test_every_routed_view_declares_a_role proves by
introspection that no routed view is missing a decorator at all — so a view
added later is caught even if nobody adds it to this table.
"""

import datetime

import pytest
from django.test import Client

from apps.accounts.models import User
from apps.personnel.models import Person, PersonSkill, Project

# (url, method, lowest role that may reach it)
MATRIX = [
    # Taxonomy — read by anyone, edited by managers
    ("/taxonomy/", "get", "user"),
    ("/taxonomy/profiles/", "get", "user"),
    ("/taxonomy/services/", "get", "user"),
    ("/taxonomy/FOUND/edit/", "get", "manager"),
    ("/taxonomy/skill/FOUND-REPORT/edit/", "get", "manager"),
    ("/taxonomy/profiles/FOUND/edit/", "get", "manager"),
    ("/taxonomy/services/SVC-DFIR/edit/", "get", "manager"),
    ("/taxonomy/reorder/", "post", "manager"),
    ("/taxonomy/profiles/reorder/", "post", "manager"),
    ("/taxonomy/services/reorder/", "post", "manager"),
    # Projects — shared planning artefacts, managed by managers
    ("/personnel/projects/", "get", "user"),
    ("/personnel/projects/p1/", "get", "user"),
    ("/personnel/projects/create/", "get", "manager"),
    ("/personnel/projects/p1/edit/", "get", "manager"),
    ("/personnel/projects/p1/skills/", "post", "manager"),
    ("/personnel/projects/p1/assess/", "get", "manager"),
    # Personnel — org-wide views and all editing are manager-level
    ("/personnel/", "get", "manager"),
    ("/personnel/gaps/", "get", "manager"),
    ("/personnel/gaps/export/", "get", "manager"),
    ("/personnel/readiness/", "get", "manager"),
    ("/personnel/add/", "get", "manager"),
    ("/personnel/JD01/edit/", "get", "manager"),
    ("/personnel/JD01/skill/add/", "get", "manager"),
    ("/personnel/JD01/skill/FOUND-REPORT/edit/", "get", "manager"),
    ("/personnel/JD01/skill/FOUND-REPORT/delete/", "post", "manager"),
    ("/personnel/JD01/seed-self-assessment/", "post", "manager"),
    # Excel exports — contain every person's data
    ("/export/", "get", "manager"),
    ("/export/taxonomy.xlsx", "get", "manager"),
    ("/export/personnel.xlsx", "get", "manager"),
    ("/export/reports.xlsx", "get", "manager"),
    # Admin only
    ("/personnel/JD01/delete/", "post", "admin"),
    ("/users/", "get", "admin"),
    ("/users/create/", "get", "admin"),
    ("/admin-tools/", "get", "admin"),
    # Dashboard — everyone, with role-dependent content (Task 20)
    ("/", "get", "user"),
]

RANKS = {"user": 0, "manager": 1, "admin": 2}


@pytest.fixture
def seeded(db):
    # Just the rows the MATRIX URLs address; seeding the full taxonomy here
    # cost ~70 s across the parametrised cases for no extra coverage.
    from apps.taxonomy.models import Domain, Profile, Service, Skill

    domain = Domain.objects.using("taxonomy").create(
        id="FOUND", name="Foundations", description="", categories=[]
    )
    Skill.objects.using("taxonomy").create(
        id="FOUND-REPORT",
        name="Report Writing",
        domain=domain,
        category="foundations",
        status="active",
        description="",
        proficiency={},
    )
    Profile.objects.using("taxonomy").create(id="FOUND", name="Foundations", domain=domain)
    Service.objects.using("taxonomy").create(id="SVC-DFIR", name="DFIR")
    person = Person.objects.create(
        id="JD01", name="Jane Doe", domains=[], start_date=datetime.date(2024, 1, 15)
    )
    # So the person-skill URLs reach their view rather than 404 before it.
    PersonSkill.objects.create(
        person=person,
        skill_id="FOUND-REPORT",
        level=2,
        assessed_date=datetime.date(2024, 6, 1),
        assessed_by_id="LEAD01",
    )
    Project.objects.create(id="p1", name="P", status="planning")


@pytest.fixture
def clients(db):
    out = {}
    for role in RANKS:
        user = User.objects.create_user(
            username=f"matrix-{role}", password="strong-pass-here", role=role
        )
        client = Client()
        client.force_login(user)
        out[role] = client
    return out


@pytest.mark.django_db(databases=["default", "taxonomy"])
@pytest.mark.parametrize("url,method,minimum", MATRIX)
class TestRoleMatrix:
    def test_roles_below_the_threshold_are_refused(self, seeded, clients, url, method, minimum):
        for role, rank in RANKS.items():
            if rank >= RANKS[minimum]:
                continue
            response = getattr(clients[role], method)(url)
            assert response.status_code == 403, (
                f"{role} reached {method.upper()} {url}, which needs {minimum}"
            )

    def test_roles_at_or_above_the_threshold_are_admitted(
        self, seeded, clients, url, method, minimum
    ):
        for role, rank in RANKS.items():
            if rank < RANKS[minimum]:
                continue
            response = getattr(clients[role], method)(url)
            assert response.status_code != 403, (
                f"{role} was refused {method.upper()} {url}, which needs {minimum}"
            )

    def test_anonymous_is_redirected_to_login(self, seeded, url, method, minimum):
        response = getattr(Client(), method)(url)
        assert response.status_code == 302
        assert "/accounts/login/" in response.url


def test_every_routed_view_declares_a_role():
    """No routed view may be left ungated.

    Checked by introspection rather than by issuing requests: role_required and
    owner_or_role tag their wrapper with _required_role, so a view added later
    without a decorator fails here immediately, whether or not anyone remembered
    to add it to MATRIX.
    """
    from django.urls import get_resolver

    # Django's own admin, the health probe and the auth views are gated
    # elsewhere (admin site permissions, deliberately public, and the login
    # flow itself).
    EXEMPT_MODULES = ("django.contrib.admin", "django.contrib.auth")
    EXEMPT_VIEWS = {"health", "LoginView", "LogoutView"}

    ungated = []

    def walk(patterns, prefix=""):
        for entry in patterns:
            if hasattr(entry, "url_patterns"):
                walk(entry.url_patterns, prefix + str(entry.pattern))
                continue
            view = entry.callback
            module = getattr(view, "__module__", "") or ""
            # Class-based views expose the class on the as_view() function.
            view_class = getattr(view, "view_class", None)
            name = view_class.__name__ if view_class else getattr(view, "__name__", repr(view))
            if module.startswith(EXEMPT_MODULES) or name in EXEMPT_VIEWS:
                continue
            if not module.startswith("apps."):
                continue
            if not hasattr(view, "_required_role"):
                ungated.append(f"{prefix}{entry.pattern} -> {module}.{name}")

    walk(get_resolver().url_patterns)
    assert not ungated, "These views have no role threshold:\n  " + "\n  ".join(sorted(ungated))
