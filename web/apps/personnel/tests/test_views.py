import datetime

import pytest
from django.test import Client
from django.urls import reverse

from apps.accounts.models import User
from apps.personnel.models import DevelopmentPlan, Person, PersonSkill
from apps.taxonomy.models import Domain, Profile, Skill


@pytest.fixture
def regular_user(db):
    return User.objects.create_user(username="analyst", password="testpass", role="user")


@pytest.fixture
def manager_user(db):
    return User.objects.create_user(username="lead", password="testpass", role="manager")


@pytest.fixture
def taxonomy_domain(db):
    return Domain.objects.using("taxonomy").create(
        id="FOUND",
        name="Foundations",
        description="Cross-cutting",
        categories=[],
    )


@pytest.fixture
def taxonomy_skill(taxonomy_domain):
    return Skill.objects.using("taxonomy").create(
        id="FOUND-REPORT",
        name="Report Writing",
        domain=taxonomy_domain,
        category="foundations",
        status="active",
        description="Technical report writing",
        proficiency={},
    )


@pytest.fixture
def taxonomy_profile(taxonomy_skill):
    return Profile.objects.using("taxonomy").create(
        id="FOUND",
        name="Foundations",
        domain=taxonomy_skill.domain,
        description="Entry-level analyst",
        maturity_levels={
            "junior": {
                "title": "Junior Analyst",
                "thresholds": {"domain_skills_at": {"1": 1}},
            },
        },
    )


@pytest.fixture
def person(db):
    return Person.objects.create(
        id="JD01",
        name="Jane Doe",
        domains=[],
        start_date=datetime.date(2024, 1, 15),
    )


@pytest.fixture
def person_with_skills(person, taxonomy_skill):
    PersonSkill.objects.create(
        person=person,
        skill_id="FOUND-REPORT",
        level=3,
        assessed_date=datetime.date(2024, 6, 1),
        assessed_by_id="LEAD01",
    )
    DevelopmentPlan.objects.create(
        person=person,
        skill_id="FOUND-REPORT",
        current_level=3,
        target_level=5,
        target_date=datetime.date(2025, 6, 1),
        actions=[{"action": "Take advanced course", "deadline": "2025-03-01"}],
    )
    return person


@pytest.mark.django_db(databases=["default", "taxonomy"])
class TestPersonList:
    def test_unauthenticated_redirects(self):
        client = Client()
        response = client.get(reverse("personnel:person-list"))
        assert response.status_code == 302

    def test_logged_in_can_access(self, manager_user, person, taxonomy_profile):
        client = Client()
        client.force_login(manager_user)
        response = client.get(reverse("personnel:person-list"))
        assert response.status_code == 200
        assert b"Jane Doe" in response.content

    def test_foundations_is_not_listed_as_a_specialism(
        self, manager_user, person, taxonomy_profile
    ):
        """Foundations is the shared base, not a domain anyone specialises in.

        The person form already refuses to offer it ("Foundations is always
        included") and there is no Foundations ladder for it to be graded on,
        so a record that carries it from before that rule must not be shown
        as though it were a specialism.
        """
        person.domains = ["FOUND", "HWSEC"]
        person.save()
        client = Client()
        client.force_login(manager_user)

        response = client.get(reverse("personnel:person-list"))

        listed = {d["id"] for row in response.context["person_data"] for d in row["domains"]}
        assert "FOUND" not in listed
        assert "HWSEC" in listed


@pytest.mark.django_db(databases=["default", "taxonomy"])
class TestPersonDetail:
    def test_shows_skills_and_plans(self, manager_user, person_with_skills, taxonomy_profile):
        client = Client()
        client.force_login(manager_user)
        response = client.get(reverse("personnel:person-detail", args=["JD01"]))
        assert response.status_code == 200
        assert b"Jane Doe" in response.content
        assert b"FOUND-REPORT" in response.content
        assert b"Report Writing" in response.content

    def test_unauthenticated_redirects(self, person):
        client = Client()
        response = client.get(reverse("personnel:person-detail", args=["JD01"]))
        assert response.status_code == 302

    def test_404_for_missing_person(self, manager_user):
        client = Client()
        client.force_login(manager_user)
        response = client.get(reverse("personnel:person-detail", args=["NOPE"]))
        assert response.status_code == 404


@pytest.mark.django_db(databases=["default", "taxonomy"])
class TestGapAnalysis:
    def test_gap_analysis_renders(self, manager_user, person_with_skills, taxonomy_profile):
        client = Client()
        client.force_login(manager_user)
        response = client.get(reverse("personnel:gap-analysis"))
        assert response.status_code == 200
        assert b"Gap Analysis" in response.content

    def test_unauthenticated_redirects(self):
        client = Client()
        response = client.get(reverse("personnel:gap-analysis"))
        assert response.status_code == 302

    def test_filter_by_person(self, manager_user, person_with_skills, taxonomy_profile):
        client = Client()
        client.force_login(manager_user)
        # With a non-matching filter, should show no gaps
        response = client.get(reverse("personnel:gap-analysis") + "?person=NOPE")
        assert response.status_code == 200

    def test_person_filter_is_searchable(self, manager_user, person_with_skills, taxonomy_profile):
        client = Client()
        client.force_login(manager_user)
        response = client.get(reverse("personnel:gap-analysis"))
        assert b'x-data="combobox"' in response.content
        assert b'name="person"' in response.content


@pytest.mark.django_db(databases=["default", "taxonomy"])
class TestServiceReadiness:
    def test_readiness_renders(self, manager_user, taxonomy_profile):
        client = Client()
        client.force_login(manager_user)
        response = client.get(reverse("personnel:service-readiness"))
        assert response.status_code == 200
        assert b"Service Readiness" in response.content

    def test_unauthenticated_redirects(self):
        client = Client()
        response = client.get(reverse("personnel:service-readiness"))
        assert response.status_code == 302
