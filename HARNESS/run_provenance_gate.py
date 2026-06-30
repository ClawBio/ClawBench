"""CI runner: block skill PRs whose effect-size citations do not hold up (ClawBio/ClawBench#3).

For each (changed) skill that declares the `emits_effect_sizes` capability in its SKILL.md
frontmatter, this requires a provenance panel (`data/provenance.json`) and validates every
entry with the provenance gate (HARNESS/validate_provenance.py) against the committed GWAS
Catalog/PubMed snapshot. A fabricated citation, or a missing panel, fails the check; skills
that do not emit effect sizes are skipped. Emits GitHub Actions annotations and a step
summary, and exits non-zero when anything blocks.

Convention: a skill opts in with
    metadata:
      capabilities:
        - emits_effect_sizes
and ships skills/<name>/data/provenance.json conforming to SCHEMAS/effect_size_provenance_schema.json.

No side effects at import. Run via .github/workflows/provenance-gate.yml in the skills repo.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import validate_provenance as VP

CAPABILITY = "emits_effect_sizes"
PROVENANCE_REL = Path("data") / "provenance.json"


def _frontmatter(text: str) -> str:
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    return m.group(1) if m else ""


def declares_effect_sizes(skill_dir: Path) -> bool:
    skill_md = Path(skill_dir) / "SKILL.md"
    if not skill_md.exists():
        return False
    return CAPABILITY in _frontmatter(skill_md.read_text())


def gate_skill(skill_dir, oracle: VP.Oracle | None = None) -> dict:
    skill_dir = Path(skill_dir)
    name = skill_dir.name
    if not declares_effect_sizes(skill_dir):
        return {"skill": name, "status": "skipped", "findings": []}

    panel_path = skill_dir / PROVENANCE_REL
    if not panel_path.exists():
        return {"skill": name, "status": "error", "panel": str(panel_path),
                "findings": [{"error_code": "MISSING_PROVENANCE", "severity": "block",
                              "message": f"{name} declares {CAPABILITY} but has no "
                                         f"{PROVENANCE_REL} provenance panel", "index": None,
                              "file": str(panel_path)}]}
    oracle = oracle or VP.CachedOracle()
    try:
        entries = json.loads(panel_path.read_text())
    except Exception as exc:
        return {"skill": name, "status": "error", "panel": str(panel_path),
                "findings": [{"error_code": "PARSE_ERROR", "severity": "block",
                              "message": f"could not parse {panel_path}: {exc}", "index": None,
                              "file": str(panel_path)}]}

    report = VP.validate_panel(entries, oracle)
    for f in report["findings"]:
        f["file"] = str(panel_path)
    status = "fail" if report["n_blocking"] else ("warn" if report["n_warnings"] else "pass")
    return {"skill": name, "status": status, "panel": str(panel_path),
            "findings": report["findings"]}


def _changed_skill_names(changed) -> set[str]:
    names = set()
    for p in changed or []:
        parts = Path(p).parts
        if "skills" in parts:
            i = parts.index("skills")
            if i + 1 < len(parts):
                names.add(parts[i + 1])
    return names


def discover_skills(skills_root, changed=None) -> list[Path]:
    skills_root = Path(skills_root)
    skills = [d for d in sorted(skills_root.iterdir()) if (d / "SKILL.md").exists()]
    if changed is not None:
        wanted = _changed_skill_names(changed)
        skills = [d for d in skills if d.name in wanted]
    return skills


def run(skills_root, changed=None, oracle: VP.Oracle | None = None) -> dict:
    oracle = oracle or VP.CachedOracle()
    results = [gate_skill(d, oracle) for d in discover_skills(skills_root, changed)]
    blocking = sum(1 for r in results if r["status"] in ("fail", "error"))
    return {"results": results, "blocking": blocking, "exit_code": 1 if blocking else 0}


def _emit_annotations(report: dict) -> None:
    for r in report["results"]:
        for f in r.get("findings", []):
            level = "error" if f.get("severity") == "block" else "warning"
            print(f"::{level} file={f.get('file', '')}::[{r['skill']}] "
                  f"{f.get('error_code')}: {f.get('message')}")


def _write_summary(report: dict) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    icon = {"pass": "✅", "warn": "🟡", "fail": "🔴", "error": "🔴", "skipped": "➖"}
    lines = ["## Provenance gate", "", "| Skill | Status | Blocking | Warnings |", "|---|---|---|---|"]
    for r in report["results"]:
        nb = sum(1 for f in r.get("findings", []) if f.get("severity") == "block")
        nw = sum(1 for f in r.get("findings", []) if f.get("severity") == "warn")
        lines.append(f"| {r['skill']} | {icon.get(r['status'], '')} {r['status']} | {nb} | {nw} |")
    with open(path, "a") as fh:
        fh.write("\n".join(lines) + "\n")


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Block skill PRs with unsupported effect-size citations.")
    ap.add_argument("--skills-root", default="skills", help="directory containing skill folders")
    ap.add_argument("--changed", default=None,
                    help="newline/comma-separated changed paths; if omitted, scan all skills")
    args = ap.parse_args(argv)

    changed = None
    if args.changed:
        changed = [p.strip() for p in re.split(r"[\n,]", args.changed) if p.strip()]

    report = run(args.skills_root, changed)
    _emit_annotations(report)
    _write_summary(report)
    for r in report["results"]:
        print(f"{r['status']:>8}  {r['skill']}")
    print(f"\n{report['blocking']} skill(s) blocking; exit {report['exit_code']}")
    return report["exit_code"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
