"""Reference list: which standards the taxonomy cites, and by how many skills.

`resources/references.json` holds the curated list. Each standard carries
`match` regexes; this module scans the taxonomy (skills, domains, profiles,
_meta.json) with them, then writes `docs/references.md`.
"""

import json
import re
from collections import defaultdict


def load_json(path):
    with open(path) as f:
        return json.load(f)


def taxonomy_texts(root):
    """Yield (record_id, raw_json_text) for every taxonomy and profile file."""
    paths = sorted((root / "taxonomy").rglob("*.json")) + sorted((root / "profiles").glob("*.json"))
    for path in paths:
        text = path.read_text(encoding="utf-8")
        try:
            record_id = json.loads(text).get("id") or path.stem
        except (json.JSONDecodeError, AttributeError):
            continue
        yield record_id, text


def citations(root, standards):
    """Map standard id -> sorted ids of the records that cite it."""
    compiled = {s["id"]: [re.compile(m) for m in s.get("match", [])] for s in standards}
    cited = defaultdict(set)
    for record_id, text in taxonomy_texts(root):
        for sid, patterns in compiled.items():
            if any(p.search(text) for p in patterns):
                cited[sid].add(record_id)
    return {sid: sorted(ids) for sid, ids in cited.items()}


def render_markdown(data, cited):
    lines = [
        "# Reference List",
        "",
        "Standards, frameworks and regulations cited by the skill taxonomy, the domain",
        "maturity profiles and `taxonomy/_meta.json`. Generated from",
        "`resources/references.json` by `python3 tools/cli.py references`; do not edit by hand.",
        "",
        "*Cited by* counts the taxonomy records (skills, domains, profiles) that cite the standard.",
        "",
    ]
    groups = defaultdict(list)
    for s in data["standards"]:
        groups[s["group"]].append(s)
    for group, items in groups.items():
        lines += [f"## {group}", "", "| Reference | Publisher | Cited by |", "| --- | --- | --- |"]
        for s in items:
            title = f"[{s['title']}]({s['url']})" if s.get("url") else s["title"]
            lines.append(f"| {title} | {s['publisher']} | {len(cited.get(s['id'], []))} |")
        lines.append("")
    lines += [
        "## Further resources",
        "",
        "Background material that the taxonomy does not cite directly.",
        "",
    ]
    for r in data.get("resources", []):
        lines.append(
            f"- [{r['title']}]({r['url']}) — {r['relevance']}"
            if r.get("url")
            else f"- {r['title']} — {r['relevance']}"
        )
    return "\n".join(lines) + "\n"


def run_references(root):
    """Write docs/references.md. Returns 1 if a listed standard is cited nowhere."""
    data = load_json(root / "resources" / "references.json")
    cited = citations(root, data["standards"])
    out = root / "docs" / "references.md"
    out.write_text(render_markdown(data, cited), encoding="utf-8")
    print(f"GENERATED: {out}")

    uncited = [s["id"] for s in data["standards"] if not cited.get(s["id"])]
    for sid in uncited:
        print(f"WARNING [references] '{sid}' is listed but no taxonomy record cites it")
    print(f"{len(data['standards'])} standards, {len(uncited)} uncited")
    return 1 if uncited else 0
