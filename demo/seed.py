#!/usr/bin/env python3
"""Load the committed demo snapshot into a throwaway personnel database.

Run through demo/demo.sh, which points PERSONNEL_DATA_DIR at a scratch
directory first. Run directly only if you have set that variable yourself: the
guards below refuse to write anywhere near a real personnel database.
"""

import argparse
import datetime
import os
import sys
from pathlib import Path

DEMO_DIR = Path(__file__).resolve().parent
REPO_ROOT = DEMO_DIR.parent
WEB_DIR = REPO_ROOT / "web"


def guard_data_dir():
    """Refuse to run unless PERSONNEL_DATA_DIR points somewhere disposable.

    The demo writes fiction. A mistake here would mix it into real personnel
    records, which is why this check does not trust the caller.
    """
    raw = os.environ.get("PERSONNEL_DATA_DIR")
    if not raw:
        return (
            "PERSONNEL_DATA_DIR is not set, so this would use the real "
            "database at web/. Run demo/demo.sh instead, or set "
            "PERSONNEL_DATA_DIR to a throwaway directory."
        )

    data_dir = Path(raw).resolve()
    web_dir = WEB_DIR.resolve()
    if data_dir == web_dir or data_dir in web_dir.parents:
        return (
            f"PERSONNEL_DATA_DIR={data_dir} is the application's own data "
            f"directory. Point it at a throwaway directory instead."
        )
    return None


def setup_django():
    sys.path.insert(0, str(WEB_DIR))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    os.environ.setdefault("DJANGO_DEBUG", "true")
    import django

    django.setup()


def seed(snapshot, accounts, force):
    from apps.accounts.models import User
    from apps.personnel.models import (
        DevelopmentPlan,
        Person,
        PersonSkill,
        Project,
        SelfAssessment,
        sanitize_id,
    )
    from django.db import transaction
    from django.utils import timezone

    if Person.objects.exists() and not force:
        print(
            "The personnel database already holds people. Pass --force to "
            "replace them, or start from an empty directory.",
            file=sys.stderr,
        )
        return 1

    # Person IDs come from the application's own sanitizer, so demo URLs read
    # /personnel/amara-okonkwo/ and the transliteration path is exercised.
    person_ids = {p["id"]: sanitize_id(p["name"]) for p in snapshot["people"]}

    with transaction.atomic():
        if force:
            Person.objects.all().delete()
            Project.objects.all().delete()
            # By the usernames the accounts file declares, not a prefix: the
            # demo accounts are named after their roles, so a prefix match
            # would miss them and the re-insert would hit the unique
            # constraint on username.
            User.objects.filter(username__in=[a["username"] for a in accounts]).delete()

        for record in snapshot["people"]:
            person = Person.objects.create(
                id=person_ids[record["id"]],
                name=record["name"],
                domains=record["profiles"],
                start_date=record["start_date"],
            )
            PersonSkill.objects.bulk_create(
                [
                    PersonSkill(
                        person=person,
                        skill_id=row["skill"],
                        level=row["level"],
                        assessed_date=row["assessed_date"],
                        assessed_by_id=row["assessed_by"],
                        last_practiced=row.get("last_practiced"),
                        evidence_notes=row.get("evidence_notes", ""),
                        authorization=row.get("authorization"),
                        # Two different states share the "self-assessment"
                        # assessor. An import leaves a level-0 placeholder with the
                        # flag off, because nothing has been claimed as
                        # authoritative; seed_self_assessment promotes a level and
                        # sets the flag. Level is what tells them apart.
                        is_self_assessed=(
                            row["assessed_by"] == "self-assessment" and row["level"] > 0
                        ),
                    )
                    for row in record["skills"]
                ]
            )
            DevelopmentPlan.objects.bulk_create(
                [
                    DevelopmentPlan(
                        person=person,
                        skill_id=target["skill"],
                        current_level=target["current_level"],
                        target_level=target["target_level"],
                        target_date=target["target_date"],
                        actions=target["actions"],
                    )
                    for target in record.get("development_plan", [])
                ]
            )

        for key, rows in snapshot["self_assessments"].items():
            person = Person.objects.get(pk=person_ids[key])
            SelfAssessment.objects.bulk_create(
                [
                    SelfAssessment(
                        person=person,
                        skill_id=row["skill"],
                        level=row["level"],
                        assessed_date=row["assessed_date"],
                        evidence_notes=row.get("evidence_notes", ""),
                    )
                    for row in rows
                ]
            )

        for spec in snapshot["projects"]:
            notes = ""
            if spec.get("completed_date"):
                notes = f"Completed {spec['completed_date']}."
            Project.objects.create(
                id=spec["id"],
                name=spec["name"],
                description=spec["description"],
                status=spec["status"],
                required_competencies=spec["required_competencies"],
                source_service_id=spec.get("source_service_id", ""),
                created_by_id="manager",
                notes=notes,
            )
            # created_at is auto_now_add, so it has to be rewritten after the
            # insert; otherwise every project claims today and the project
            # list's -created_at ordering shows seed order, not the campaign.
            created = timezone.make_aware(
                datetime.datetime.fromisoformat(spec["created_date"] + "T09:00:00")
            )
            Project.objects.filter(pk=spec["id"]).update(created_at=created)

        for account in accounts:
            user = User(
                username=account["username"],
                role=account["role"],
                is_staff=account["role"] == "admin",
            )
            if account.get("person"):
                user.person_id = person_ids[account["person"]]
            user.set_password(account["password"])
            user.save()

    return 0


def main():
    parser = argparse.ArgumentParser(description="Seed the demo population.")
    parser.add_argument("--force", action="store_true", help="Replace an existing demo population.")
    args = parser.parse_args()

    problem = guard_data_dir()
    if problem:
        print(f"demo/seed.py refused to run: {problem}", file=sys.stderr)
        return 2

    sys.path.insert(0, str(DEMO_DIR))
    import expand

    snapshot = expand.load_json(expand.SNAPSHOT_PATH)
    accounts = expand.load_json(DEMO_DIR / "accounts.json")

    setup_django()
    status = seed(snapshot, accounts, args.force)
    if status == 0:
        rows = sum(len(p["skills"]) for p in snapshot["people"])
        print(
            f"Seeded {len(snapshot['people'])} people, {rows} assessments, "
            f"{len(snapshot['projects'])} projects, {len(accounts)} accounts."
        )
    return status


if __name__ == "__main__":
    raise SystemExit(main())
