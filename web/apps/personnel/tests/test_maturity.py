import datetime

import pytest

from apps.personnel.models import Person, PersonSkill
from apps.personnel.services import compute_domain_maturity
from apps.taxonomy.models import Domain, Profile, Skill


def _skill(domain, skill_id, category, status="active"):
    return Skill.objects.using("taxonomy").create(
        id=skill_id,
        name=skill_id,
        domain=domain,
        category=category,
        status=status,
        description="-",
        proficiency={},
    )


@pytest.fixture
def taxonomy(db):
    found = Domain.objects.using("taxonomy").create(
        id="FOUND",
        name="Foundations",
        description="-",
        categories=[],
    )
    hw = Domain.objects.using("taxonomy").create(
        id="HWSEC",
        name="Hardware",
        description="-",
        categories=[],
    )
    for sid in ("FOUND-A", "FOUND-B", "FOUND-C", "FOUND-D"):
        _skill(found, sid, "Foundations")
    _skill(found, "FOUND-OLD", "Foundations", status="deprecated")
    _skill(hw, "HW-1", "Cat A")
    _skill(hw, "HW-2", "Cat A")
    _skill(hw, "HW-3", "Cat B")
    profile = Profile.objects.using("taxonomy").create(
        id="HWSEC",
        name="Hardware",
        domain=hw,
        description="-",
        maturity_levels={
            "junior": {
                "title": "Junior",
                "description": "-",
                "thresholds": {"domain_skills_at": {"2": 1}},
            },
            "practitioner": {
                "title": "Practitioner",
                "description": "-",
                "thresholds": {"domain_skills_at": {"2": 2}, "min_categories": 2},
            },
        },
    )
    return profile


@pytest.fixture
def person(db):
    return Person.objects.create(id="P1", name="P One", start_date=datetime.date(2024, 1, 1))


def _assess(person, skill_id, level, self_assessed=False):
    PersonSkill.objects.create(
        person=person,
        skill_id=skill_id,
        level=level,
        assessed_date=datetime.date(2025, 1, 1),
        assessed_by_id="mgr",
        is_self_assessed=self_assessed,
    )


@pytest.mark.django_db(databases=["default", "taxonomy"])
class TestDomainMaturity:
    def test_self_assessed_rows_do_not_count(self, taxonomy, person):
        _assess(person, "HW-1", 4, self_assessed=True)
        result = compute_domain_maturity(person, taxonomy)
        assert result["level"] is None
        assert result["detail"]["domain_skill_count"] == 0

    def test_category_breadth_needs_level_two(self, taxonomy, person):
        _assess(person, "HW-1", 3)
        _assess(person, "HW-2", 3)
        _assess(person, "HW-3", 1)  # Cat B held only at awareness level
        result = compute_domain_maturity(person, taxonomy)
        assert result["detail"]["categories_covered"] == 1
        assert result["level"] == "junior"

        PersonSkill.objects.filter(skill_id="HW-3").update(level=2)
        assert compute_domain_maturity(person, taxonomy)["level"] == "practitioner"

    def test_foundation_avg_counts_unassessed_as_zero(self, taxonomy, person):
        # One strong Foundations skill must not read as a 4.0 average.
        _assess(person, "FOUND-A", 4)
        result = compute_domain_maturity(person, taxonomy)
        assert result["detail"]["foundation_avg"] == 1.0  # 4 / 4 active skills

    def test_foundation_avg_ignores_deprecated_skills(self, taxonomy, person):
        for sid in ("FOUND-A", "FOUND-B", "FOUND-C", "FOUND-D"):
            _assess(person, sid, 2)
        _assess(person, "FOUND-OLD", 0)
        assert compute_domain_maturity(person, taxonomy)["detail"]["foundation_avg"] == 2.0
