TAXONOMY_APPS = {"taxonomy"}
PERSONNEL_APPS = {"personnel", "accounts", "sessions", "axes", "admin", "auth", "contenttypes"}


class PersonnelRouter:
    def _get_db(self, model):
        if model._meta.app_label in TAXONOMY_APPS:
            return "taxonomy"
        return "default"

    def db_for_read(self, model, **hints):
        return self._get_db(model)

    def db_for_write(self, model, **hints):
        return self._get_db(model)

    def allow_relation(self, obj1, obj2, **hints):
        db1 = self._get_db(type(obj1))
        db2 = self._get_db(type(obj2))
        return db1 == db2

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if app_label in TAXONOMY_APPS:
            return db == "taxonomy"
        return db == "default"
