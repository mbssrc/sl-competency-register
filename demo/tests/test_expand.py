"""Tests for the demo population solver."""

import datetime
import json

import pytest
from conftest import REPO
from expand import (
    Skill,
    Taxonomy,
    UnsatisfiableArchetype,
    expand_all,
    expand_person,
    expand_self_assessments,
    load_services,
    load_taxonomy,
    repair_prerequisites,
    resolve_requirements,
    solve_levels,
    thresholds_met,
)


def tiny_taxonomy():
    """Two HWSEC skills where DPA requires SPA, plus one Foundations skill."""
    skills = [
        Skill(
            id="HWSEC-SCA-SPA",
            name="Simple Power Analysis",
            domain_id="HWSEC",
            category="Side-Channel Analysis",
            category_id="HWSEC-SCA",
            status="active",
            requires=[],
            proficiency={},
        ),
        Skill(
            id="HWSEC-SCA-DPA",
            name="Differential Power Analysis",
            domain_id="HWSEC",
            category="Side-Channel Analysis",
            category_id="HWSEC-SCA",
            status="active",
            requires=["HWSEC-SCA-SPA"],
            proficiency={},
        ),
        Skill(
            id="FOUND-REPORT",
            name="Reporting",
            domain_id="FOUND",
            category="Foundations",
            category_id="FOUND-CORE",
            status="active",
            requires=[],
            proficiency={},
        ),
    ]
    return Taxonomy({s.id: s for s in skills})


def test_repair_prerequisites_raises_prerequisite_to_one_below_dependant():
    levels = {"HWSEC-SCA-DPA": 4}

    repaired = repair_prerequisites(levels, tiny_taxonomy(), excluded=set())

    assert repaired.get("HWSEC-SCA-SPA") == 3


def chain_taxonomy():
    """C <- B <- A: a three-link prerequisite chain."""
    skills = [
        Skill(
            id="D-C",
            name="C",
            domain_id="D",
            category="Cat",
            category_id="D-CAT",
            status="active",
            requires=[],
            proficiency={},
        ),
        Skill(
            id="D-B",
            name="B",
            domain_id="D",
            category="Cat",
            category_id="D-CAT",
            status="active",
            requires=["D-C"],
            proficiency={},
        ),
        Skill(
            id="D-A",
            name="A",
            domain_id="D",
            category="Cat",
            category_id="D-CAT",
            status="active",
            requires=["D-B"],
            proficiency={},
        ),
    ]
    return Taxonomy({s.id: s for s in skills})


def test_repair_prerequisites_propagates_through_a_chain():
    repaired = repair_prerequisites({"D-A": 5}, chain_taxonomy(), excluded=set())

    assert (repaired["D-B"], repaired["D-C"]) == (4, 3)


def test_repair_prerequisites_floors_at_two_rather_than_descending_to_zero():
    repaired = repair_prerequisites({"D-A": 2}, chain_taxonomy(), excluded=set())

    assert (repaired["D-B"], repaired["D-C"]) == (2, 2)


def test_repair_prerequisites_never_adds_an_excluded_skill():
    repaired = repair_prerequisites({"D-A": 4}, chain_taxonomy(), excluded={"D-B"})

    assert "D-B" not in repaired


def test_repair_prerequisites_never_lowers_an_already_higher_level():
    repaired = repair_prerequisites({"D-A": 3, "D-B": 5}, chain_taxonomy(), excluded=set())

    assert repaired["D-B"] == 5


def ladder_taxonomy():
    """Four HWSEC skills in two categories, plus two active Foundations skills."""
    skills = [
        Skill(
            id="HWSEC-SCA-SPA",
            name="SPA",
            domain_id="HWSEC",
            category="SCA",
            category_id="HWSEC-SCA",
            status="active",
            requires=[],
            proficiency={},
        ),
        Skill(
            id="HWSEC-SCA-DPA",
            name="DPA",
            domain_id="HWSEC",
            category="SCA",
            category_id="HWSEC-SCA",
            status="active",
            requires=[],
            proficiency={},
        ),
        Skill(
            id="HWSEC-FI-VG",
            name="VG",
            domain_id="HWSEC",
            category="FI",
            category_id="HWSEC-FI",
            status="active",
            requires=[],
            proficiency={},
        ),
        Skill(
            id="HWSEC-FI-CG",
            name="CG",
            domain_id="HWSEC",
            category="FI",
            category_id="HWSEC-FI",
            status="active",
            requires=[],
            proficiency={},
        ),
        Skill(
            id="FOUND-REPORT",
            name="Reporting",
            domain_id="FOUND",
            category="Core",
            category_id="FOUND-CORE",
            status="active",
            requires=[],
            proficiency={},
        ),
        Skill(
            id="FOUND-QA",
            name="QA",
            domain_id="FOUND",
            category="Core",
            category_id="FOUND-CORE",
            status="active",
            requires=[],
            proficiency={},
        ),
    ]
    return Taxonomy({s.id: s for s in skills})


def test_thresholds_met_requires_the_counted_number_of_skills_at_level():
    rung = {"thresholds": {"domain_skills_at": {"3": 3}}}
    tax = ladder_taxonomy()

    two_at_three = {"HWSEC-SCA-SPA": 3, "HWSEC-SCA-DPA": 3, "HWSEC-FI-VG": 2}
    three_at_three = {"HWSEC-SCA-SPA": 3, "HWSEC-SCA-DPA": 3, "HWSEC-FI-VG": 3}

    assert thresholds_met(rung, two_at_three, tax, "HWSEC") is False
    assert thresholds_met(rung, three_at_three, tax, "HWSEC") is True


def test_thresholds_met_counts_a_category_only_from_level_two():
    rung = {"thresholds": {"min_categories": 2}}
    tax = ladder_taxonomy()

    second_category_at_one = {"HWSEC-SCA-SPA": 4, "HWSEC-FI-VG": 1}
    second_category_at_two = {"HWSEC-SCA-SPA": 4, "HWSEC-FI-VG": 2}

    assert thresholds_met(rung, second_category_at_one, tax, "HWSEC") is False
    assert thresholds_met(rung, second_category_at_two, tax, "HWSEC") is True


def test_thresholds_met_averages_foundation_over_every_active_foundations_skill():
    # Two active Foundations skills. One held at 3, the other absent, averages 1.5.
    rung = {"thresholds": {"foundation_avg": 2.0}}
    tax = ladder_taxonomy()

    assert thresholds_met(rung, {"FOUND-REPORT": 3}, tax, "HWSEC") is False
    assert thresholds_met(rung, {"FOUND-REPORT": 3, "FOUND-QA": 1}, tax, "HWSEC") is True


def test_thresholds_met_requires_every_pinned_skill():
    rung = {"thresholds": {}, "pinned": [{"skill": "FOUND-QA", "minimum_level": 3}]}
    tax = ladder_taxonomy()

    assert thresholds_met(rung, {"FOUND-QA": 2}, tax, "HWSEC") is False
    assert thresholds_met(rung, {"FOUND-QA": 3}, tax, "HWSEC") is True


def ladder_profile_taxonomy():
    """ladder_taxonomy plus a two-rung HWSEC maturity ladder."""
    tax = ladder_taxonomy()
    tax.profiles = {
        "HWSEC": {
            "maturity_levels": {
                "junior": {
                    "title": "Junior Evaluator",
                    "thresholds": {"domain_skills_at": {"2": 2}},
                    "pinned": [],
                },
                "practitioner": {
                    "title": "Evaluator",
                    "thresholds": {"domain_skills_at": {"3": 3}},
                    "pinned": [{"skill": "FOUND-QA", "minimum_level": 3}],
                },
            }
        }
    }
    return tax


def archetype(**overrides):
    base = {
        "key": "PERS-001",
        "name": "Test Person",
        "role": "Evaluator",
        "start_date": "2024-01-15",
        "domains": ["HWSEC"],
        "target_maturity": {"HWSEC": "junior"},
        "bands": {"strong": [], "weak": []},
        "signature": {},
        "never": [],
        "foundations": [1, 1],
        "projects": [],
        "stale_skills": [],
        "self_assessment": {"mode": "none"},
        "development_plan": [],
    }
    base.update(overrides)
    return base


def test_solve_levels_keeps_signature_levels_verbatim():
    levels = solve_levels(archetype(signature={"HWSEC-SCA-DPA": 5}), ladder_profile_taxonomy())

    assert levels["HWSEC-SCA-DPA"] == 5


def test_solve_levels_omits_never_skills_entirely():
    levels = solve_levels(archetype(never=["HWSEC-FI-CG"]), ladder_profile_taxonomy())

    assert "HWSEC-FI-CG" not in levels


def test_solve_levels_reaches_the_target_rung():
    tax = ladder_profile_taxonomy()
    levels = solve_levels(archetype(), tax)

    junior = tax.profiles["HWSEC"]["maturity_levels"]["junior"]
    assert thresholds_met(junior, levels, tax, "HWSEC") is True


def test_solve_levels_does_not_reach_the_rung_above_the_target():
    tax = ladder_profile_taxonomy()
    levels = solve_levels(archetype(), tax)

    practitioner = tax.profiles["HWSEC"]["maturity_levels"]["practitioner"]
    assert thresholds_met(practitioner, levels, tax, "HWSEC") is False


def test_solve_levels_rejects_a_signature_that_overshoots_the_target_rung():
    overshooting = archetype(
        signature={
            "HWSEC-SCA-DPA": 5,
            "HWSEC-SCA-SPA": 4,
            "HWSEC-FI-VG": 4,
            "FOUND-QA": 3,
        }
    )

    with pytest.raises(UnsatisfiableArchetype, match="practitioner"):
        solve_levels(overshooting, ladder_profile_taxonomy())


def test_solve_levels_rejects_a_target_rung_made_unreachable_by_never():
    unreachable = archetype(
        target_maturity={"HWSEC": "practitioner"},
        never=["HWSEC-SCA-SPA", "HWSEC-SCA-DPA", "HWSEC-FI-VG", "HWSEC-FI-CG"],
    )

    with pytest.raises(UnsatisfiableArchetype, match="domain_skills_at"):
        solve_levels(unreachable, ladder_profile_taxonomy())


# --- Loading the real taxonomy tree -----------------------------------------


def test_load_taxonomy_maps_a_skills_domain_directory_to_its_domain_id():
    tax = load_taxonomy(REPO)

    dpa = tax.skills["HWSEC-SCA-DPA"]
    assert (dpa.domain_id, dpa.category_id) == ("HWSEC", "HWSEC-SCA")


def test_load_taxonomy_carries_prerequisites_and_proficiency_evidence():
    tax = load_taxonomy(REPO)

    dpa = tax.skills["HWSEC-SCA-DPA"]
    assert dpa.requires == ["HWSEC-SCA-SPA"]
    assert dpa.proficiency["3"]["evidence"]


def test_load_taxonomy_loads_every_domain_maturity_ladder():
    tax = load_taxonomy(REPO)

    # Foundations has no ladder; every other domain does.
    assert "FOUND" not in tax.profiles
    assert tax.profiles["HWSEC"]["maturity_levels"]["senior"]["thresholds"]


# --- Project requirements ----------------------------------------------------


def test_resolve_requirements_copies_a_service_template():
    tax = load_taxonomy(REPO)
    services = load_services(REPO)

    reqs = resolve_requirements({"from_service": "SVC-HWSEC-EVAL"}, tax, services)

    assert {r["skill"] for r in reqs} == {
        c["skill"] for c in services["SVC-HWSEC-EVAL"]["required_competencies"]
    }


def test_resolve_requirements_drops_whole_categories_for_a_narrower_scope():
    tax = load_taxonomy(REPO)
    services = load_services(REPO)

    # The PCB-level project is board-level by scope: no chip-invasive work.
    reqs = resolve_requirements(
        {"from_service": "SVC-HWSEC-EVAL", "drop_categories": ["HWSEC-INV", "HWSEC-SPREP"]},
        tax,
        services,
    )

    categories = {tax.skills[r["skill"]].category_id for r in reqs}
    assert "HWSEC-INV" not in categories
    assert "HWSEC-SPREP" not in categories
    assert "HWSEC-PCB" in categories


def test_resolve_requirements_applies_additions_and_level_overrides():
    tax = load_taxonomy(REPO)
    services = load_services(REPO)

    reqs = resolve_requirements(
        {
            "from_service": "SVC-HWSEC-EVAL",
            "add": [{"skill": "SWSEC-RE-STATIC", "minimum_level": 3}],
            "levels": {"HWSEC-PCB-RE": 4},
        },
        tax,
        services,
    )

    by_skill = {r["skill"]: r["minimum_level"] for r in reqs}
    assert by_skill["SWSEC-RE-STATIC"] == 3
    assert by_skill["HWSEC-PCB-RE"] == 4


def test_resolve_requirements_builds_a_hand_listed_project_without_a_service():
    tax = load_taxonomy(REPO)

    reqs = resolve_requirements(
        {"add": [{"skill": "HWSEC-EMBED-BOOT", "minimum_level": 3}]}, tax, {}
    )

    assert reqs == [{"skill": "HWSEC-EMBED-BOOT", "minimum_level": 3}]


# --- Assessment metadata -----------------------------------------------------

TODAY = datetime.date(2026, 10, 14)


def evidence_taxonomy():
    tax = ladder_profile_taxonomy()
    tax.skills["HWSEC-SCA-DPA"].proficiency = {
        "3": {
            "label": "Independent Practice",
            "evidence": ["Recovered full AES keys from unprotected implementations"],
        },
        "4": {
            "label": "Advanced / Mentor",
            "evidence": ["Performs higher-order DPA to defeat masking"],
        },
    }
    return tax


def demo_projects():
    return {
        "PRJ-A": {
            "name": "Alpha Assessment",
            "status": "done",
            "completed_date": "2026-02-13",
            "required_competencies": [{"skill": "HWSEC-SCA-DPA", "minimum_level": 3}],
        },
        "PRJ-B": {
            "name": "Beta Assessment",
            "status": "done",
            "completed_date": "2026-06-05",
            "required_competencies": [{"skill": "HWSEC-SCA-DPA", "minimum_level": 3}],
        },
        "PRJ-C": {
            "name": "Gamma Assessment",
            "status": "planning",
            "completed_date": None,
            "required_competencies": [{"skill": "HWSEC-SCA-DPA", "minimum_level": 3}],
        },
    }


def skill_row(record, skill_id):
    return next(s for s in record["skills"] if s["skill"] == skill_id)


def test_expand_person_cites_every_finished_project_that_required_the_skill():
    arch = archetype(signature={"HWSEC-SCA-DPA": 4}, projects=["PRJ-A", "PRJ-B"])

    record = expand_person(arch, evidence_taxonomy(), demo_projects(), TODAY)

    assert skill_row(record, "HWSEC-SCA-DPA")["evidence_notes"] == (
        "Project: Alpha Assessment\nProject: Beta Assessment"
    )


def test_expand_person_dates_a_project_skill_from_the_latest_completion():
    arch = archetype(signature={"HWSEC-SCA-DPA": 4}, projects=["PRJ-A", "PRJ-B"])

    record = expand_person(arch, evidence_taxonomy(), demo_projects(), TODAY)

    row = skill_row(record, "HWSEC-SCA-DPA")
    assert (row["assessed_date"], row["last_practiced"]) == ("2026-06-05", "2026-06-05")


def test_expand_person_ignores_an_unfinished_project():
    arch = archetype(signature={"HWSEC-SCA-DPA": 4}, projects=["PRJ-C"])

    record = expand_person(arch, evidence_taxonomy(), demo_projects(), TODAY)

    assert "Gamma" not in skill_row(record, "HWSEC-SCA-DPA")["evidence_notes"]


def test_expand_person_takes_non_project_evidence_from_the_taxonomy():
    arch = archetype(signature={"HWSEC-SCA-DPA": 4})

    record = expand_person(arch, evidence_taxonomy(), demo_projects(), TODAY)

    assert skill_row(record, "HWSEC-SCA-DPA")["evidence_notes"] == (
        "Performs higher-order DPA to defeat masking"
    )


def test_expand_person_authorizes_from_level_three_only():
    arch = archetype(signature={"HWSEC-SCA-DPA": 3, "HWSEC-SCA-SPA": 2})

    record = expand_person(arch, evidence_taxonomy(), demo_projects(), TODAY)

    assert skill_row(record, "HWSEC-SCA-DPA")["authorization"]["authorized"] is True
    assert skill_row(record, "HWSEC-SCA-SPA")["authorization"] is None


def test_expand_person_backdates_a_stale_skill_past_the_staleness_threshold():
    arch = archetype(signature={"HWSEC-SCA-DPA": 4}, stale_skills=["HWSEC-SCA-DPA"])

    record = expand_person(arch, evidence_taxonomy(), demo_projects(), TODAY)

    last = datetime.date.fromisoformat(skill_row(record, "HWSEC-SCA-DPA")["last_practiced"])
    assert (TODAY - last).days > 400


# --- Self-assessment modes ---------------------------------------------------


def test_self_assessment_mode_none_produces_no_rows():
    arch = archetype(signature={"HWSEC-SCA-DPA": 3})

    assert expand_self_assessments(arch, evidence_taxonomy(), TODAY) == []


def test_self_assessment_mode_all_offsets_every_held_skill_by_the_bias():
    arch = archetype(signature={"HWSEC-SCA-DPA": 3}, self_assessment={"mode": "all", "bias": 1})
    tax = evidence_taxonomy()

    rows = {r["skill"]: r["level"] for r in expand_self_assessments(arch, tax, TODAY)}
    managed = solve_levels(arch, tax)

    assert rows["HWSEC-SCA-DPA"] == managed["HWSEC-SCA-DPA"] + 1


def test_self_assessment_bias_cannot_push_a_level_outside_the_scale():
    arch = archetype(signature={"HWSEC-SCA-DPA": 5}, self_assessment={"mode": "all", "bias": 2})

    rows = {
        r["skill"]: r["level"] for r in expand_self_assessments(arch, evidence_taxonomy(), TODAY)
    }

    assert rows["HWSEC-SCA-DPA"] == 5


def test_self_assessment_mode_only_leaves_the_person_with_no_managed_skills():
    arch = archetype(signature={"HWSEC-SCA-DPA": 3}, self_assessment={"mode": "only"})
    tax = evidence_taxonomy()

    record = expand_person(arch, tax, demo_projects(), TODAY)

    assert [r for r in record["skills"] if r["level"] > 0] == []
    assert expand_self_assessments(arch, tax, TODAY) != []


def test_self_assessment_mode_seeded_marks_rows_with_the_applications_own_assessor():
    arch = archetype(
        signature={"HWSEC-SCA-DPA": 3},
        self_assessment={"mode": "seeded", "skills": ["HWSEC-SCA-DPA"]},
    )

    record = expand_person(arch, evidence_taxonomy(), demo_projects(), TODAY)

    assert skill_row(record, "HWSEC-SCA-DPA")["assessed_by"] == "self-assessment"
    assert skill_row(record, "HWSEC-FI-CG")["assessed_by"] != "self-assessment"


def test_a_seeded_self_assessment_is_never_authorized():
    # seed_self_assessment creates PersonSkill rows without an authorization
    # record: a self-reported level is not a formal authorization, whatever
    # number it claims.
    arch = archetype(
        signature={"HWSEC-SCA-DPA": 4},
        self_assessment={"mode": "seeded", "skills": ["HWSEC-SCA-DPA"]},
    )

    record = expand_person(arch, evidence_taxonomy(), demo_projects(), TODAY)

    assert skill_row(record, "HWSEC-SCA-DPA")["authorization"] is None


# --- Coverage ----------------------------------------------------------------


def test_coverage_limits_how_many_of_a_domains_skills_a_person_holds_at_all():
    # A junior has not been exposed to every skill in the domain. Holding a
    # record for all of them would be less credible than holding none.
    tax = ladder_profile_taxonomy()

    levels = solve_levels(archetype(coverage=0.5), tax)

    held = [sid for sid in levels if tax.skills[sid].domain_id == "HWSEC"]
    assert len(held) == 2


def test_coverage_keeps_strong_categories_and_drops_weak_ones_first():
    tax = ladder_profile_taxonomy()

    levels = solve_levels(
        archetype(coverage=0.5, bands={"strong": ["HWSEC-SCA"], "weak": ["HWSEC-FI"]}),
        tax,
    )

    held = {sid for sid in levels if tax.skills[sid].domain_id == "HWSEC"}
    assert held == {"HWSEC-SCA-DPA", "HWSEC-SCA-SPA"}


def test_coverage_defaults_by_rung_so_a_lead_is_broader_than_a_junior():
    tax = ladder_profile_taxonomy()

    junior = solve_levels(archetype(target_maturity={"HWSEC": "junior"}), tax)
    practitioner = solve_levels(
        archetype(
            target_maturity={"HWSEC": "practitioner"},
            bands={"strong": ["HWSEC-SCA", "HWSEC-FI"], "weak": []},
        ),
        tax,
    )

    def held(levels):
        return len([s for s in levels if tax.skills[s].domain_id == "HWSEC"])

    assert held(junior) < held(practitioner)


# --- Whole-snapshot expansion ------------------------------------------------


def write_demo_dir(tmp_path):
    (tmp_path / "archetypes").mkdir()
    (tmp_path / "archetypes" / "01-rosa-telles.json").write_text(
        json.dumps(
            {
                "key": "PERS-001",
                "name": "Rosa Telles",
                "role": "AI/ML Security Evaluator",
                "start_date": "2023-05-02",
                "domains": ["AIML"],
                "target_maturity": {"AIML": "junior"},
                "bands": {"strong": [], "weak": []},
                "signature": {},
                "never": [],
                "foundations": [1, 2],
                "projects": ["PRJ-X"],
                "stale_skills": [],
                "self_assessment": {"mode": "none"},
                "development_plan": [],
            }
        )
    )
    (tmp_path / "projects.json").write_text(
        json.dumps(
            [
                {
                    "id": "PRJ-X",
                    "name": "Example Assessment",
                    "description": "An example.",
                    "status": "done",
                    "created_date": "2026-01-05",
                    "completed_date": "2026-03-20",
                    "requirements": {"from_service": "SVC-PENTEST-WEB"},
                }
            ]
        )
    )
    return tmp_path


def test_expand_all_produces_a_snapshot_of_people_and_resolved_projects(tmp_path):
    snapshot = expand_all(REPO, write_demo_dir(tmp_path), TODAY)

    assert [p["id"] for p in snapshot["people"]] == ["PERS-001"]
    assert snapshot["projects"][0]["required_competencies"]


def test_expand_all_is_deterministic(tmp_path):
    demo_dir = write_demo_dir(tmp_path)

    first = expand_all(REPO, demo_dir, TODAY)
    second = expand_all(REPO, demo_dir, TODAY)

    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_expand_all_keeps_a_projects_status_and_completion_date(tmp_path):
    snapshot = expand_all(REPO, write_demo_dir(tmp_path), TODAY)

    project = snapshot["projects"][0]
    assert (project["status"], project["completed_date"]) == ("done", "2026-03-20")


def cross_category_requires_taxonomy():
    """ladder_profile_taxonomy, but fault injection depends on side-channel work."""
    tax = ladder_profile_taxonomy()
    tax.skills["HWSEC-FI-VG"].requires = ["HWSEC-SCA-SPA"]
    return tax


def test_coverage_does_not_drop_a_skill_that_a_kept_skill_requires():
    # Coverage says what a person has been exposed to, not what is physically
    # possible: you cannot glitch a target at L3 with no power-analysis skill.
    tax = cross_category_requires_taxonomy()

    levels = solve_levels(
        archetype(
            coverage=0.5,
            signature={"HWSEC-FI-VG": 3},
            bands={"strong": ["HWSEC-FI"], "weak": ["HWSEC-SCA"]},
        ),
        tax,
    )

    assert "HWSEC-FI-VG" in levels
    assert levels.get("HWSEC-SCA-SPA", 0) >= levels["HWSEC-FI-VG"] - 1


def test_a_never_skill_required_by_a_kept_skill_is_an_authoring_error():
    tax = cross_category_requires_taxonomy()

    with pytest.raises(UnsatisfiableArchetype, match="HWSEC-SCA-SPA"):
        solve_levels(
            archetype(
                target_maturity={"HWSEC": "practitioner"},
                signature={"HWSEC-FI-VG": 3},
                never=["HWSEC-SCA-SPA"],
            ),
            tax,
        )


def test_a_self_assessed_skill_gets_the_level_zero_placeholder_the_import_creates():
    # self_assessment_import creates a PersonSkill at level 0 alongside each
    # SelfAssessment. Without it the person detail table has no row to show,
    # because it iterates PersonSkill and only filters by self-assessed IDs.
    arch = archetype(signature={"HWSEC-SCA-DPA": 3}, self_assessment={"mode": "only"})

    record = expand_person(arch, evidence_taxonomy(), demo_projects(), TODAY)

    placeholder = skill_row(record, "HWSEC-SCA-DPA")
    assert placeholder["level"] == 0
    assert placeholder["assessed_by"] == "self-assessment"
    assert placeholder["authorization"] is None
    assert "last_practiced" not in placeholder


def test_a_placeholder_is_not_created_where_a_managed_assessment_exists():
    arch = archetype(signature={"HWSEC-SCA-DPA": 4}, self_assessment={"mode": "all", "bias": 1})

    record = expand_person(arch, evidence_taxonomy(), demo_projects(), TODAY)

    rows = [r for r in record["skills"] if r["skill"] == "HWSEC-SCA-DPA"]
    assert len(rows) == 1
    assert rows[0]["level"] == 4


# --- Self-assessment realism -------------------------------------------------


def test_jitter_varies_the_offset_per_skill_instead_of_shifting_all_rows_equally():
    # A person who rates every single skill exactly one level above their
    # assessment reads as generated. Real divergence varies skill by skill.
    arch = archetype(
        target_maturity={"HWSEC": "practitioner"},
        self_assessment={"mode": "all", "bias": 0, "jitter": 1},
    )
    tax = ladder_profile_taxonomy()

    managed = solve_levels(arch, tax)
    stated = {r["skill"]: r["level"] for r in expand_self_assessments(arch, tax, TODAY)}
    offsets = {s: stated[s] - managed[s] for s in managed}

    assert set(offsets.values()) != {0}
    assert all(-1 <= o <= 1 for o in offsets.values())


def test_jitter_is_deterministic():
    arch = archetype(
        target_maturity={"HWSEC": "practitioner"},
        self_assessment={"mode": "all", "bias": 0, "jitter": 1},
    )
    tax = ladder_profile_taxonomy()

    first = expand_self_assessments(arch, tax, TODAY)
    second = expand_self_assessments(arch, tax, TODAY)

    assert first == second


def test_without_jitter_the_bias_applies_exactly():
    arch = archetype(
        target_maturity={"HWSEC": "practitioner"}, self_assessment={"mode": "all", "bias": -1}
    )
    tax = ladder_profile_taxonomy()

    managed = solve_levels(arch, tax)
    stated = {r["skill"]: r["level"] for r in expand_self_assessments(arch, tax, TODAY)}

    assert all(stated[s] == max(0, managed[s] - 1) for s in managed)


def test_extra_self_assessments_claim_skills_the_person_does_not_hold():
    # Someone may rate themselves on a skill nobody has assessed. That is the
    # case the "seed from self-assessment" flow exists to resolve.
    arch = archetype(
        target_maturity={"HWSEC": "junior"},
        self_assessment={"mode": "all", "bias": 0, "extra": {"HWSEC-SCA-DPA": 3}},
    )
    tax = ladder_profile_taxonomy()

    managed = solve_levels(arch, tax)
    stated = {r["skill"]: r["level"] for r in expand_self_assessments(arch, tax, TODAY)}
    record = expand_person(arch, tax, demo_projects(), TODAY)

    assert stated["HWSEC-SCA-DPA"] == 3
    assert "HWSEC-SCA-DPA" not in managed
    # ...and it needs the level-0 placeholder, or the table cannot show it.
    assert skill_row(record, "HWSEC-SCA-DPA")["level"] == 0
