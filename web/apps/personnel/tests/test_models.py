import datetime

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.personnel.models import DevelopmentPlan, Person, PersonSkill
from apps.taxonomy.models import Domain, Skill


@pytest.fixture
def person(db):
    return Person.objects.create(
        id="JD01", name="Jane Doe", domains=[], start_date=datetime.date(2024, 1, 15)
    )


@pytest.fixture
def taxonomy_skill(db):
    domain = Domain.objects.using("taxonomy").create(
        id="FOUND", name="Foundations", description="Cross-cutting", categories=[]
    )
    return Skill.objects.using("taxonomy").create(
        id="FOUND-REPORT",
        name="Report Writing",
        domain=domain,
        category="foundations",
        status="active",
        description="Technical report writing",
        proficiency={},
    )


@pytest.mark.django_db(databases=["default"])
class TestPerson:
    def test_create_person(self):
        p = Person.objects.create(
            id="JD01",
            name="Jane Doe",
            domains=["analyst-junior"],
            start_date=datetime.date(2024, 1, 15),
        )
        assert p.id == "JD01"
        assert str(p) == "JD01: Jane Doe"

    def test_person_ordering(self):
        Person.objects.create(
            id="ZZ01", name="Zara", domains=[], start_date=datetime.date(2024, 1, 1)
        )
        Person.objects.create(
            id="AA01", name="Alice", domains=[], start_date=datetime.date(2024, 1, 1)
        )
        names = list(Person.objects.values_list("name", flat=True))
        assert names == ["Alice", "Zara"]


@pytest.mark.django_db(databases=["default", "taxonomy"])
class TestPersonSkill:
    def test_create_person_skill(self, person, taxonomy_skill):
        ps = PersonSkill.objects.create(
            person=person,
            skill_id="FOUND-REPORT",
            level=3,
            assessed_date=datetime.date(2024, 6, 1),
            assessed_by_id="LEAD01",
        )
        assert str(ps) == "JD01 — FOUND-REPORT (L3)"
        assert ps.person == person

    def test_person_skill_unique_together(self, person, taxonomy_skill):
        PersonSkill.objects.create(
            person=person,
            skill_id="FOUND-REPORT",
            level=3,
            assessed_date=datetime.date(2024, 6, 1),
            assessed_by_id="LEAD01",
        )
        with pytest.raises(Exception):
            PersonSkill.objects.create(
                person=person,
                skill_id="FOUND-REPORT",
                level=4,
                assessed_date=datetime.date(2024, 7, 1),
                assessed_by_id="LEAD01",
            )

    def test_clean_validates_skill_exists(self, person, taxonomy_skill):
        ps = PersonSkill(
            person=person,
            skill_id="FOUND-REPORT",
            level=3,
            assessed_date=datetime.date(2024, 6, 1),
            assessed_by_id="LEAD01",
        )
        ps.clean()  # should not raise

    def test_clean_rejects_invalid_skill(self, person):
        ps = PersonSkill(
            person=person,
            skill_id="NONEXISTENT",
            level=3,
            assessed_date=datetime.date(2024, 6, 1),
            assessed_by_id="LEAD01",
        )
        with pytest.raises(ValidationError) as exc_info:
            ps.clean()
        assert "skill_id" in exc_info.value.message_dict


@pytest.mark.django_db(databases=["default"])
class TestDevelopmentPlan:
    @pytest.fixture
    def person(self):
        return Person.objects.create(
            id="JD01", name="Jane Doe", domains=[], start_date=datetime.date(2024, 1, 15)
        )

    def test_create_development_plan(self, person):
        dp = DevelopmentPlan.objects.create(
            person=person,
            skill_id="FOUND-REPORT",
            current_level=2,
            target_level=4,
            target_date=datetime.date(2025, 6, 1),
            actions=[
                {"action": "Attend advanced report writing course", "deadline": "2025-03-01"},
                {"action": "Shadow senior analyst for 3 reports", "deadline": "2025-04-15"},
            ],
        )
        assert str(dp) == "JD01 — FOUND-REPORT: 2 → 4"
        assert len(dp.actions) == 2

    def test_development_plan_unique_together(self, person):
        DevelopmentPlan.objects.create(
            person=person,
            skill_id="FOUND-REPORT",
            current_level=2,
            target_level=4,
            target_date=datetime.date(2025, 6, 1),
            actions=[],
        )
        with pytest.raises(Exception):
            DevelopmentPlan.objects.create(
                person=person,
                skill_id="FOUND-REPORT",
                current_level=3,
                target_level=5,
                target_date=datetime.date(2025, 12, 1),
                actions=[],
            )


@pytest.mark.django_db(databases=["default", "taxonomy"])
class TestLevelConstraints:
    def test_database_rejects_level_above_five(self, person):
        from apps.personnel.models import PersonSkill

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                PersonSkill.objects.create(
                    person=person,
                    skill_id="FOUND-REPORT",
                    level=99,
                    assessed_date=datetime.date(2026, 6, 1),
                    assessed_by_id="LEAD01",
                )

    def test_database_rejects_negative_level(self, person):
        from apps.personnel.models import PersonSkill

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                PersonSkill.objects.create(
                    person=person,
                    skill_id="FOUND-REPORT",
                    level=-1,
                    assessed_date=datetime.date(2026, 6, 1),
                    assessed_by_id="LEAD01",
                )

    def test_database_rejects_self_assessment_out_of_range(self, person):
        from apps.personnel.models import SelfAssessment

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                SelfAssessment.objects.create(
                    person=person,
                    skill_id="FOUND-REPORT",
                    level=7,
                    assessed_date=datetime.date(2026, 6, 1),
                )

    def test_full_clean_rejects_unknown_skill(self, person):
        """PersonSkill.clean() has existed but never run — prove it now does."""
        from apps.personnel.models import PersonSkill

        ps = PersonSkill(
            person=person,
            skill_id="NOT-A-REAL-SKILL",
            level=3,
            assessed_date=datetime.date(2026, 6, 1),
            assessed_by_id="LEAD01",
        )
        with pytest.raises(ValidationError) as exc:
            ps.full_clean()
        assert "skill_id" in exc.value.message_dict

    def test_full_clean_rejects_out_of_range_level(self, person, taxonomy_skill):
        from apps.personnel.models import PersonSkill

        ps = PersonSkill(
            person=person,
            skill_id="FOUND-REPORT",
            level=9,
            assessed_date=datetime.date(2026, 6, 1),
            assessed_by_id="LEAD01",
        )
        with pytest.raises(ValidationError) as exc:
            ps.full_clean()
        assert "level" in exc.value.message_dict

    def test_valid_level_is_accepted(self, person, taxonomy_skill):
        from apps.personnel.models import PersonSkill

        ps = PersonSkill(
            person=person,
            skill_id="FOUND-REPORT",
            level=5,
            assessed_date=datetime.date(2026, 6, 1),
            assessed_by_id="LEAD01",
        )
        ps.full_clean()
        ps.save()
        assert PersonSkill.objects.filter(level=5).count() == 1


class TestSanitizeId:
    """Pure function — no database."""

    @pytest.mark.parametrize(
        "name,expected",
        [
            ("Jane Doe", "jane-doe"),
            ("  Jane   Doe  ", "jane-doe"),
            ("O'Brien", "o-brien"),
            ("Jean-Philippe Vandenberghe", "jean-philippe-vandenberghe"),
        ],
    )
    def test_normalises_latin_names(self, name, expected):
        from apps.personnel.models import sanitize_id

        assert sanitize_id(name) == expected

    @pytest.mark.parametrize(
        "name,expected",
        [
            ("Müller", "muller"),
            ("Žarko Petrović", "zarko-petrovic"),
            ("José Álvarez", "jose-alvarez"),
            ("Łukasz Søren", "lukasz-soren"),
            ("Johann Strauß", "johann-strauss"),
            ("Æsa Đorđe Œuvre", "aesa-dorde-oeuvre"),
        ],
    )
    def test_transliterates_accented_names(self, name, expected):
        from apps.personnel.models import sanitize_id

        assert sanitize_id(name) == expected

    @pytest.mark.parametrize("name", ["محمد", "日本語", "!!!", "   "])
    def test_returns_empty_when_nothing_survives(self, name):
        from apps.personnel.models import sanitize_id

        assert sanitize_id(name) == ""

    def test_respects_max_length(self):
        from apps.personnel.models import sanitize_id

        result = sanitize_id("a" * 200, max_length=20)
        assert len(result) == 20

    def test_does_not_end_on_a_hyphen_after_truncation(self):
        from apps.personnel.models import sanitize_id

        result = sanitize_id("abcdefghij klmnop", max_length=11)
        assert not result.endswith("-")
