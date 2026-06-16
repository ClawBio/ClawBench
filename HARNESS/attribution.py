"""Per-variant layer attribution: convert model performance into WHERE apparent errors originate.

For each (variant, model) in skill_execution, attribute the residual uncertainty to architectural
layers using the model's replicate code submissions, the Richards rule combiner (predicted_class in
the record), and the Tavtigian points combiner (acmg_points):
- safety_clean         : no dangerous Pathogenic<->Benign miscall across replicates
- combiner_sensitive   : the modal class differs between the rule and points combiners
- assignment_unstable  : the proposed code SETS differ across replicates
- evidence_insufficient: truth is definitive but even the points combiner yields VUS

NOTE: this measures safety, assignment, sufficiency, and combiner-threshold. It does NOT measure
evidence ACQUISITION (the pilot provided the evidence); acquisition is a separate, untested layer.
No side effects at import.
"""
from __future__ import annotations

from collections import Counter, defaultdict

import acmg_points as AP
import acmg_vocabulary as voc

ACTIONABLE = {"Pathogenic", "Likely Pathogenic"}
BENIGN = {"Benign", "Likely Benign"}
VUS = "Uncertain Significance"


def _mode(xs):
    return Counter(xs).most_common(1)[0][0] if xs else None


def _kept(codes):
    return [c for c in codes if isinstance(c, dict) and c.get("code") not in voc.ASSERTION_CODES]


def attribute_one(records: list[dict]) -> dict:
    """Attribute one (variant, model) from its skill_execution replicates."""
    sc = [r for r in records if r.get("scoreable")]
    truth = records[0].get("truth_class")
    rule_classes = [r.get("predicted_class") for r in sc]
    points_classes, code_sets = [], []
    for r in sc:
        kept = _kept(r.get("proposed_codes", []) or [])
        points_classes.append(AP.classify_codes(kept)[0])
        code_sets.append(frozenset(c.get("code") for c in kept if c.get("code")))

    rule_modal = _mode(rule_classes)
    points_modal = _mode(points_classes)
    dangerous = any((rc in ACTIONABLE and truth in BENIGN) or (rc in BENIGN and truth in ACTIONABLE)
                    for rc in rule_classes)
    flags = {
        "safety_clean": not dangerous,
        "dangerous": dangerous,
        "combiner_sensitive": (rule_modal is not None and points_modal is not None
                               and rule_modal != points_modal),
        "assignment_unstable": len(set(code_sets)) > 1,
        "evidence_insufficient": (truth != VUS and points_modal == VUS),
    }
    return {"truth": truth, "rule_class": rule_modal, "points_class": points_modal,
            "n_reps": len(sc), "flags": flags}


def attribute(records: list[dict], variant_meta: dict | None = None) -> list[dict]:
    by: dict = defaultdict(list)
    for r in records:
        if r.get("condition") == "skill_execution":
            by[(r["variant_id"], r["model"])].append(r)
    out = []
    for (vid, model), recs in by.items():
        a = attribute_one(recs)
        a["variant_id"], a["model"] = vid, model
        if variant_meta and vid in variant_meta:
            a["tier"] = variant_meta[vid].get("tier")
            a["consequence"] = variant_meta[vid].get("consequence")
        out.append(a)
    return out


def breadth(attributions: list[dict], group_key: str, flag: str) -> dict:
    g: dict = defaultdict(lambda: [0, 0])
    for a in attributions:
        k = a.get(group_key)
        g[k][1] += 1
        g[k][0] += 1 if a["flags"].get(flag) else 0
    return {k: (n, tot, n / tot if tot else 0.0) for k, (n, tot) in g.items()}
