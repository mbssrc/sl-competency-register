"""Tests for the demo snapshot validator."""

from validate import check_evidence_markers, check_known_skills, check_levels_in_range


def snapshot(skills, projects=None):
    return {
        "people": [
            {
                "id": "PERS-001",
                "name": "Test Person",
                "profiles": ["HWSEC"],
                "start_date": "2024-01-01",
                "skills": skills,
                "development_plan": [],
            }
        ],
        "self_assessments": {},
        "projects": projects or [],
    }


def row(skill, level=3, evidence=""):
    return {
        "skill": skill,
        "level": level,
        "assessed_date": "2026-01-01",
        "assessed_by": "e.papadakis",
        "last_practiced": "2026-01-01",
        "evidence_notes": evidence,
        "authorization": None,
    }


FINISHED = [
    {
        "id": "PRJ-A",
        "name": "Alpha",
        "status": "done",
        "required_competencies": [{"skill": "HWSEC-SCA-DPA", "minimum_level": 3}],
    }
]
PLANNED = [
    {
        "id": "PRJ-B",
        "name": "Beta",
        "status": "planning",
        "required_competencies": [{"skill": "HWSEC-SCA-DPA", "minimum_level": 3}],
    }
]


def test_an_evidence_marker_for_a_finished_project_that_required_the_skill_passes():
    errors = check_evidence_markers(
        snapshot([row("HWSEC-SCA-DPA", evidence="Project: Alpha")], FINISHED)
    )

    assert errors == []


def test_an_evidence_marker_naming_no_known_project_is_an_error():
    errors = check_evidence_markers(
        snapshot([row("HWSEC-SCA-DPA", evidence="Project: Nonexistent")], FINISHED)
    )

    assert len(errors) == 1
    assert "Nonexistent" in errors[0]


def test_an_evidence_marker_for_an_unfinished_project_is_an_error():
    errors = check_evidence_markers(
        snapshot([row("HWSEC-SCA-DPA", evidence="Project: Beta")], PLANNED)
    )

    assert len(errors) == 1
    assert "not finished" in errors[0]


def test_an_evidence_marker_on_a_skill_the_project_never_required_is_an_error():
    errors = check_evidence_markers(
        snapshot([row("HWSEC-PCB-RE", evidence="Project: Alpha")], FINISHED)
    )

    assert len(errors) == 1
    assert "did not require" in errors[0]


def test_free_text_evidence_is_not_mistaken_for_a_project_marker():
    errors = check_evidence_markers(
        snapshot(
            [row("HWSEC-SCA-DPA", evidence="Recovered AES keys on three engagements")], FINISHED
        )
    )

    assert errors == []


def test_a_level_outside_the_scale_is_an_error():
    errors = check_levels_in_range(snapshot([row("HWSEC-SCA-DPA", level=6)]))

    assert len(errors) == 1


def test_a_skill_absent_from_the_taxonomy_is_an_error():
    errors = check_known_skills(snapshot([row("HWSEC-NOT-A-SKILL")]), {"HWSEC-SCA-DPA"})

    assert len(errors) == 1
    assert "HWSEC-NOT-A-SKILL" in errors[0]
