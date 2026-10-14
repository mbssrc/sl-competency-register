from apps.core.db_router import PersonnelRouter


class FakeModel:
    class _meta:
        app_label = "taxonomy"


class FakePersonnelModel:
    class _meta:
        app_label = "personnel"


class TestPersonnelRouter:
    def setup_method(self):
        self.router = PersonnelRouter()

    def test_taxonomy_model_routes_to_taxonomy_db(self):
        assert self.router.db_for_read(FakeModel) == "taxonomy"
        assert self.router.db_for_write(FakeModel) == "taxonomy"

    def test_personnel_model_routes_to_default_db(self):
        assert self.router.db_for_read(FakePersonnelModel) == "default"
        assert self.router.db_for_write(FakePersonnelModel) == "default"

    def test_allow_migrate_taxonomy_to_taxonomy_db(self):
        assert self.router.allow_migrate("taxonomy", "taxonomy") is True
        assert self.router.allow_migrate("default", "taxonomy") is False

    def test_allow_migrate_personnel_to_default_db(self):
        assert self.router.allow_migrate("default", "personnel") is True
        assert self.router.allow_migrate("taxonomy", "personnel") is False
