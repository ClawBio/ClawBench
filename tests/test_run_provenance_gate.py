"""TDD for the CI runner that blocks bad-citation skill PRs (ClawBio/ClawBench#3, L1 enforcement).

The runner walks changed skills, and for any skill that declares the `emits_effect_sizes`
capability it requires + validates a provenance panel against the gate. A skill that declares
the capability but ships a fabricated citation (or no panel at all) fails the check; a skill
that does not emit effect sizes is skipped. Uses the committed GWAS Catalog/PubMed snapshot,
so it is offline and deterministic.
"""
from __future__ import annotations

import json

import run_provenance_gate as G

# A real catalogued tuple from the committed snapshot (rs7903146 / T2D / EUR / Repin 2010).
GOOD_ENTRY = {"variant": {"rsid": "rs7903146"},
              "trait": {"label": "type 2 diabetes", "efo_id": "MONDO_0005148"},
              "ancestry": "EUR", "effect": {"measure": "OR", "value": 1.4},
              "source": {"pmid": "20581827"}}
# The flagship fabricated citation: head-and-neck-cancer survey cited as APOL1.
BAD_ENTRY = {"variant": {"rsid": "rs73885319"},
             "trait": {"label": "chronic kidney disease", "efo_id": "MONDO_0005300"},
             "ancestry": "AFR", "effect": {"measure": "OR", "value": 1.89},
             "source": {"pmid": "20566908"}}

SKILL_MD_EFFECTS = """---
name: {name}
metadata:
  capabilities:
    - emits_effect_sizes
---
# {name}
"""
SKILL_MD_PLAIN = """---
name: {name}
metadata:
  capabilities: []
---
# {name}
"""


def _make_skill(root, name, skill_md, panel=None):
    d = root / "skills" / name
    (d / "data").mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(skill_md.format(name=name))
    if panel is not None:
        (d / "data" / "provenance.json").write_text(json.dumps(panel))
    return d


def test_declares_effect_sizes_detects_capability(tmp_path):
    good = _make_skill(tmp_path, "a", SKILL_MD_EFFECTS, [GOOD_ENTRY])
    plain = _make_skill(tmp_path, "b", SKILL_MD_PLAIN, None)
    assert G.declares_effect_sizes(good) is True
    assert G.declares_effect_sizes(plain) is False


def test_good_panel_passes(tmp_path):
    d = _make_skill(tmp_path, "good", SKILL_MD_EFFECTS, [GOOD_ENTRY])
    res = G.gate_skill(d)
    assert res["status"] == "pass", res


def test_fabricated_citation_fails(tmp_path):
    d = _make_skill(tmp_path, "bad", SKILL_MD_EFFECTS, [BAD_ENTRY])
    res = G.gate_skill(d)
    assert res["status"] == "fail"
    codes = [f["error_code"] for f in res["findings"]]
    assert "PMID_STUDY_MISMATCH" in codes


def test_capability_without_panel_is_error(tmp_path):
    d = _make_skill(tmp_path, "nopanel", SKILL_MD_EFFECTS, panel=None)
    res = G.gate_skill(d)
    assert res["status"] == "error"
    assert res["findings"][0]["error_code"] == "MISSING_PROVENANCE"


def test_non_emitting_skill_is_skipped(tmp_path):
    d = _make_skill(tmp_path, "plain", SKILL_MD_PLAIN, None)
    res = G.gate_skill(d)
    assert res["status"] == "skipped"


def test_run_blocks_when_any_skill_fails(tmp_path):
    _make_skill(tmp_path, "good", SKILL_MD_EFFECTS, [GOOD_ENTRY])
    _make_skill(tmp_path, "bad", SKILL_MD_EFFECTS, [BAD_ENTRY])
    _make_skill(tmp_path, "plain", SKILL_MD_PLAIN, None)
    report = G.run(tmp_path / "skills")
    assert report["blocking"] >= 1
    assert report["exit_code"] == 1
    statuses = {r["skill"]: r["status"] for r in report["results"]}
    assert statuses["good"] == "pass"
    assert statuses["bad"] == "fail"
    assert statuses["plain"] == "skipped"


def test_run_passes_when_all_clean(tmp_path):
    _make_skill(tmp_path, "good", SKILL_MD_EFFECTS, [GOOD_ENTRY])
    _make_skill(tmp_path, "plain", SKILL_MD_PLAIN, None)
    report = G.run(tmp_path / "skills")
    assert report["blocking"] == 0
    assert report["exit_code"] == 0


def test_changed_filter_restricts_scope(tmp_path):
    _make_skill(tmp_path, "good", SKILL_MD_EFFECTS, [GOOD_ENTRY])
    _make_skill(tmp_path, "bad", SKILL_MD_EFFECTS, [BAD_ENTRY])
    # Only the good skill changed in this PR: the bad skill must not be evaluated.
    report = G.run(tmp_path / "skills", changed=["skills/good/data/provenance.json"])
    assert report["exit_code"] == 0
    assert {r["skill"] for r in report["results"]} == {"good"}
