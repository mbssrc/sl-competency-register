"""A `user` must not be able to reach a colleague's name or level.

The sidebar not linking a page is not a control; these tests drive the URLs
directly, the way a curious employee would.
"""

import datetime

import pytest
from django.test import Client
from django.urls import reverse

from apps.accounts.models import User
from apps.personnel.models import Person, PersonSkill, Project


@pytest.fixture
def two_people(db):
    jane = Person.objects.create(
        id="JD01",
        name="Jane Doe",
        domains=["FOUND"],
        start_date=datetime.date(2024, 1, 15),
    )
    alex = Person.objects.create(
        id="AB02",
        name="Alex Brown",
        domains=["FOUND"],
        start_date=datetime.date(2024, 3, 1),
    )
    return jane, alex


@pytest.fixture
def seeded_taxonomy(db):
    from apps.taxonomy.models import Domain, Skill

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


@pytest.fixture
def jane_client(two_people):
    jane, _ = two_people
    user = User.objects.create_user(username="jane", password="strong-pass-here", role="user")
    user.person = jane
    user.save()
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def staffed_project(two_people, seeded_taxonomy):
    jane, alex = two_people
    skill_id = "FOUND-REPORT"
    PersonSkill.objects.create(
        person=jane,
        skill_id=skill_id,
        level=2,
        assessed_date=datetime.date(2024, 6, 1),
        assessed_by_id="lead",
    )
    PersonSkill.objects.create(
        person=alex,
        skill_id=skill_id,
        level=4,
        assessed_date=datetime.date(2024, 6, 1),
        assessed_by_id="lead",
    )
    return Project.objects.create(
        id="p1",
        name="Audit",
        status="planning",
        required_competencies=[{"skill": skill_id, "minimum_level": 3}],
    )


@pytest.mark.django_db(databases=["default", "taxonomy"])
class TestOwnRecordOnly:
    def test_user_sees_their_own_detail(self, jane_client, seeded_taxonomy):
        response = jane_client.get(reverse("personnel:person-detail", args=["JD01"]))
        assert response.status_code == 200
        assert b"Jane Doe" in response.content

    def test_user_cannot_open_a_colleague(self, jane_client, seeded_taxonomy):
        response = jane_client.get(reverse("personnel:person-detail", args=["AB02"]))
        assert response.status_code == 403

    @pytest.mark.parametrize(
        "name",
        [
            "person-list",
            "gap-analysis",
            "service-readiness",
        ],
    )
    def test_user_cannot_open_org_wide_reports(self, jane_client, seeded_taxonomy, name):
        assert jane_client.get(reverse(f"personnel:{name}")).status_code == 403


@pytest.mark.django_db(databases=["default", "taxonomy"])
class TestProjectDetailScope:
    def test_user_sees_coverage_without_names(self, jane_client, staffed_project):
        response = jane_client.get(reverse("personnel:project-detail", args=["p1"]))
        assert response.status_code == 200
        assert b"Alex Brown" not in response.content
        assert b"Audit" in response.content

    def test_user_sees_their_own_fitness(self, jane_client, staffed_project):
        response = jane_client.get(reverse("personnel:project-detail", args=["p1"]))
        fitness = response.context["my_fitness"]
        assert fitness["total"] == 1
        assert fitness["met"] == 0  # Jane is L2, needs L3
        assert fitness["skills"][0]["current_level"] == 2

    def test_user_still_sees_whether_a_requirement_is_covered(self, jane_client, staffed_project):
        response = jane_client.get(reverse("personnel:project-detail", args=["p1"]))
        coverage = response.context["coverage"]
        assert coverage[0]["is_covered"] is True  # Alex covers it
        assert "qualified" not in coverage[0]
        assert "qualified_count" not in coverage[0]

    def test_manager_sees_the_names(self, staffed_project):
        manager = User.objects.create_user(
            username="lead", password="strong-pass-here", role="manager"
        )
        client = Client()
        client.force_login(manager)
        response = client.get(reverse("personnel:project-detail", args=["p1"]))
        assert response.status_code == 200
        assert b"Alex Brown" in response.content

    def test_unlinked_user_gets_no_fitness_block(self, staffed_project, seeded_taxonomy):
        client = Client()
        client.force_login(
            User.objects.create_user(username="nobody", password="strong-pass-here", role="user")
        )
        response = client.get(reverse("personnel:project-detail", args=["p1"]))
        assert response.status_code == 200
        assert response.context["my_fitness"] is None


@pytest.mark.django_db(databases=["default", "taxonomy"])
class TestDashboardScope:
    def test_dashboard_names_no_colleague_to_a_user(self, jane_client, two_people, seeded_taxonomy):
        response = jane_client.get("/")
        assert response.status_code == 200
        assert b"Alex Brown" not in response.content

    def test_user_dashboard_shows_their_own_summary(self, jane_client, two_people, seeded_taxonomy):
        response = jane_client.get("/")
        assert response.context["my_person"].id == "JD01"
        assert b"Jane Doe" in response.content

    def test_dashboard_names_nobody_even_to_a_manager(self, two_people, seeded_taxonomy):
        # The dashboard reports scale, not people. A manager may read any
        # record, but the landing page is not where colleague names belong:
        # it is the one page everyone sees over a shoulder.
        manager = User.objects.create_user(
            username="lead", password="strong-pass-here", role="manager"
        )
        client = Client()
        client.force_login(manager)
        response = client.get("/")
        assert response.status_code == 200
        assert b"Alex Brown" not in response.content
        assert b"Jane Doe" not in response.content

    def test_dashboard_still_reports_the_headcount_to_a_manager(self, two_people, seeded_taxonomy):
        manager = User.objects.create_user(
            username="lead2", password="strong-pass-here", role="manager"
        )
        client = Client()
        client.force_login(manager)
        response = client.get("/")
        assert response.context["person_count"] == 2

    def test_unlinked_user_dashboard_explains_itself(self, seeded_taxonomy, two_people):
        client = Client()
        client.force_login(
            User.objects.create_user(username="nobody", password="strong-pass-here", role="user")
        )
        response = client.get("/")
        assert response.status_code == 200
        assert response.context["my_person"] is None
        assert b"not linked" in response.content.lower()


@pytest.mark.django_db(databases=["default", "taxonomy"])
class TestNavigationMatchesRole:
    """A link that can only ever yield 403 is a defect of its own."""

    MANAGER_ONLY = [
        b'href="/personnel/"',
        b'href="/personnel/gaps/"',
        b'href="/personnel/readiness/"',
        b'href="/export/"',
    ]

    def test_user_sidebar_hides_manager_pages(self, jane_client, seeded_taxonomy):
        content = jane_client.get("/taxonomy/").content
        for link in self.MANAGER_ONLY:
            assert link not in content, link
        assert b'href="/personnel/JD01/"' in content
        assert b"My Skills" in content

    def test_manager_sidebar_shows_them(self, two_people, seeded_taxonomy):
        manager = User.objects.create_user(
            username="lead", password="strong-pass-here", role="manager"
        )
        client = Client()
        client.force_login(manager)
        content = client.get("/taxonomy/").content
        for link in self.MANAGER_ONLY:
            assert link in content, link
        assert b'href="/users/"' not in content

    def test_user_sees_no_edit_controls_on_their_own_record(self, jane_client, seeded_taxonomy):
        content = jane_client.get(reverse("personnel:person-detail", args=["JD01"])).content
        assert b"/personnel/JD01/edit/" not in content
        assert b"/personnel/JD01/delete/" not in content
        assert b"/personnel/JD01/skill/add/" not in content
        # The owner may still use their own self-assessment workbook.
        assert b"/personnel/JD01/self-assessment/export/" in content
