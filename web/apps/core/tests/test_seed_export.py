import json

import pytest
from django.core.management import call_command

from apps.core.models import TaxonomyMeta
from apps.taxonomy.models import Domain, Profile, Service, Skill


@pytest.mark.django_db(databases=["default", "taxonomy"])
class TestSeedTaxonomy:
    def test_seed_loads_domains(self):
        call_command("seed_taxonomy", verbosity=0)
        assert Domain.objects.using("taxonomy").count() == 12

    def test_seed_loads_skills(self):
        call_command("seed_taxonomy", verbosity=0)
        assert Skill.objects.using("taxonomy").count() >= 200

    def test_seed_loads_profiles(self):
        call_command("seed_taxonomy", verbosity=0)
        assert Profile.objects.using("taxonomy").count() == 11  # every domain except Foundations

    def test_seed_loads_services(self):
        call_command("seed_taxonomy", verbosity=0)
        assert Service.objects.using("taxonomy").count() == 17

    def test_seed_loads_meta(self):
        call_command("seed_taxonomy", verbosity=0)
        meta = TaxonomyMeta.load()
        assert meta.version == "1.0.0"

    def test_seed_is_idempotent(self):
        call_command("seed_taxonomy", verbosity=0)
        count1 = Skill.objects.using("taxonomy").count()
        call_command("seed_taxonomy", verbosity=0)
        count2 = Skill.objects.using("taxonomy").count()
        assert count1 == count2

    def test_seed_wires_requires_relationships(self):
        call_command("seed_taxonomy", verbosity=0)
        skills_with_requires = (
            Skill.objects.using("taxonomy").filter(requires__isnull=False).distinct()
        )
        assert skills_with_requires.count() > 0

    def test_seed_loads_profile_maturity_levels(self):
        call_command("seed_taxonomy", verbosity=0)
        profile = Profile.objects.using("taxonomy").first()
        assert len(profile.maturity_levels) > 0


@pytest.mark.django_db(databases=["taxonomy"])
class TestExportTaxonomy:
    def test_export_produces_json_files(self, tmp_path):
        call_command("seed_taxonomy", verbosity=0)
        call_command("export_taxonomy", str(tmp_path), verbosity=0)
        domain_dirs = [d for d in tmp_path.iterdir() if d.is_dir()]
        assert len(domain_dirs) > 0
        skill_files = list(tmp_path.rglob("*.json"))
        assert len(skill_files) > 0

    def test_round_trip_preserves_skill_count(self, tmp_path):
        call_command("seed_taxonomy", verbosity=0)
        skill_count = Skill.objects.using("taxonomy").count()
        call_command("export_taxonomy", str(tmp_path), verbosity=0)
        exported = [f for f in tmp_path.rglob("*.json") if not f.name.startswith("_")]
        # Exported files include skills + profiles + services
        # Just verify we have a reasonable number
        assert len(exported) >= skill_count

    def test_exported_json_is_deterministic(self, tmp_path):
        """Running export twice produces identical files."""
        call_command("seed_taxonomy", verbosity=0)
        dir1 = tmp_path / "run1"
        dir2 = tmp_path / "run2"
        call_command("export_taxonomy", str(dir1), verbosity=0)
        call_command("export_taxonomy", str(dir2), verbosity=0)
        files1 = sorted(f.relative_to(dir1) for f in dir1.rglob("*.json"))
        files2 = sorted(f.relative_to(dir2) for f in dir2.rglob("*.json"))
        assert files1 == files2
        for rel in files1:
            assert (dir1 / rel).read_text(encoding="utf-8") == (dir2 / rel).read_text(
                encoding="utf-8"
            )


@pytest.mark.django_db(databases=["default", "taxonomy"])
class TestCheckIntegrity:
    def test_integrity_passes_on_clean_data(self):
        call_command("seed_taxonomy", verbosity=0)
        call_command("check_integrity", verbosity=0)


@pytest.mark.django_db(databases=["default", "taxonomy"])
class TestEncodingIndependence:
    def test_roundtrips_non_ascii_under_ascii_locale(self, tmp_path, monkeypatch):
        """Export then re-import a non-ASCII description.

        Under systemd with no LANG, Python's default encoding for open() and
        write_text() can resolve to ASCII; these commands must not depend on it.
        """
        from django.core.management import call_command

        from apps.taxonomy.models import Domain

        call_command("seed_taxonomy", verbosity=0)
        domain = Domain.objects.using("taxonomy").first()
        domain.description = "Analyse des émissions — ‹signal› 日本"
        domain.save(using="taxonomy")

        monkeypatch.setenv("LC_ALL", "C")
        monkeypatch.setenv("LANG", "C")

        out = tmp_path / "export"
        call_command("export_taxonomy", str(out), verbosity=0)

        written = (out / "taxonomy" / "_meta.json").read_text(encoding="utf-8")
        assert written  # did not raise

        call_command("seed_taxonomy", source=str(out), verbosity=0)
        reloaded = Domain.objects.using("taxonomy").get(pk=domain.pk)
        assert reloaded.description == "Analyse des émissions — ‹signal› 日本"

    def test_seed_reports_the_file_it_failed_on(self, tmp_path):
        from django.core.management import call_command
        from django.core.management.base import CommandError

        (tmp_path / "taxonomy").mkdir()
        (tmp_path / "taxonomy" / "_meta.json").write_text("{not json", encoding="utf-8")
        with pytest.raises(CommandError) as exc:
            call_command("seed_taxonomy", source=str(tmp_path), verbosity=0)
        assert "_meta.json" in str(exc.value)


@pytest.mark.django_db(databases=["default", "taxonomy"])
class TestExportLayout:
    def test_export_writes_the_layout_seed_reads(self, tmp_path):
        """export_taxonomy <dir> must produce what seed_taxonomy --source <dir>
        reads, which is also the repo's own layout — so exporting into
        TAXONOMY_JSON_DIR updates taxonomy/ in place instead of scattering
        domain directories beside it."""
        call_command("seed_taxonomy", verbosity=0)
        call_command("export_taxonomy", str(tmp_path), verbosity=0)
        top = sorted(p.name for p in tmp_path.iterdir())
        assert top == ["profiles", "services", "taxonomy"]
        assert (tmp_path / "taxonomy" / "_meta.json").is_file()

    def test_default_output_is_taxonomy_json_dir(self, tmp_path, settings):
        call_command("seed_taxonomy", verbosity=0)
        settings.TAXONOMY_JSON_DIR = tmp_path
        call_command("export_taxonomy", verbosity=0)
        assert (tmp_path / "taxonomy" / "_meta.json").is_file()

    def test_download_archive_mirrors_the_repo_layout(self):
        import io
        import tarfile

        from django.test import Client

        from apps.accounts.models import User

        call_command("seed_taxonomy", verbosity=0)
        admin = User.objects.create_user(username="admin", password="x", role="admin")
        client = Client()
        client.force_login(admin)
        response = client.post("/admin-tools/export-download/")
        assert response.status_code == 200
        with tarfile.open(fileobj=io.BytesIO(response.content), mode="r:gz") as tar:
            names = tar.getnames()
        assert "taxonomy/_meta.json" in names
        assert any(n.startswith("profiles/") for n in names)
        assert any(n.startswith("services/") for n in names)


@pytest.mark.django_db(databases=["default", "taxonomy"])
class TestSeedConvergence:
    def test_seed_is_atomic_on_failure(self, tmp_path):
        """A malformed file part-way through must leave nothing behind."""
        from django.core.management import call_command
        from django.core.management.base import CommandError

        from apps.taxonomy.models import Skill

        call_command("seed_taxonomy", verbosity=0)
        call_command("export_taxonomy", str(tmp_path), verbosity=0)
        Skill.objects.using("taxonomy").all().delete()

        # Corrupt the last skill file walked, so hundreds of rows have been
        # written before the failure and only a rollback can remove them.
        victim = sorted(tmp_path.glob("taxonomy/*/*/*.json"))[-1]
        victim.write_text("{ broken", encoding="utf-8")

        with pytest.raises(CommandError):
            call_command("seed_taxonomy", source=str(tmp_path), verbosity=0)

        assert Skill.objects.using("taxonomy").count() == 0

    def test_prune_removes_rows_with_no_json_file(self, tmp_path):
        from django.core.management import call_command

        from apps.taxonomy.models import Skill

        call_command("seed_taxonomy", verbosity=0)
        call_command("export_taxonomy", str(tmp_path), verbosity=0)

        removed = sorted(tmp_path.glob("taxonomy/*/*/*.json"))[0]
        removed_id = json.loads(removed.read_text(encoding="utf-8"))["id"]
        removed.unlink()

        call_command("seed_taxonomy", source=str(tmp_path), prune=True, verbosity=0)
        assert not Skill.objects.using("taxonomy").filter(id=removed_id).exists()

    def test_without_prune_stale_rows_are_kept(self, tmp_path):
        from django.core.management import call_command

        from apps.taxonomy.models import Skill

        call_command("seed_taxonomy", verbosity=0)
        call_command("export_taxonomy", str(tmp_path), verbosity=0)

        removed = sorted(tmp_path.glob("taxonomy/*/*/*.json"))[0]
        removed_id = json.loads(removed.read_text(encoding="utf-8"))["id"]
        removed.unlink()

        call_command("seed_taxonomy", source=str(tmp_path), verbosity=0)
        assert Skill.objects.using("taxonomy").filter(id=removed_id).exists()


@pytest.mark.django_db(databases=["default", "taxonomy"])
class TestExportIntoSourceTree:
    """Exporting into an existing tree must update its files in place.

    The admin "Run Export" button writes into TAXONOMY_JSON_DIR — the repo's
    own JSON tree — so anything other than an exact, in-place rewrite either
    duplicates records under new file names (and the next seed reverts the
    edit) or drops content the repo files carry.
    """

    @pytest.fixture
    def source_copy(self, tmp_path, settings):
        import shutil

        root = settings.TAXONOMY_JSON_DIR
        for name in ("taxonomy", "profiles", "services"):
            shutil.copytree(root / name, tmp_path / name)
        return tmp_path

    @staticmethod
    def _snapshot(root):
        return {
            str(p.relative_to(root)): json.loads(p.read_text(encoding="utf-8"))
            for p in sorted(root.rglob("*.json"))
        }

    def test_round_trip_leaves_the_tree_unchanged(self, source_copy):
        before = self._snapshot(source_copy)
        call_command("seed_taxonomy", source=str(source_copy), verbosity=0)
        call_command("export_taxonomy", str(source_copy), verbosity=0)
        after = self._snapshot(source_copy)

        assert sorted(after) == sorted(before), "export added or renamed files"
        changed = [path for path in before if before[path] != after[path]]
        assert not changed, f"export altered {len(changed)} files, e.g. {changed[:3]}"

    def test_a_tag_reorder_survives_export(self, source_copy):
        """Only requires/recommended keep their file order: export sorts those
        by id itself. Any other list is ordered by the user and must be kept."""
        call_command("seed_taxonomy", source=str(source_copy), verbosity=0)
        skill = Skill.objects.using("taxonomy").get(pk="ADVSIM-RED-DEBRIEF")
        assert len(skill.tags) > 1
        reordered = list(reversed(skill.tags))
        skill.tags = reordered
        skill.save(using="taxonomy")

        call_command("export_taxonomy", str(source_copy), verbosity=0)
        call_command("seed_taxonomy", source=str(source_copy), verbosity=0)

        assert Skill.objects.using("taxonomy").get(pk=skill.pk).tags == reordered

    def test_an_edit_survives_export_and_reseed(self, source_copy):
        call_command("seed_taxonomy", source=str(source_copy), verbosity=0)
        # Its repo file name (debrief-purple-teaming.json) is not derived from
        # its id, which is what exposed the duplicate-file bug.
        skill = Skill.objects.using("taxonomy").get(pk="ADVSIM-RED-DEBRIEF")
        skill.name = "Renamed By A Manager"
        skill.save(using="taxonomy")

        call_command("export_taxonomy", str(source_copy), verbosity=0)
        call_command("seed_taxonomy", source=str(source_copy), verbosity=0)

        assert Skill.objects.using("taxonomy").get(pk=skill.pk).name == "Renamed By A Manager"


@pytest.mark.django_db(databases=["default", "taxonomy"])
class TestRelationshipConvergence:
    def test_removing_relations_from_json_clears_them(self, tmp_path):
        call_command("seed_taxonomy", verbosity=0)
        call_command("export_taxonomy", str(tmp_path), verbosity=0)

        skill = Skill.objects.using("taxonomy").filter(requires__isnull=False).first()
        other = Skill.objects.using("taxonomy").exclude(pk=skill.pk).first()
        skill.superseded_by = other
        skill.save(using="taxonomy")
        assert skill.requires.exists()

        path = next(
            p
            for p in (tmp_path / "taxonomy").rglob("*.json")
            if json.loads(p.read_text(encoding="utf-8")).get("id") == skill.id
        )
        data = json.loads(path.read_text(encoding="utf-8"))
        data.pop("requires", None)
        data.pop("superseded_by", None)
        path.write_text(json.dumps(data), encoding="utf-8")

        call_command("seed_taxonomy", source=str(tmp_path), verbosity=0)
        skill.refresh_from_db()
        assert not skill.requires.exists()
        assert skill.superseded_by is None
