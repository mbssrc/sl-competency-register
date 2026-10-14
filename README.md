# SecLab Competence Register (DRAFT-VERSION)

Personnel competency management for a security laboratory.

> **Note** This is a draft version. Almost exclusively AI-generated.

A web-based personnel competency management system for a security laboratory. Tracks personnel skills, manages competency assessments, and provides gap analysis against role profiles and project requirements.

Built for a full-spectrum security lab with 12 skill domains spanning adversarial simulation, digital forensics, hardware security, cryptography,  and more. The taxonomy is aligned with ISO 17025 principles.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Django 5.2, Python 3 |
| Database | SQLite (dual-database: taxonomy + personnel) |
| Frontend | HTMX, Alpine.js, Tailwind CSS 3.4 |
| Static files | WhiteNoise (compressed manifest in production) |
| Auth | Argon2 password hashing, django-axes brute-force protection |
| Excel | openpyxl (export/import) |
| Deployment | Gunicorn, NixOS (flake-based) |

## Architecture

### Dual-Database Design

The system uses two separate SQLite databases:

- **`taxonomy.sqlite3`** — Reference data: domains, skills, profiles, services, and metadata. This data is authored as JSON files in the repo and seeded into the database via a management command. It can be version-controlled and shared across environments.
- **`personnel.sqlite3`** — Runtime data: people, skill assessments, self-assessments, development plans, projects, and user accounts.

A custom database router (`apps/core/db_router.py`) directs reads and writes to the correct database based on app label. Cross-database references use `CharField` IDs instead of foreign keys, since Django does not support cross-database FK constraints.

### App Structure

```
web/
├── config/              # Django settings, URLs, WSGI
├── apps/
│   ├── core/            # Dashboard, admin tools, export, middleware, DB router
│   │   └── management/commands/
│   │       ├── seed_taxonomy.py      # Load JSON → taxonomy DB
│   │       ├── export_taxonomy.py    # Dump taxonomy DB → JSON
│   │       └── check_integrity.py    # Validate cross-DB references
│   ├── taxonomy/        # Domain, Skill, Profile, Service models + views
│   ├── personnel/       # Person, PersonSkill, Project, SelfAssessment + views
│   └── accounts/        # Custom User model, login, role-based access
├── templates/           # Base templates
└── static/
    ├── src/             # Tailwind input CSS, background image
    ├── dist/            # Compiled CSS output
    └── vendor/          # Vendored JS (htmx.min.js, alpine.min.js)
```

### Role System

Three roles, each a superset of the one below. The `@role_required(minimum_role)`
decorator in `apps/accounts/decorators.py` enforces the threshold; `owner_or_role`
additionally lets a person act on their own record.

| Role | Access |
|------|--------|
| **User** | Their own personnel record and skill assessments; the project list and project detail; the full taxonomy. Exports and imports their own self-assessment workbook. Sees no other person's name or level anywhere. |
| **Manager** | Everything a User sees, for everyone — plus all personnel and assessment editing, full control of projects, taxonomy editing and reordering, the gap analysis and service readiness reports, and the Excel exports. |
| **Admin** | Everything a Manager can do, plus user management, the admin tools (seed, export, integrity check), and deleting personnel records. |

Superusers are forced to `admin` on save.

Two boundaries are deliberate. Deleting a person is admin-only because it cascades to
every assessment, self-assessment and development plan for that person. Promoting a
self-assessment into an official `PersonSkill` level is manager-only, because that is
the step that makes a self-reported number authoritative for gap analysis and service
readiness — a person may state their own view of their competence, but not ratify it.

The dashboard is a third boundary, and a softer one: it reports headcount,
assessment totals, open projects and taxonomy size, plus the most recent projects
and their coverage, but it names no personnel for any role. It is the one page
that gets read over a shoulder, so the roster lives on the Personnel page where
opening it is a deliberate act.

An account is linked to a Person record from the Users page. That link is what
`owner_or_role` checks, so a User with no linked Person sees only projects and the
taxonomy, and the dashboard tells them to ask an administrator.

Upgrading from an earlier version promotes nobody: migration `0003_simplify_roles`
discarded the old `privileged` assignments, so an admin assigns the Manager role by
hand from the Users page.

## Features

### Personnel Management
- Add, edit, and manage personnel records
- Track skill assessments with proficiency levels (0–5: None → Authority)
- Record assessed date, assessor, evidence notes, authorization, and last practiced date
- Person detail view groups skills by domain with filter toggles (Managed / Self-Assessed / Show All)

### Self-Assessment
- Export per-person Excel workbook with dropdown level selectors and proficiency descriptions
- Import completed self-assessment workbooks — creates `SelfAssessment` records
- Self-assessed levels are advisory and displayed alongside official management levels
- Delta indicator shows divergence between management and self-assessed levels

### Taxonomy Browser
- Browse domains, skills, profiles, and services
- Drag-and-drop reordering for domains, profiles, and services
- Edit skills with full field editor (proficiency levels, assessment methods, equipment, framework mappings, tags)

### Project Planner
- Create projects as skill-requirement templates
- Initialize from Service templates (copies required competencies)
- Add/remove individual skill requirements with minimum level
- Per-project gap analysis showing org-wide qualified personnel
- Automatic skill assessment on project completion (planning → done → archived)

### Reports
- **Gap Analysis** — compare personnel skills against assigned profile requirements. Domain maturity counts only management-assessed levels (self-assessments are ignored); a category counts towards breadth once a skill in it is held at level 2+; the Foundations average runs over every active Foundations skill, with unassessed ones counting as 0
- **Service Readiness** — check staffing coverage for each service's required competencies
- **Excel Export** — taxonomy, personnel, and report workbooks

### Admin Tools
- Seed taxonomy from JSON files
- Export taxonomy back to JSON
- Integrity check (validates cross-DB references, DAG integrity)
- User management (create, edit, activate/deactivate)

### Other
- Health check endpoint (`/health/`)
- Audit logging middleware (logs every successful mutation app-wide, personnel reads, and all 403s with the request method)
- Modal overlay system for all create/edit forms
- Dark glassmorphism UI theme

## Demo

A committed, fictional example population — 20 people and 10 projects — that turns the empty
tool into a self-explaining one. No checkout required:

```sh
nix run github:<owner>/<repo>#demo   # any machine with Nix
nix run .#demo                       # from a clone
./demo/demo.sh                       # in a dev shell
```

That builds the stylesheet, creates a throwaway database in `.demo-run/`, seeds the taxonomy and
the demo population, verifies the result and serves it at <http://127.0.0.1:8000/> with three
logins printed on the way. Your own database in `web/` is never opened, and the scratch
directory is rebuilt on every start. Run without a checkout and it unpacks itself into
`~/.cache/personnel-demo/` first; it needs no Node and no network, because the stylesheet comes
from the `personnel-web` package. `nix flake check` runs the whole spin-up headlessly.

The demo is self-contained in [`demo/`](demo/README.md), which has the walkthrough and explains
what the data deliberately shows — a single point of failure in invasive analysis, two projects
competing for one mobile specialist, a capability hole in AI/ML, and the Foundations skill that
gates several people's next ladder rung. The application itself is not modified and cannot tell
it is running a demo.

## Getting Started

### Prerequisites

**Option A — Nix (recommended):**

```sh
nix develop
```

`nix develop` provides Python with all web dependencies plus Node.js.

**Option B — Manual:**

```sh
pip install django django-htmx django-axes whitenoise argon2-cffi openpyxl gunicorn
npm install    # in web/ directory, for Tailwind
```

### Setup

```sh
cd web
export DJANGO_DEBUG=true   # local development; see Configuration

# 1. Run migrations (both databases)
python manage.py migrate
python manage.py migrate taxonomy --database taxonomy

# 2. Seed taxonomy data from JSON files
python manage.py seed_taxonomy

# 3. Build Tailwind CSS
npm run build

# 4. Create a superuser
python manage.py createsuperuser

# 5. Run the dev server
python manage.py runserver
```

The app will be available at `http://localhost:8000/`.

### Tailwind Watch Mode

During development, run Tailwind in watch mode to auto-rebuild on template changes:

```sh
npm run watch:css
```

## Project Structure

```
personnel/
├── taxonomy/                # Skill domain JSON files (git-managed)
│   ├── _meta.json           # Version, proficiency model, domain definitions
│   ├── foundations/          # One directory per domain
│   ├── hardware-security/
│   ├── ...
│   └── wireless-signal-security/
├── profiles/                # Per-domain maturity ladders (e.g., hardware-security.json)
├── services/                # Service definition JSON files (e.g., svc-pentest-web.json)
├── mappings/                # Framework mapping data
├── schema/                  # JSON schemas for validation
├── resources/               # Reference list of cited standards (references.json; rendered to docs/references.md)
├── demo/                    # Demo mode: example population, solver and launcher
│   ├── demo.sh              # One-command spin-up (see demo/README.md)
│   ├── expand.py            # Archetypes -> committed population snapshot
│   ├── archetypes/          # 20 hand-authored people, as intent not numbers
│   └── generated/           # The expanded snapshot, committed
├── tools/                   # CLI tools (validate, export, import, gap analysis)
│   ├── cli.py               # Main CLI entry point
│   ├── validate.py          # Schema + cross-reference validation
│   ├── excel_export.py      # Standalone Excel export
│   ├── excel_import.py      # Excel → JSON import
│   ├── gap_analysis.py      # CLI gap analysis
│   └── references.py        # Renders docs/references.md (python3 tools/cli.py references)
├── web/                     # Django web application
│   ├── config/              # Settings, URLs, WSGI
│   ├── apps/                # Django apps (core, taxonomy, personnel, accounts)
│   ├── templates/           # Base templates
│   ├── static/              # CSS, JS, images
│   └── manage.py
├── nix/                     # Web package, NixOS module and VM test
├── flake.nix                # Nix flake (dev shell, CLI + web packages, NixOS module)
└── docs/                    # Presentation deck and the generated references list
```

## Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `DJANGO_SECRET_KEY` | *(none)* | Secret key for cryptographic signing. **Required** when `DJANGO_DEBUG` is false — the app refuses to start without it. With debug on, an insecure dev key is used. |
| `DJANGO_SECRET_KEY_FILE` | *(none)* | File to read the secret key from when `DJANGO_SECRET_KEY` is unset. The NixOS module uses this with a systemd credential. |
| `DJANGO_DEBUG` | `false` | Set to `true` for local development (enables the dev key and plain-HTTP cookies). |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated list of allowed hostnames. |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | *(empty)* | Comma-separated scheme+host origins, e.g. `https://lab.example.internal`. |
| `PERSONNEL_DATA_DIR` | `web/` | Directory for SQLite database files. Set this to persist data outside the project tree. |
| `PERSONNEL_TAXONOMY_DIR` | repo root | Directory holding `taxonomy/`, `profiles/`, `services/`. Required when the app is installed outside a source checkout. |
| `PERSONNEL_TRUSTED_PROXY_COUNT` | `0` | Number of trusted reverse proxies in front of the app. Set to `1` behind nginx so client IPs, lockout and audit logs are correct. |

The timezone is set to `Asia/Dubai` (UTC+4).

## Deployment (NixOS)

The flake exports `packages.personnel-web` (app, built CSS, collected static files, taxonomy JSON) and `nixosModules.default`, which provides `services.personnel`:

```nix
{
  imports = [ inputs.personnel.nixosModules.default ];

  services.personnel = {
    enable = true;
    domain = "personnel.internal";
    nginx = {
      enable = true;
      openFirewall = true;
      sslCertificate = "/var/lib/personnel-tls/cert.pem";
      sslCertificateKey = "/var/lib/personnel-tls/key.pem";
    };
    fail2ban.enable = true;
    backup.enable = true;
  };
}
```

After the first deploy, create an admin as root: `personnel-manage createsuperuser`. The module's options are documented inline in [`nix/module.nix`](nix/module.nix); `nix build .#checks.x86_64-linux.integration-test` runs the VM test.

## Maintenance

### Seeding Taxonomy Data

When taxonomy JSON files are updated, re-seed the database:

```sh
python manage.py seed_taxonomy
```

This is also available as a button in the Admin Tools page (admin role required).

Seeding runs in a single transaction, so a malformed file leaves the database unchanged. A plain `seed_taxonomy` only adds and updates; deletions in the JSON tree need `--prune` to take effect:

```sh
# Re-seed, and delete database rows whose JSON file was removed from the repo
python manage.py seed_taxonomy --prune
```

### Exporting Taxonomy

To dump the taxonomy database back to JSON files (e.g., after edits in the web UI):

```sh
python manage.py export_taxonomy
```

This writes `taxonomy/`, `profiles/` and `services/` into `PERSONNEL_TAXONOMY_DIR` (the repo root by default) — the same layout `seed_taxonomy` reads — so the JSON source of truth is updated in place and the diff can be reviewed with git. Pass a directory to export elsewhere, e.g. `python manage.py export_taxonomy ../taxonomy-export`. `seed_taxonomy --source <dir>` loads from such a directory.

### Integrity Check

Validates that all cross-database references are consistent (e.g., personnel skill IDs match taxonomy, profile competencies reference valid skills):

```sh
python manage.py check_integrity
```

### Excel Export

Four export workbooks are available. Three are on the Export page:

- **Taxonomy** — all domains, skills, profiles, and services
- **Personnel** — all personnel with skill assessments, grouped by domain
- **Reports** — gap analysis and service readiness data

The fourth, the **Gap Analysis** workbook, is exported from the Gap Analysis page.

### Self-Assessment Workflow

1. Export a self-assessment workbook for a person (from their detail page)
2. The person fills in proficiency levels using dropdown selectors in Excel
3. Import the completed workbook back — creates `SelfAssessment` records
4. Self-assessed levels appear alongside management levels in the person detail view

### User Management

Managed from the Users page (admin role required). Link each account to its Person record: that link is what lets a User see their own record and self-assessment, and nothing else. The last active admin cannot be deactivated or demoted.

## Key Design Decisions

**Two databases, not one.** The taxonomy is reference data that should be versioned in git as JSON. The personnel database is runtime data that changes per-environment. Keeping them separate means you can seed a fresh environment from the repo without touching personnel records.

**CharField for cross-DB references.** Django doesn't support foreign keys across databases. `PersonSkill.skill_id` is a `CharField` that stores the taxonomy skill ID, not a FK. The `check_integrity` command validates these references.

**JSON fields for structured data.** Profile competencies, service requirements, project requirements, and skill proficiency definitions are stored as JSON fields. This avoids join-heavy schemas for data that is always read as a unit.

**Palette derived from the presentation deck.** `web/tailwind.config.js` replaces
Tailwind's `gray`, `indigo`, `amber`, `emerald` and `red` ramps with ramps built from
the lab deck's `slate` theme (`docs/presentation-deck.html`), so the app and the deck
read as one family. The ramps are anchored on the deck's own tokens at the steps the
markup already uses and interpolated in Oklab in between; `gray-500` and `indigo-400`
are pinned by hand to hold 4.5:1. Nothing bespoke appears in the templates, which is
why ~2,600 existing colour utilities recoloured without being touched. `white` is
deliberately *not* warmed to the deck's card tone: that pair fails against
`bg-indigo-500` in dark-mode buttons.

**Vendored JavaScript.** HTMX and Alpine.js are vendored in `static/vendor/` rather than loaded from a CDN. The deployment environment is air-gapped.

**Fetch-based modals, not HTMX.** The modal overlay system uses `fetch()` with `credentials: 'same-origin'` rather than HTMX attributes. This was chosen after HTMX's `afterSwap` event proved unreliable for backdrop/z-index management.

**Argon2 password hashing.** The primary password hasher is Argon2 (via `argon2-cffi`), with PBKDF2 as fallback. Combined with django-axes for brute-force protection (5 attempts, 30-minute cooloff).

**Audit middleware.** Every successful POST/PUT/PATCH/DELETE by an authenticated user is logged as `CHANGE`, anywhere in the app — the taxonomy is a controlled document, so its edits are traceable too. Successful `GET`s under `/personnel` are logged as `ACCESS`, and every 403 as `FORBIDDEN` with its method. Client IPs come from `client_ip()`, which honours `PERSONNEL_TRUSTED_PROXY_COUNT`. Logs go to the `personnel.audit` logger.

**Singleton pattern for TaxonomyMeta.** `TaxonomyMeta` uses `pk=1` with an overridden `save()` to ensure exactly one row. This stores taxonomy version, proficiency model, domain definitions, and custom ordering for profiles/services.
