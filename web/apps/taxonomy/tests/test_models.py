import pytest

from apps.taxonomy.models import Domain, Profile, Service, Skill


@pytest.mark.django_db(databases=["taxonomy"])
class TestDomain:
    def test_create_domain(self):
        d = Domain.objects.using("taxonomy").create(
            id="NETSEC",
            name="Network Security",
            description="Network security skills",
            categories=[
                {"id": "NETSEC-RECON", "name": "Reconnaissance", "description": "Recon skills"}
            ],
        )
        assert d.id == "NETSEC"
        assert str(d) == "Network Security"

    def test_domain_optional_fields(self):
        d = Domain.objects.using("taxonomy").create(
            id="HWSEC",
            name="Hardware Security",
            description="HW skills",
            categories=[],
            note="No framework covers this",
            attack_tiers=[{"tier": "non-invasive", "categories": ["HWSEC-SCA"]}],
        )
        assert d.note == "No framework covers this"
        assert len(d.attack_tiers) == 1


@pytest.mark.django_db(databases=["taxonomy"])
class TestSkill:
    @pytest.fixture
    def domain(self):
        return Domain.objects.using("taxonomy").create(
            id="FOUND", name="Foundations", description="Cross-cutting", categories=[]
        )

    def test_create_skill(self, domain):
        s = Skill.objects.using("taxonomy").create(
            id="FOUND-REPORT",
            name="Report Writing",
            domain=domain,
            category="foundations",
            status="active",
            description="Technical report writing",
            proficiency={"0": {"label": "None", "description": "No exposure"}},
        )
        assert s.id == "FOUND-REPORT"
        assert str(s) == "FOUND-REPORT: Report Writing"

    def test_skill_requires_relationship(self, domain):
        s1 = Skill.objects.using("taxonomy").create(
            id="FOUND-REPORT",
            name="Report Writing",
            domain=domain,
            category="foundations",
            status="active",
            description="Reports",
            proficiency={},
        )
        s2 = Skill.objects.using("taxonomy").create(
            id="FOUND-COMM",
            name="Communication",
            domain=domain,
            category="foundations",
            status="active",
            description="Comms",
            proficiency={},
        )
        s2.requires.add(s1)
        assert s1 in s2.requires.all()
        assert s2 in s1.required_by.all()

    def test_deprecated_skill_with_superseded_by(self, domain):
        s1 = Skill.objects.using("taxonomy").create(
            id="OLD-SKILL",
            name="Old",
            domain=domain,
            category="foundations",
            status="active",
            description="Old",
            proficiency={},
        )
        s2 = Skill.objects.using("taxonomy").create(
            id="NEW-SKILL",
            name="New",
            domain=domain,
            category="foundations",
            status="deprecated",
            description="New",
            proficiency={},
            superseded_by=s1,
        )
        assert s2.superseded_by == s1


@pytest.mark.django_db(databases=["taxonomy"])
class TestProfile:
    def test_create_profile_with_maturity_levels(self):
        p = Profile.objects.using("taxonomy").create(
            id="PROF-TEST",
            name="Test Profile",
            description="Testing",
            maturity_levels={
                "junior": {"title": "Junior", "thresholds": {"domain_skills_at": {"1": 3}}},
                "practitioner": {
                    "title": "Practitioner",
                    "thresholds": {"domain_skills_at": {"2": 5}},
                },
            },
        )
        assert len(p.maturity_levels) == 2


@pytest.mark.django_db(databases=["taxonomy"])
class TestService:
    def test_create_service_with_competencies(self):
        s = Service.objects.using("taxonomy").create(
            id="SVC-TEST",
            name="Test Service",
            description="Testing",
            required_competencies=[{"skill": "FOUND-REPORT", "minimum_level": 3}],
            standards=["ISO 27001"],
        )
        assert len(s.required_competencies) == 1
