"""Pathogenic end-to-end attribution (execution-light), per the scope decision.

GIAB genomes are healthy, so the call-and-interpret overlap was benign-only (integration finding).
To exercise the framework on PATHOGENIC cases without re-calling from FASTQ, this module:
  1. selects pathogenic / likely-pathogenic held-out variants,
  2. uses their REAL Exp1 skill_execution interpretation attribution (via attribution.attribute),
  3. overlays a CONTROLLED calling outcome -- default TP (the qualified control arm calls GIAB truth
     at ~0.99, so correct calling is the expected outcome), with optional injected FN / genotype-
     mismatch to demonstrate the cross-layer end-to-end labels,
  4. joins via integrate_workflow.

The calling overlay is a labelled positive control demonstrating the joint attribution, NOT a
measurement of caller performance on pathogenic variants (that would need spiked re-calling, which is
out of the execution-light scope). No import-time IO.
"""
from __future__ import annotations

import attribution as AT
import integrate_workflow as IW

PATHOGENIC = {"Pathogenic", "Likely Pathogenic"}


def pathogenic_variant_ids(tier_a_records: list[dict]) -> set:
    return {r["variant_id"] for r in tier_a_records if r.get("clnsig") in PATHOGENIC}


def calling_overlay(variant_ids, *, fn_ids=(), gt_mismatch_ids=()) -> dict:
    """Controlled calling outcome per variant: TP (correct call) by default; FN for fn_ids; TP with a
    wrong genotype for gt_mismatch_ids (to exercise genotype_propagation)."""
    fn, gm = set(fn_ids), set(gt_mismatch_ids)
    out = {}
    for v in variant_ids:
        if v in fn:
            out[v] = {"vcfeval": "FN"}
        elif v in gm:
            out[v] = {"vcfeval": "TP", "gt_match": False}
        else:
            out[v] = {"vcfeval": "TP", "gt_match": True}
    return out


def attributions_from_records(interp_records: list[dict], variant_meta=None) -> dict:
    """Real interpretation attribution keyed by variant_id (attribution.attribute filters to the
    skill_execution condition and computes the per-variant flags)."""
    return {a["variant_id"]: a for a in AT.attribute(interp_records, variant_meta)}


def pathogenic_integration(tier_a_records: list[dict], interp_records: list[dict], *,
                           fn_ids=(), gt_mismatch_ids=(), variant_meta=None) -> dict:
    """End-to-end attribution restricted to pathogenic/LP variants, with a controlled calling overlay."""
    pids = pathogenic_variant_ids(tier_a_records)
    interp = attributions_from_records(
        [r for r in interp_records if r.get("variant_id") in pids], variant_meta)
    calling = calling_overlay(pids, fn_ids=fn_ids, gt_mismatch_ids=gt_mismatch_ids)
    # only variants we actually have interpretation for (or that failed calling) enter the join
    overlap = [v for v in pids if v in interp or v in set(fn_ids)]
    return IW.join_workflow(calling, interp, overlap_keys=overlap)
