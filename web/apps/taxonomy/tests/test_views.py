import json

import pytest
from django.core.management import call_command
from django.test import Client

from apps.accounts.models import User


@pytest.mark.django_db(databases=["default", "taxonomy"])
class TestDomainList:
    @pytest.fixture(autouse=True)
    def setup(self):
        call_command("seed_taxonomy", verbosity=0)
        self.user = User.objects.create_user(username="test", password="test123")

    def test_requires_login(self):
        client = Client()
        response = client.get("/taxonomy/")
        assert response.status_code == 302  # redirect to login

    def test_shows_domains(self):
        client = Client()
        client.force_login(self.user)
        response = client.get("/taxonomy/")
        assert response.status_code == 200
        assert b"Network Security" in response.content

    def test_domain_detail(self):
        client = Client()
        client.force_login(self.user)
        response = client.get("/taxonomy/NETSEC/")
        assert response.status_code == 200
        assert b"Network Security" in response.content

    def test_domain_detail_404(self):
        client = Client()
        client.force_login(self.user)
        response = client.get("/taxonomy/NONEXISTENT/")
        assert response.status_code == 404


@pytest.mark.django_db(databases=["default", "taxonomy"])
class TestSkillDetail:
    @pytest.fixture(autouse=True)
    def setup(self):
        call_command("seed_taxonomy", verbosity=0)
        self.user = User.objects.create_user(username="viewer", password="test123")
        self.admin = User.objects.create_user(username="admin", password="test123", role="admin")
        self.manager = User.objects.create_user(
            username="manager", password="test123", role="manager"
        )

    def test_skill_detail_renders(self):
        client = Client()
        client.force_login(self.user)
        response = client.get("/taxonomy/skill/NETSEC-RECON-PORTSCANNING/")
        assert response.status_code == 200
        assert b"Port Scanning" in response.content
        # Proficiency levels should be shown
        assert b"Awareness" in response.content
        assert b"Independent Practice" in response.content
        # Prerequisites should be shown
        assert b"FOUND-TOOLS" in response.content

    def test_skill_detail_404(self):
        client = Client()
        client.force_login(self.user)
        response = client.get("/taxonomy/skill/NONEXISTENT/")
        assert response.status_code == 404

    def test_skill_edit_requires_login(self):
        client = Client()
        response = client.get("/taxonomy/skill/NETSEC-RECON-PORTSCANNING/edit/")
        assert response.status_code == 302

    def test_manager_can_load_edit_form(self):
        client = Client()
        client.force_login(self.manager)
        response = client.get("/taxonomy/skill/NETSEC-RECON-PORTSCANNING/edit/")
        assert response.status_code == 200
        assert b"Edit Skill" in response.content

    def test_plain_user_cannot_load_edit_form(self):
        client = Client()
        client.force_login(self.user)
        response = client.get("/taxonomy/skill/NETSEC-RECON-PORTSCANNING/edit/")
        assert response.status_code == 403

    def test_manager_can_edit_skill(self):
        client = Client()
        client.force_login(self.manager)
        response = client.post(
            "/taxonomy/skill/NETSEC-RECON-PORTSCANNING/edit/",
            {
                "name": "Port Scanning Updated",
                "description": "Updated description",
                "status": "active",
                "tags": "nmap, updated, test",
            },
        )
        assert response.status_code == 302
        from apps.taxonomy.models import Skill

        assert Skill.objects.get(pk="NETSEC-RECON-PORTSCANNING").name == "Port Scanning Updated"

    def test_plain_user_cannot_edit_skill(self):
        client = Client()
        client.force_login(self.user)
        response = client.post(
            "/taxonomy/skill/NETSEC-RECON-PORTSCANNING/edit/",
            {"name": "Vandalised", "description": "d", "status": "active"},
        )
        assert response.status_code == 403
        from apps.taxonomy.models import Skill

        assert Skill.objects.get(pk="NETSEC-RECON-PORTSCANNING").name != "Vandalised"

    def test_plain_user_can_still_read(self):
        client = Client()
        client.force_login(self.user)
        for url in (
            "/taxonomy/",
            "/taxonomy/profiles/",
            "/taxonomy/services/",
            "/taxonomy/skill/NETSEC-RECON-PORTSCANNING/",
        ):
            assert client.get(url).status_code == 200, url

    def test_edit_rejects_invalid_status(self):
        client = Client()
        client.force_login(self.manager)
        response = client.post(
            "/taxonomy/skill/NETSEC-RECON-PORTSCANNING/edit/",
            {"name": "Port Scanning", "description": "d", "status": "retired"},
        )
        assert response.status_code == 200
        assert b"status must be one of" in response.content
        from apps.taxonomy.models import Skill

        assert Skill.objects.get(pk="NETSEC-RECON-PORTSCANNING").status == "active"

    def test_edit_rejects_absurd_method_count(self):
        """An unbounded range() here would spin a worker indefinitely."""
        client = Client()
        client.force_login(self.manager)
        response = client.post(
            "/taxonomy/skill/NETSEC-RECON-PORTSCANNING/edit/",
            {
                "name": "Port Scanning",
                "description": "d",
                "status": "active",
                "method_count": "1000000000",
            },
        )
        assert response.status_code == 200
        assert b"assessment method count" in response.content


@pytest.mark.django_db(databases=["default", "taxonomy"])
class TestProfileViews:
    @pytest.fixture(autouse=True)
    def setup(self):
        call_command("seed_taxonomy", verbosity=0)
        self.user = User.objects.create_user(username="viewer", password="test123")

    def test_profile_list(self):
        client = Client()
        client.force_login(self.user)
        response = client.get("/taxonomy/profiles/")
        assert response.status_code == 200
        assert b"Network Penetration Tester" in response.content

    def test_profile_detail(self):
        client = Client()
        client.force_login(self.user)
        response = client.get("/taxonomy/profiles/NETSEC/")
        assert response.status_code == 200
        assert b"Network Penetration Tester" in response.content

    def test_profile_detail_404(self):
        client = Client()
        client.force_login(self.user)
        response = client.get("/taxonomy/profiles/NONEXISTENT/")
        assert response.status_code == 404


@pytest.mark.django_db(databases=["default", "taxonomy"])
class TestServiceViews:
    @pytest.fixture(autouse=True)
    def setup(self):
        call_command("seed_taxonomy", verbosity=0)
        self.user = User.objects.create_user(username="viewer", password="test123")

    def test_service_list(self):
        client = Client()
        client.force_login(self.user)
        response = client.get("/taxonomy/services/")
        assert response.status_code == 200
        assert b"Web Application Penetration Test" in response.content

    def test_service_detail(self):
        client = Client()
        client.force_login(self.user)
        response = client.get("/taxonomy/services/SVC-PENTEST-WEB/")
        assert response.status_code == 200
        assert b"Web Application Penetration Test" in response.content
        # Required competencies should be shown
        assert b"SWSEC-WEB-XSS" in response.content

    def test_service_detail_404(self):
        client = Client()
        client.force_login(self.user)
        response = client.get("/taxonomy/services/NONEXISTENT/")
        assert response.status_code == 404


@pytest.mark.django_db(databases=["default", "taxonomy"])
class TestReorderValidation:
    @pytest.fixture(autouse=True)
    def setup(self, db):
        call_command("seed_taxonomy", verbosity=0)
        self.admin = User.objects.create_user(username="admin", password="test123", role="admin")

    def test_rejects_non_list_payload(self):
        client = Client()
        client.force_login(self.admin)
        response = client.post(
            "/taxonomy/services/reorder/",
            data='{"not": "a list"}',
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_rejects_non_string_entries(self):
        client = Client()
        client.force_login(self.admin)
        response = client.post(
            "/taxonomy/services/reorder/",
            data="[1, 2, 3]",
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_accepts_list_of_ids(self):
        client = Client()
        client.force_login(self.admin)
        response = client.post(
            "/taxonomy/services/reorder/",
            data='["svc-pentest-web", "svc-dfir"]',
            content_type="application/json",
        )
        assert response.status_code == 200
        assert response.json() == {"ok": True}


@pytest.mark.django_db(databases=["default", "taxonomy"])
class TestTaxonomyLevelValidation:
    """Every route that stores a proficiency level must bound it to 0-5."""

    @pytest.fixture(autouse=True)
    def setup(self, db):
        call_command("seed_taxonomy", verbosity=0)
        self.client = Client()
        self.client.force_login(
            User.objects.create_user(username="lead", password="test123", role="manager")
        )

    def _service_post(self, competencies):
        return self.client.post(
            "/taxonomy/services/SVC-DFIR/edit/",
            {
                "name": "DFIR",
                "description": "d",
                "competencies": competencies,
            },
        )

    @pytest.mark.parametrize(
        "line,message",
        [
            ("FOUND-REPORT:999", b"between 0 and 5"),
            ("FOUND-REPORT:x", b"must be a number"),
            ("NOT-A-SKILL:3", b"not found in taxonomy"),
            ("FOUND-REPORT", b"SKILL-ID:level"),
        ],
    )
    def test_service_edit_rejects_bad_competency_lines(self, line, message):
        from apps.taxonomy.models import Service

        before = Service.objects.get(pk="SVC-DFIR").required_competencies
        response = self._service_post(line)
        assert response.status_code == 200
        assert message in response.content
        assert Service.objects.get(pk="SVC-DFIR").required_competencies == before

    def test_service_edit_accepts_valid_competencies(self):
        from apps.taxonomy.models import Service

        response = self._service_post("FOUND-REPORT:3\nFOUND-TOOLS:2")
        assert response.status_code == 302
        assert Service.objects.get(pk="SVC-DFIR").required_competencies == [
            {"skill": "FOUND-REPORT", "minimum_level": 3},
            {"skill": "FOUND-TOOLS", "minimum_level": 2},
        ]

    def _profile_post(self, **fields):
        data = {
            "name": "Digital Forensics Analyst",
            "description": "d",
            "ml_junior_title": "Junior",
        }
        data.update({f"ml_junior_{k}": v for k, v in fields.items()})
        return self.client.post("/taxonomy/profiles/DFIR/edit/", data)

    @pytest.mark.parametrize(
        "fields,message",
        [
            ({"pinned": "FOUND-REPORT:9"}, b"between 0 and 5"),
            ({"dsa": "9:2"}, b"between 0 and 5"),
            ({"dsa": "3:many"}, b"must be a number"),
            ({"min_categories": "lots"}, b"must be a number"),
            ({"foundation_avg": "7"}, b"between 0 and 5"),
        ],
    )
    def test_profile_edit_rejects_bad_thresholds(self, fields, message):
        from apps.taxonomy.models import Profile

        before = Profile.objects.get(pk="DFIR").maturity_levels
        response = self._profile_post(**fields)
        assert response.status_code == 200
        assert message in response.content
        assert Profile.objects.get(pk="DFIR").maturity_levels == before

    def test_profile_edit_accepts_valid_thresholds(self):
        from apps.taxonomy.models import Profile

        response = self._profile_post(
            dsa="2:3", min_categories="1", foundation_avg="1.5", pinned="FOUND-REPORT:2"
        )
        assert response.status_code == 302
        junior = Profile.objects.get(pk="DFIR").maturity_levels["junior"]
        assert junior["thresholds"] == {
            "domain_skills_at": {"2": 3},
            "min_categories": 1,
            "foundation_avg": 1.5,
        }
        assert junior["pinned"] == [{"skill": "FOUND-REPORT", "minimum_level": 2}]


@pytest.mark.django_db(databases=["default", "taxonomy"])
class TestSkillFrameworkMappings:
    URL = "/taxonomy/skill/NETSEC-RECON-PORTSCANNING/"

    @pytest.fixture(autouse=True)
    def setup(self):
        call_command("seed_taxonomy", verbosity=0)
        self.manager = User.objects.create_user(
            username="manager", password="test123", role="manager"
        )
        self.client = Client()
        self.client.force_login(self.manager)

    def _post(self, **extra):
        data = {
            "name": "Port Scanning",
            "description": "d",
            "status": "active",
            "prof_3_label": "Independent Practice",
            "prof_3_description": "Edited description",
        }
        data.update(extra)
        return self.client.post(self.URL + "edit/", data)

    def _skill(self):
        from apps.taxonomy.models import Skill

        return Skill.objects.get(pk="NETSEC-RECON-PORTSCANNING")

    def test_detail_shows_list_valued_mappings(self):
        response = self.client.get("/taxonomy/skill/SWSEC-WEB-API/")
        assert b"CWE-285" in response.content

    def test_detail_shows_nested_mappings(self):
        response = self.client.get(self.URL)
        assert b"T1046" in response.content
        assert b"PD-WRL-007 Vulnerability Analysis" in response.content

    def test_edit_form_shows_existing_mappings(self):
        response = self.client.get(self.URL + "edit/")
        assert b"T1046" in response.content
        assert b"K0861" in response.content

    def test_edit_saves_mappings_json(self):
        response = self._post(framework_mappings='{"cwe": ["CWE-200"], "nice": {"tks": ["K0861"]}}')
        assert response.status_code == 302
        assert self._skill().framework_mappings == {"cwe": ["CWE-200"], "nice": {"tks": ["K0861"]}}

    def test_edit_without_mappings_field_keeps_them(self):
        before = self._skill().framework_mappings
        assert self._post().status_code == 302
        assert self._skill().framework_mappings == before

    def test_edit_rejects_invalid_mappings_json(self):
        before = self._skill().framework_mappings
        response = self._post(framework_mappings='{"cwe": [', name="Should Not Save")
        assert response.status_code == 200
        assert b"framework mappings is not valid JSON" in response.content
        # the submitted text is echoed back so the edit isn't lost
        assert b"{&quot;cwe&quot;: [" in response.content
        skill = self._skill()
        assert skill.framework_mappings == before
        assert skill.name == "Port Scanning"

    def test_edit_keeps_proficiency_evidence_and_authorization(self):
        assert self._post().status_code == 302
        level = self._skill().proficiency["3"]
        assert level["description"] == "Edited description"
        assert level["authorization"] is True
        assert (
            "Uses Nmap scripting engine (NSE) for targeted service detection" in level["evidence"]
        )

    def test_mapping_keys_never_reach_alpine_expressions(self):
        """Keys are manager-editable; inside an x-on/x-show attribute a quote
        would break out of the JS string and run for every viewer."""
        hostile = "x']; alert(document.domain); open['"
        assert self._post(framework_mappings=json.dumps({hostile: ["v"]})).status_code == 302
        response = self.client.get(self.URL)
        assert response.status_code == 200
        assert b"alert(document.domain)" in response.content  # shown as text...
        for line in response.content.decode().splitlines():
            if "alert(document.domain)" in line:
                assert "x-" not in line and "@click" not in line  # ...never in a directive
        assert b'x-show="open[1]"' in response.content
