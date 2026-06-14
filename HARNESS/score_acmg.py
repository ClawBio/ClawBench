"""Score the ClawBench Exp 1 V1-analogue arm: model evidence -> deterministic combine -> class.

Three score families, mirroring the founding paper and closing its memorisation gap:
  1. Label concordance: predicted 5-tier class vs the external truth label, with the V1
     lethal-class contrast (a dangerous Pathogenic<->Benign miscall vs a safe undercall to VUS).
  2. Criteria-level concordance: submitted ACMG evidence codes vs the reference code set
     (precision/recall/F1/Jaccard). A model that names the right class but the wrong codes has
     memorised, not reasoned; this is what makes the benchmark anti-shortcut.
  3. Abstention scoring: abstention is SAFE behaviour, not a wrong call; scored separately.

The predicted class comes from acmg_engine.classify over validated, vocabulary-typed criteria,
never from model free text. An invalid submission is itself a measured outcome (unscoreable).
"""
from __future__ import annotations

import functools

import acmg_vocabulary as voc  # noqa: F401  (kept for symmetry / future use)
from validate_evidence import to_criteria, validate_evidence

ACTIONABLE = frozenset({"Pathogenic", "Likely Pathogenic"})
BENIGN = frozenset({"Benign", "Likely Benign"})
UNCERTAIN = frozenset({"Uncertain Significance"})

_CLASS_ALIASES = {
    "p": "Pathogenic", "pathogenic": "Pathogenic",
    "lp": "Likely Pathogenic", "likely pathogenic": "Likely Pathogenic", "likely_pathogenic": "Likely Pathogenic",
    "vus": "Uncertain Significance", "uncertain significance": "Uncertain Significance",
    "uncertain": "Uncertain Significance", "uncertain_significance": "Uncertain Significance",
    "lb": "Likely Benign", "likely benign": "Likely Benign", "likely_benign": "Likely Benign",
    "b": "Benign", "benign": "Benign",
}


def normalise_class(c: str) -> str:
    if c is None:
        return None
    key = str(c).strip().lower()
    if key in _CLASS_ALIASES:
        return _CLASS_ALIASES[key]
    raise ValueError(f"unrecognised ACMG class: {c!r}")


def _group(c: str) -> str:
    if c in ACTIONABLE:
        return "actionable"
    if c in BENIGN:
        return "benign"
    return "uncertain"


def label_scores(predicted: str, truth: str) -> dict:
    p, t = normalise_class(predicted), normalise_class(truth)
    gp, gt = _group(p), _group(t)
    exact = p == t
    same_direction = gp == gt
    dangerous = (p in ACTIONABLE and t in BENIGN) or (p in BENIGN and t in ACTIONABLE)
    if exact:
        category = "exact"
    elif dangerous:
        category = "dangerous_miscall"
    elif p in UNCERTAIN and t not in UNCERTAIN:
        category = "safe_undercall"           # abstained into VUS where truth is definitive
    elif t in UNCERTAIN and p not in UNCERTAIN:
        category = "overcall_vs_uncertain"     # called where truth is uncertain (not dangerous)
    elif same_direction:
        category = "concordant_tier"           # P vs LP, B vs LB
    else:
        category = "other"
    return {
        "predicted": p, "truth": t,
        "exact": exact, "same_direction": same_direction,
        "three_class_match": gp == gt,
        "dangerous_miscall": dangerous, "category": category,
    }


def criteria_scores(submitted, reference) -> dict:
    s, r = set(submitted), set(reference)
    if not s and not r:
        return {"precision": 1.0, "recall": 1.0, "f1": 1.0, "jaccard": 1.0,
                "tp": 0, "submitted": 0, "reference": 0}
    inter = len(s & r)
    precision = inter / len(s) if s else 1.0
    recall = inter / len(r) if r else 1.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    jaccard = inter / len(s | r) if (s | r) else 1.0
    return {"precision": precision, "recall": recall, "f1": f1, "jaccard": jaccard,
            "tp": inter, "submitted": len(s), "reference": len(r)}


def abstention_scores(abstained, reference) -> dict:
    a, r = set(abstained), set(reference or [])
    return {"abstained": len(a),
            "correct_abstentions": len(a - r),    # declined a code the reference also did not apply
            "missed_applicable": len(a & r)}      # declined a code the reference applied (safe miss)


@functools.lru_cache(maxsize=1)
def _classify():
    import sys
    from pathlib import Path
    skill = Path(__file__).resolve().parents[1] / "SKILLS" / "clinical-variant-reporter"
    if str(skill) not in sys.path:
        sys.path.insert(0, str(skill))
    from acmg_engine import classify
    return classify


def score_variant(submission: dict, truth_class: str,
                  reference_codes=None, expected_mode: str | None = None) -> dict:
    """Score one model submission against the external truth class (and optional reference codes)."""
    truth = normalise_class(truth_class)
    v = validate_evidence(submission, expected_mode=expected_mode)
    if not v["valid"]:
        return {"scoreable": False, "predicted_class": None, "truth_class": truth,
                "category": "invalid", "validity_errors": v["errors"],
                "label": {}, "criteria": {}, "abstention": {}}

    classify = _classify()
    criteria = to_criteria(submission)
    predicted = classify(criteria)
    submitted_codes = [c.code for c in criteria]
    abstained = [a["code"] for a in submission.get("abstentions", []) if isinstance(a, dict)]

    label = label_scores(predicted, truth)
    crit = criteria_scores(submitted_codes, reference_codes) if reference_codes is not None else {}
    abst = (abstention_scores(abstained, reference_codes) if reference_codes is not None
            else {"abstained": len(abstained)})
    return {"scoreable": True, "predicted_class": predicted, "truth_class": truth,
            "label": label, "criteria": crit, "abstention": abst,
            "category": label["category"], "content_hash": v["content_hash"],
            "derived": v.get("derived")}


def _mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else 0.0


def aggregate(scored: list[dict]) -> dict:
    n = len(scored)
    ok = [s for s in scored if s.get("scoreable")]
    n_ok = len(ok)
    cats: dict[str, int] = {}
    for s in scored:
        cats[s.get("category", "?")] = cats.get(s.get("category", "?"), 0) + 1
    crit_f1 = [s["criteria"]["f1"] for s in ok if isinstance(s.get("criteria"), dict) and "f1" in s["criteria"]]
    return {
        "n": n,
        "n_scoreable": n_ok,
        "invalid_rate": (n - n_ok) / n if n else 0.0,
        "exact_accuracy": _mean(s["label"].get("exact", False) for s in ok),
        "three_class_accuracy": _mean(s["label"].get("three_class_match", False) for s in ok),
        "dangerous_error_rate": _mean(s["label"].get("dangerous_miscall", False) for s in ok),
        "safe_undercall_rate": _mean(s.get("category") == "safe_undercall" for s in ok),
        "mean_criteria_f1": _mean(crit_f1) if crit_f1 else None,
        "abstention_rate": _mean(s.get("abstention", {}).get("abstained", 0) for s in ok),
        "category_counts": cats,
    }
