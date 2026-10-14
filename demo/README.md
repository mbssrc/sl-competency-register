# Demo mode

A complete, populated instance of the personnel tool, for showing what it does
with realistic data in it. Everything here is fictional.

## Run it

```sh
nix develop          # or have Django and Node available some other way
./demo/demo.sh
```

Then open <http://127.0.0.1:8000/> and sign in:

| Role | Username | Password |
|------|----------|----------|
| Admin | `admin` | `admin` |
| Manager | `manager` | `manager` |
| User | `user` | `user` |

From a fresh clone, `nix run .#demo` does the same thing without needing a dev
shell first.

The script creates its database in `.demo-run/`, which it deletes and rebuilds
on every start, so the demo is identical each time and the real database in
`web/` is never touched. It also rebuilds the stylesheet and static assets every
time, so an edit to `web/static/src/` — the Tailwind input or the background
image — shows up on the next start without any extra step.

Options: `--port N`, `--keep` (don't rebuild the database, to show that an edit
survives a restart), `--no-css` (skip the asset build), `--no-serve`.

Start with the manager account. The admin account exists to show user
management and the admin tools; `user` shows how little a regular user sees —
it is linked to Lucia Rossi, the new hire.

## A walkthrough

1. **Dashboard.** Headcount, assessment total, open projects and taxonomy
   size, then the recent projects with their coverage. It names nobody.
2. **Reports → Gap Analysis.** Each person's rung on their domain's maturity
   ladder, and what the next rung needs. Note how many practitioners are held
   back by `FOUND-QA` — the senior rung of every domain pins it at level 3.
3. **Projects → SATCOM Handset — Crypto-Processor Invasive Attack Assessment.**
   Nine of the twelve requirements have exactly one qualified person, and
   `HWSEC-INV-FIB` at level 4 has nobody. This engagement rests on one person.
4. **Personnel → Tomas Lindqvist.** The succession plan for that risk: he holds
   the invasive skills at level 2 with a development plan toward level 3. His
   RF skills show a `last_practiced` date over a year old.
5. **Reports → Service Readiness.** Eight of seventeen service lines cannot be
   staffed, because the lab has no digital forensics, adversarial simulation,
   intelligence or ICS people at all.
6. **Projects → the two Android assessments.** The finished messaging app
   assessment and the planned provisioning app assessment both need
   `SWSEC-MOB-ANDROID` at level 3, and only Dmitri Volkov has it.
7. **Projects → MedGrant AI.** The AI/ML requirements resolve to one person,
   and `AIML-ADV-PRIVACY` at level 4 to nobody — a hire-or-train decision.
8. **Personnel → Lucia Rossi.** The new hire: 31 self-assessed skills and not
   one management assessment, so every row sits at level 0 with her own claim
   beside it. Use the Managed / Self-Assessed / Show All toggles, then
   "Seed from Self-Assessment" to promote her claims into assessable levels.
   Five other people have a smaller version of the same thing — a skill they
   have rated themselves on that nobody has assessed.
9. **Personnel → Amara Okonkwo → Edit on `HWSEC-SCA-DPA`.** The evidence field
   cites the engagements the level was assessed on, one `Project:` line per
   engagement, exactly as the project completion flow writes them. That trail
   is the competence evidence. Note that the skill table does not show this
   field — it is visible in the edit modal and in the personnel Excel export
   (Export → Personnel, "Skill Details" sheet, "Evidence Notes" column), where a reviewer
   would read it across the whole lab.
10. **Projects → SATCOM Handset — Operating System Assessment.** Mark it done
    and work through the assessment matrix to watch new `Project:` evidence
    lines get written onto people's skills.

## What the data deliberately shows

| Finding | How | Where it shows |
|---------|-----|----------------|
| Key-person risk | The invasive analysis skills have exactly one holder at level 3+ | `PRJ-SAT-CP-INV` coverage; Service Readiness |
| Capacity contention | One person holds Android at level 4; nobody else is above 2 | The two Android projects resolve to the same name |
| Capability hole | AI/ML security is one practitioner deep | `PRJ-MEDGRANT-WEB` has an uncovered requirement |
| Progression bottleneck | `FOUND-QA` at level 3 is pinned by every domain's senior rung | Gap Analysis names it for several strong practitioners |
| Service lines with no people | Nobody works in forensics, adversarial simulation, intelligence or ICS | Service Readiness: 8 of 17 not fully staffable |
| Self-reported vs. assessed | 18 of 20 people have self-assessed, diverging up and down per skill | The delta column on every person's page |

The six finished projects are all fully staffable, because a project you could
not staff is not a project you could have finished. The four planned ones carry
the problems above.

## Self-assessments

18 of the 20 people have returned a self-assessment; 738 rows in all. Two have
not, which is itself a thing a manager wants to see.

The divergence varies per skill rather than shifting a whole person's rows by a
fixed amount, so the delta column shows someone being confident in places and
unsure in others. Beatriz Carvalho and Hannes Müller rate themselves below their
assessments, Yusuf Demirci and Kwame Mensah above.

Four people claim a skill nobody has assessed — Priya Raghunathan on
microprobing, Tomas Lindqvist on optical sample preparation, Kwame Mensah on SIM
and GSM work, Nadia Haddad on post-quantum agility. Those rows carry the level-0
`PersonSkill` placeholder that `self_assessment_import` creates, which is what
makes a self-assessed skill appear in the table at all; the self-reported number
shows beside a managed level of zero. Six people have something a manager can
promote with "Seed from Self-Assessment".

Self-reported levels never count towards maturity, gap analysis, service
readiness or project coverage — the application ignores them until a manager
ratifies one. A claim on an unassessed skill therefore does not make anyone look
qualified for work they cannot do.

## The data itself

| Path | What it is |
|------|------------|
| `archetypes/*.json` | Twenty people, hand-authored as *intent*: domains, target ladder rung, strong and weak categories, exact levels for signature skills, project history |
| `projects.json` | Ten projects, with requirements taken from service templates and then narrowed or widened to each project's scope |
| `accounts.json` | The three logins |
| `generated/population.json` | The full literal expansion, committed |

Each archetype's `self_assessment` block says how that person rates themselves:
`mode` (`none`, `all`, `only` or `seeded`), a `bias` for the central offset,
`jitter` to spread it per skill, and `extra` for claims on skills they hold no
assessment for.

An archetype says what a person *is*; the solver works out the numbers. To make
someone read as "Senior Hardware Security Evaluator", the gap analysis needs 16
HWSEC skills at level 3+, 7 at level 4+, four categories covered, a Foundations
average of 1.5 and three pinned Foundations skills. Nobody should have to count
that by hand for twenty people across twelve domains, so `expand.py` does the
counting, and refuses with a specific message when an archetype asks for
something impossible.

After editing an archetype:

```sh
python3 demo/expand.py     # regenerate the snapshot
python3 demo/validate.py   # check it before seeding
git diff demo/generated/   # review what changed
```

The snapshot is committed so the demo is exactly what the repository says, and
`validate.py` fails if it is stale. The solver has no randomness in it: the same
archetypes always produce the same snapshot.

| Script | Needs Django | Job |
|--------|--------------|-----|
| `expand.py` | no | Archetypes → snapshot |
| `validate.py` | no | Snapshot freshness, schema, references, prerequisites, evidence markers |
| `seed.py` | yes | Snapshot → database |
| `verify.py` | yes | Checks the seeded result with the application's own calculations |

`verify.py` matters most. `expand.py` approximates the maturity ladders from
JSON; `verify.py` then checks what the pages will actually show, using the real
`compute_domain_maturity`. If the two ever disagree, the archetype is wrong.

## Tests

```sh
python3 -m pytest demo/tests/
```

## Caveats

- The names, people, projects and clients are invented. Any resemblance to real
  engagements is coincidental.
- The passwords are the usernames. `demo.sh` serves on 127.0.0.1 only, which is
  what makes that acceptable; never run this demo on an interface others can
  reach, and never reuse these credentials anywhere else. The application's own
  password validators would reject all three — `seed.py` writes them straight
  through `set_password`, which does not validate.
- The scenario's "today" is fixed at 2026-10-14, so dates do not drift as real
  time passes.
