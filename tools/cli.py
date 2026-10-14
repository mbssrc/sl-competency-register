#!/usr/bin/env python3
"""Security Lab Skill Database CLI.

Usage:
    python tools/cli.py validate [--no-warnings]
    python tools/cli.py scaffold skill --id ID --name NAME --domain DOMAIN --category CATEGORY
    python tools/cli.py scaffold profile --id ID --name NAME
    python tools/cli.py scaffold service --id ID --name NAME
    python tools/cli.py generate-indexes
    python tools/cli.py export taxonomy|personnel|reports|all
    python tools/cli.py import <file.xlsx> [--dry-run]
    python tools/cli.py gap-analysis gaps|readiness|summary
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(
        prog="cli.py",
        description="Security Lab Skill Database CLI",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # validate
    val = sub.add_parser("validate", help="Validate all JSON files")
    val.add_argument(
        "--no-warnings", action="store_true", help="Suppress warnings, show only errors"
    )

    # scaffold
    scaf = sub.add_parser("scaffold", help="Generate skeleton JSON files")
    scaf_sub = scaf.add_subparsers(dest="type", required=True)

    skill_p = scaf_sub.add_parser("skill", help="Scaffold a skill file")
    skill_p.add_argument("--id", required=True, help="Skill ID (e.g., HWSEC-FI-LASER)")
    skill_p.add_argument("--name", required=True, help="Skill name")
    skill_p.add_argument("--domain", required=True, help="Domain directory name")
    skill_p.add_argument("--category", required=True, help="Category directory name")
    skill_p.add_argument("--batch", help="Batch file with id|name pairs, one per line")

    prof_p = scaf_sub.add_parser("profile", help="Scaffold a profile file")
    prof_p.add_argument("--id", required=True, help="Profile ID (e.g., PROF-HWSEC-EVAL)")
    prof_p.add_argument("--name", required=True, help="Profile name")

    svc_p = scaf_sub.add_parser("service", help="Scaffold a service file")
    svc_p.add_argument("--id", required=True, help="Service ID (e.g., SVC-HWSEC-EVAL)")
    svc_p.add_argument("--name", required=True, help="Service name")

    # generate-indexes
    sub.add_parser("generate-indexes", help="Generate reverse-index mappings")

    # references
    sub.add_parser("references", help="Generate docs/references.md from resources/references.json")

    # export
    exp = sub.add_parser("export", help="Export to Excel")
    exp.add_argument(
        "type", choices=["taxonomy", "personnel", "reports", "all"], help="What to export"
    )

    # import
    imp = sub.add_parser("import", help="Import personnel data from Excel")
    imp.add_argument("file", help="Path to personnel-export.xlsx")
    imp.add_argument("--dry-run", action="store_true", help="Show changes without writing")

    # gap-analysis
    gap = sub.add_parser("gap-analysis", help="Gap analysis and service readiness")
    gap.add_argument("type", choices=["gaps", "readiness", "summary"], help="Analysis type")

    args = parser.parse_args()

    if args.command == "validate":
        from validate import run_validate

        sys.exit(run_validate(ROOT, warnings=not args.no_warnings))
    elif args.command == "scaffold":
        from scaffold import run_scaffold

        run_scaffold(ROOT, args)
    elif args.command == "generate-indexes":
        from indexes import run_generate_indexes

        run_generate_indexes(ROOT)
    elif args.command == "references":
        from references import run_references

        sys.exit(run_references(ROOT))
    elif args.command == "export":
        from excel_export import run_export

        run_export(ROOT, args)
    elif args.command == "import":
        from excel_import import run_import

        run_import(ROOT, args)
    elif args.command == "gap-analysis":
        from gap_analysis import run_gap_analysis

        run_gap_analysis(ROOT, args)


if __name__ == "__main__":
    main()
