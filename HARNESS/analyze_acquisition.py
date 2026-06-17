"""Analyse the acquisition arm: per-variant layer attribution, thin->enriched transitions, verdict.

Primary endpoint (per the experiment design): the change in per-variant layer attribution between
Condition A (thin: consequence+AF) and Condition B (enriched: oracle non-ClinVar evidence). The
question the whole arm answers: does allowing an agent to acquire additional evidence shrink the
evidence_insufficient layer, i.e. is acquisition a real architectural layer or a subset of the
sufficiency/assignment layers already characterised?

Also reports, because they explain any null:
  * realised vs theoretical CEILING: the best points-class achievable from PM2 (moderate) + the
    calibrated PP3/BP4 the oracle supplied, so a null can be attributed to the structural non-ClinVar
    evidence ceiling and/or the model's conservative strength assignment (PM2 at supporting);
  * PM2 / PP3 / BP4 strength distributions and strength_basis supply, the assignment-layer behaviour.

Run: python3 HARNESS/analyze_acquisition.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "HARNESS"))
import acmg_points as AP  # noqa: E402
import attribution as A  # noqa: E402

VUS = "Uncertain Significance"
_DEFINITIVE = {"Pathogenic", "Likely Pathogenic", "Likely Benign", "Benign"}


def attribution_category(att: dict) -> str:
    """Collapse attribute_one flags to one ordered layer category per (variant, arm)."""
    f = att["flags"]
    truth = att["truth"]
    if not f.get("safety_clean", True):
        return "dangerous"
    if truth == VUS:
        return "vus_correct" if att.get("points_class") == VUS else "vus_overcall"
    if f.get("evidence_insufficient"):
        return "evidence_insufficient"
    if f.get("combiner_sensitive"):
        return "combiner_sensitive"
    if f.get("assignment_unstable"):
        return "assignment_unstable"
    return "resolved"


def transition_matrix(pairs) -> Counter:
    return Counter(pairs)


def resolution_rate(pairs) -> dict:
    """Of definitive variants that were evidence_insufficient under thin, the fraction that left
    that layer under enriched (the headline acquisition effect)."""
    thin_ei = [(a, b) for a, b in pairs if a == "evidence_insufficient"]
    resolved = [(a, b) for a, b in thin_ei if b != "evidence_insufficient"]
    n = len(thin_ei)
    return {"n_thin_ei": n, "n_resolved": len(resolved), "rate": (len(resolved) / n if n else 0.0)}


# ---- ceiling + strength helpers -------------------------------------------------
def ceiling_points_class(enriched_evidence_context: dict) -> str:
    """Best points-class an IDEAL (non-conservative, non-contradictory) agent could reach from the
    oracle's non-ClinVar evidence. Direction-aware:
      * pathogenic in-silico (PP3): PM2 at its moderate baseline (rare) + the calibrated PP3;
      * benign in-silico (BP4):     the calibrated BP4 alone (PM2 would contradict a benign signal);
      * indeterminate:              PM2 moderate alone (rare) -> stays VUS.
    This is the upper bound on what acquisition can do; the gap to the realised count is the model's
    strength-assignment conservatism (it applies PM2 at supporting, not moderate)."""
    ev = enriched_evidence_context or {}
    rec = (ev.get("in_silico") or {}).get("revel_acmg")
    af = ev.get("population_max_af")
    rare = af in (None, "") or (isinstance(af, (int, float)) and af < 1e-4)
    codes = []
    if rec and rec["code"] == "PP3":
        codes.append({"code": "PP3", "strength": rec["strength"]})
        if rare:
            codes.append({"code": "PM2", "strength": "moderate"})
    elif rec and rec["code"] == "BP4":
        codes.append({"code": "BP4", "strength": rec["strength"]})
    elif rare:
        codes.append({"code": "PM2", "strength": "moderate"})
    return AP.classify_codes(codes)[0]


def _attribute_arm(records_by_variant_arm, arm, meta):
    out = {}
    for (vid, a), recs in records_by_variant_arm.items():
        if a != arm:
            continue
        att = A.attribute_one(recs)
        att["variant_id"] = vid
        att["consequence"] = meta.get(vid, {}).get("consequence")
        out[vid] = att
    return out


def main() -> None:
    rows = [json.loads(l) for l in (_ROOT / "RESULTS/acquisition_probe_runs.jsonl").read_text().splitlines() if l.strip()]
    probe = json.loads((_ROOT / "TRUTH/clinvar/acquisition_probe_v1.json").read_text())
    cache = {v["variant_id"]: v for v in json.loads((_ROOT / "TRUTH/clinvar/acquisition_cache_v1.json").read_text())["variants"]}
    meta = {v["variant_id"]: {"truth": v["truth"]["clnsig"], "tier": v.get("tier")} for v in probe["variants"]}

    by_va = defaultdict(list)
    for r in rows:
        by_va[(r["variant_id"], r["arm"])].append(r)

    thin_att = _attribute_arm(by_va, "thin", meta)
    enr_att = _attribute_arm(by_va, "enriched", meta)
    cal_att = _attribute_arm(by_va, "calibrated", meta)
    has_cal = bool(cal_att)

    # per-variant comparison
    variants = [v["variant_id"] for v in probe["variants"]]
    rows_out = []
    pairs_def = []  # definitive only
    for vid in variants:
        truth = meta[vid]["truth"]
        ta, ea = thin_att.get(vid), enr_att.get(vid)
        if not ta or not ea:
            continue
        tc, ec = attribution_category(ta), attribution_category(ea)
        ceil = ceiling_points_class(cache[vid]["evidence_context"])
        row = {"variant_id": vid, "truth": truth, "thin_cat": tc, "enr_cat": ec,
               "thin_points": ta.get("points_class"), "enr_points": ea.get("points_class"),
               "ceiling_points": ceil,
               "revel_acmg": (cache[vid]["evidence_context"].get("in_silico") or {}).get("revel_acmg")}
        ca = cal_att.get(vid)
        if ca:
            row["cal_cat"] = attribution_category(ca)
            row["cal_points"] = ca.get("points_class")
        rows_out.append(row)
        if truth in _DEFINITIVE:
            pairs_def.append((tc, ec))

    tm = transition_matrix(pairs_def)
    res = resolution_rate(pairs_def)

    # strength behaviour (enriched arm): PM2 strength, PP3 strength, basis supply
    def strength_dist(arm, code):
        c = Counter()
        for r in rows:
            if r["arm"] != arm:
                continue
            for pc in r.get("proposed_codes", []):
                if pc.get("code") == code:
                    c[pc.get("strength")] += 1
        return dict(c)

    # ceiling vs realised on definitive variants
    n_def = sum(1 for v in rows_out if v["truth"] in _DEFINITIVE)
    ceil_resolvable = sum(1 for v in rows_out if v["truth"] in _DEFINITIVE and v["ceiling_points"] != VUS)
    enr_resolved = sum(1 for v in rows_out if v["truth"] in _DEFINITIVE and v["enr_cat"] != "evidence_insufficient")
    thin_resolved = sum(1 for v in rows_out if v["truth"] in _DEFINITIVE and v["thin_cat"] != "evidence_insufficient")

    cal_block = None
    if has_cal:
        cal_rows = [v for v in rows_out if v["truth"] in _DEFINITIVE and "cal_cat" in v]
        cal_ei = sum(1 for v in cal_rows if v["cal_cat"] == "evidence_insufficient")
        recovered = [v["variant_id"] for v in cal_rows
                     if v["enr_cat"] == "evidence_insufficient" and v["cal_cat"] != "evidence_insufficient"]
        regressed = [v["variant_id"] for v in cal_rows
                     if v["enr_cat"] != "evidence_insufficient" and v["cal_cat"] == "evidence_insufficient"]
        enr_to_cal = transition_matrix([(v["enr_cat"], v["cal_cat"]) for v in cal_rows])
        # VUS-control overcalling under calibration (should stay vus_correct)
        vus_overcall = [v["variant_id"] for v in rows_out
                        if v["truth"] == VUS and v.get("cal_cat") == "vus_overcall"]
        cal_block = {
            "calibrated_evidence_insufficient": cal_ei,
            "n_definitive": len(cal_rows),
            "recovered_vs_enriched": recovered,
            "regressed_vs_enriched": regressed,
            "vus_controls_overcalled": vus_overcall,
            "pm2_strength_calibrated": None,  # filled below
            "enriched_to_calibrated": {f"{a} -> {b}": n for (a, b), n in sorted(enr_to_cal.items(), key=lambda x: -x[1])},
        }

    summary = {
        "model": probe["selection_model"],
        "n_variants": len(rows_out),
        "n_definitive": n_def,
        "primary_endpoint": {
            "thin_evidence_insufficient": n_def - thin_resolved,
            "enriched_evidence_insufficient": n_def - enr_resolved,
            "resolution_rate_of_thin_ei": res,
        },
        "ceiling": {
            "definitive_resolvable_at_ceiling": ceil_resolvable,
            "definitive_resolved_realised_enriched": enr_resolved,
            "note": ("ceiling assumes PM2 moderate + the oracle's calibrated PP3/BP4; the realised "
                     "count is what the model actually reached. Gap = assignment conservatism."),
        },
        "transitions_definitive": {f"{a} -> {b}": n for (a, b), n in sorted(tm.items(), key=lambda x: -x[1])},
        "pm2_strength_enriched": strength_dist("enriched", "PM2"),
        "pp3_strength_enriched": strength_dist("enriched", "PP3"),
        "bp4_strength_enriched": strength_dist("enriched", "BP4"),
        "per_variant": rows_out,
    }
    if cal_block is not None:
        cal_block["pm2_strength_calibrated"] = strength_dist("calibrated", "PM2")
        summary["calibration_arm"] = cal_block
    out_json = _ROOT / "RESULTS/exp1_acquisition_analysis.json"
    out_json.write_text(json.dumps(summary, indent=2))

    summary["_n_definitive_total"] = n_def
    md = _render_markdown(summary, tm, by_truth=_resolution_by_truth(rows_out))
    (_ROOT / "RESULTS/exp1_acquisition.md").write_text(md)
    print(md)
    print(f"\nwrote {out_json.relative_to(_ROOT)} + RESULTS/exp1_acquisition.md")


def _resolution_by_truth(rows_out):
    by = defaultdict(lambda: {"n": 0, "thin_ei": 0, "enr_ei": 0})
    for v in rows_out:
        if v["truth"] not in _DEFINITIVE:
            continue
        b = by[v["truth"]]
        b["n"] += 1
        b["thin_ei"] += 1 if v["thin_cat"] == "evidence_insufficient" else 0
        b["enr_ei"] += 1 if v["enr_cat"] == "evidence_insufficient" else 0
    return by


def _render_markdown(s, tm, by_truth):
    p = s["primary_endpoint"]
    L = ["# ClawBench Exp 1 — Acquisition arm (oracle, single model)", "",
         f"Model: **{s['model']}**. {s['n_variants']} rare missense (Tier-B), {s['n_definitive']} definitive "
         "+ VUS controls. Condition A = consequence+AF; Condition B = oracle non-ClinVar evidence "
         "(VEP/REVEL/AlphaMissense/CADD; calibrated PP3/BP4 per Pejaver 2022). Same frozen truth, "
         "same scorer, same attribution. 5 replicates/arm.", "",
         "## Primary endpoint: evidence_insufficient (definitive variants)",
         f"- Condition A (thin):     {p['thin_evidence_insufficient']}/{s['n_definitive']} evidence_insufficient",
         f"- Condition B (enriched): {p['enriched_evidence_insufficient']}/{s['n_definitive']} evidence_insufficient",
         f"- Resolution of thin-ei variants: {p['resolution_rate_of_thin_ei']['n_resolved']}/"
         f"{p['resolution_rate_of_thin_ei']['n_thin_ei']} ({100*p['resolution_rate_of_thin_ei']['rate']:.0f}%)", "",
         "## Ceiling vs realised (definitive)",
         f"- Resolvable at theoretical ceiling (PM2 moderate + calibrated PP3/BP4): "
         f"{s['ceiling']['definitive_resolvable_at_ceiling']}/{s['n_definitive']}",
         f"- Actually resolved by the model (enriched): {s['ceiling']['definitive_resolved_realised_enriched']}/{s['n_definitive']}",
         "", "## thin -> enriched transitions (definitive)"]
    for k, v in s["transitions_definitive"].items():
        L.append(f"- {k}: {v}")
    L += ["", "## evidence_insufficient by truth class (thin -> enriched)",
          "| truth | n | thin ei | enriched ei |", "|---|---|---|---|"]
    for t in ("Pathogenic", "Likely Pathogenic", "Likely Benign", "Benign"):
        if t in by_truth:
            b = by_truth[t]
            L.append(f"| {t} | {b['n']} | {b['thin_ei']} | {b['enr_ei']} |")
    L += ["", "## Assignment-layer behaviour (enriched arm, code strengths)",
          f"- PM2: {s['pm2_strength_enriched']}",
          f"- PP3: {s['pp3_strength_enriched']}",
          f"- BP4: {s['bp4_strength_enriched']}"]
    cal = s.get("calibration_arm")
    if cal:
        nd = s.get("_n_definitive_total", cal["n_definitive"])
        L += ["", "## Strength-calibration arm (PM2 licensed at moderate per the 2015 combiner)",
              f"- PM2 strength shifted: enriched {s['pm2_strength_enriched']} -> calibrated {cal['pm2_strength_calibrated']}",
              f"- evidence_insufficient (definitive): enriched {p['enriched_evidence_insufficient']}/{nd} "
              f"-> calibrated {cal['calibrated_evidence_insufficient']}/{nd}",
              f"- recovered vs enriched ({len(cal['recovered_vs_enriched'])}): {cal['recovered_vs_enriched']}",
              f"- regressed vs enriched ({len(cal['regressed_vs_enriched'])}): {cal['regressed_vs_enriched']}",
              f"- VUS controls overcalled: {cal['vus_controls_overcalled'] or 'none'}",
              "", "### enriched -> calibrated transitions (definitive)"]
        for k, v in cal["enriched_to_calibrated"].items():
            L.append(f"- {k}: {v}")
    return "\n".join(L)


if __name__ == "__main__":
    main()
