import datetime

import pytest

from apps.personnel.models import Person, PersonSkill
from apps.personnel.services import compute_service_readiness
from apps.taxonomy.models import Domain, Service, Skill


@pytest.fixture
def taxonomy_domain(db):
    return Domain.objects.using("taxonomy").create(
        id="FOUND",
        name="Foundations",
        description="Cross-cutting",
        categories=[],
    )


@pytest.fixture
def taxonomy_skills(taxonomy_domain):
    s1 = Skill.objects.using("taxonomy").create(
        id="FOUND-REPORT",
        name="Report Writing",
        domain=taxonomy_domain,
        category="foundations",
        status="active",
        description="Technical report writing",
        proficiency={},
    )
    s2 = Skill.objects.using("taxonomy").create(
        id="FOUND-REVIEW",
        name="Peer Review",
        domain=taxonomy_domain,
        category="foundations",
        status="active",
        description="Peer review process",
        proficiency={},
    )
    return s1, s2


@pytest.fixture
def taxonomy_service(taxonomy_skills):
    return Service.objects.using("taxonomy").create(
        id="SVC-PEN",
        name="Penetration Testing",
        description="Pen test service",
        required_competencies=[
            {"skill": "FOUND-REPORT", "minimum_level": 3},
            {"skill": "FOUND-REVIEW", "minimum_level": 2},
        ],
    )


@pytest.fixture
def person(db):
    return Person.objects.create(
        id="JD01",
        name="Jane Doe",
        start_date=datetime.date(2024, 1, 15),
    )


@pytest.mark.django_db(databases=["default", "taxonomy"])
class TestServiceReadiness:
    def test_no_personnel_shows_zero(self, taxonomy_service, taxonomy_skills):
        results = compute_service_readiness()
        assert len(results) == 1

        service = results[0]
        assert service["service_name"] == "Penetration Testing"
        assert service["fully_staffable"] is False
        for comp in service["competencies"]:
            assert comp["qualified_count"] == 0

    def test_qualified_personnel_counted(self, person, taxonomy_service, taxonomy_skills):
        PersonSkill.objects.create(
            person=person,
            skill_id="FOUND-REPORT",
            level=4,
            assessed_date=datetime.date(2024, 6, 1),
            assessed_by_id="LEAD01",
        )
        PersonSkill.objects.create(
            person=person,
            skill_id="FOUND-REVIEW",
            level=3,
            assessed_date=datetime.date(2024, 6, 1),
            assessed_by_id="LEAD01",
        )

        results = compute_service_readiness()
        assert len(results) == 1

        service = results[0]
        assert service["fully_staffable"] is True
        for comp in service["competencies"]:
            assert comp["qualified_count"] == 1
            assert "Jane Doe" in comp["qualified_people"]


@pytest.fixture
def project_with_requirements(person, taxonomy_skills):
    from apps.personnel.models import Project

    PersonSkill.objects.create(
        person=person,
        skill_id="FOUND-REPORT",
        level=4,
        assessed_date=datetime.date(2024, 6, 1),
        assessed_by_id="LEAD01",
    )
    return Project.objects.create(
        id="p1",
        name="Audit",
        status="planning",
        required_competencies=[
            {"skill": "FOUND-REPORT", "minimum_level": 3},
            {"skill": "FOUND-REVIEW", "minimum_level": 2},
        ],
    )


@pytest.mark.django_db(databases=["default", "taxonomy"])
class TestCoverageWithoutPersonnel:
    def test_omits_names_and_counts(self, project_with_requirements):
        from apps.personnel.services import compute_project_coverage

        coverage = compute_project_coverage(project_with_requirements, include_personnel=False)
        assert coverage
        for entry in coverage:
            assert set(entry) == {"skill_id", "skill_name", "minimum_level", "is_covered"}

    def test_still_reports_coverage_correctly(self, project_with_requirements):
        from apps.personnel.services import compute_project_coverage

        with_names = compute_project_coverage(project_with_requirements)
        without = compute_project_coverage(project_with_requirements, include_personnel=False)
        assert [c["is_covered"] for c in with_names] == [c["is_covered"] for c in without]
