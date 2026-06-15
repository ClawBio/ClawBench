"""Summarise the held-out ClinVar slice: counts by cutoff, review status, gene, class, reclassification.

The foundation headline this reports is:
  "We constructed a temporally blinded ClinVar held-out set in which labels post-date model
   cutoffs and are segregated from interpretive evidence."

Pure functions over a manifest dict (no side effects at import).
"""
from __future__ import annotations

import datetime as dt

HEADLINE = ("We constructed a temporally blinded ClinVar held-out set in which labels post-date "
            "model cutoffs and are segregated from interpretive evidence.")


def _inc(d: dict, k):
    d[k] = d.get(k, 0) + 1


def summarise_slice(manifest: dict) -> dict:
    variants = manifest.get("variants", [])
    by_stars: dict = {}
    by_class: dict = {}
    by_gene: dict = {}
    transitions: dict = {}
    labels: list[str] = []

    for v in variants:
        t = v.get("truth", {})
        _inc(by_stars, t.get("review_stars"))
        _inc(by_class, t.get("clnsig"))
        _inc(by_gene, v.get("genomic_context", {}).get("gene", ""))
        lfa = t.get("label_first_available")
        if lfa:
            labels.append(lfa)
        if v.get("reclassified"):
            _inc(transitions, f'{v.get("from_class")} -> {v.get("to_class")}')

    earliest = min(labels) if labels else None
    per_model: dict = {}
    all_after = True
    for model, cutoff in (manifest.get("model_cutoffs") or {}).items():
        entry = {"cutoff": cutoff}
        try:
            cd = dt.date.fromisoformat(cutoff)
            if earliest:
                days = (dt.date.fromisoformat(earliest) - cd).days
                entry["headroom_days_to_earliest_label"] = days
                if days <= 0:
                    all_after = False
        except (ValueError, TypeError):
            entry["headroom_days_to_earliest_label"] = None
            all_after = False
        per_model[model] = entry

    return {
        "headline": HEADLINE,
        "effective_cutoff": manifest.get("effective_cutoff"),
        "min_review_stars": manifest.get("min_review_stars"),
        "safety_margin_days": manifest.get("safety_margin_days"),
        "content_hash": manifest.get("content_hash"),
        "counts": manifest.get("counts", {}),
        "by_review_stars": by_stars,
        "by_class": by_class,
        "by_gene_top": sorted(by_gene.items(), key=lambda kv: (-kv[1], kv[0]))[:25],
        "n_genes": len(by_gene),
        "reclassification": {"n": sum(transitions.values()), "by_transition": transitions},
        "blinding": {
            "earliest_label_first_available": earliest,
            "all_labels_postdate_all_model_cutoffs": all_after,
            "per_model": per_model,
        },
    }


def render_markdown(summary: dict) -> str:
    L: list[str] = []
    L.append("# ClawBench Exp 1 — held-out ClinVar slice")
    L.append("")
    L.append(f"**Foundation:** {summary['headline']}")
    L.append("")
    c = summary["counts"]
    L.append("## Construction")
    L.append(f"- effective cutoff: **{summary['effective_cutoff']}** "
             f"(max model cutoff + {summary['safety_margin_days']}-day safety margin)")
    L.append(f"- minimum review stars: {summary['min_review_stars']}")
    L.append(f"- content hash (immutable manifest): `{summary['content_hash']}`")
    L.append("")
    L.append("## Counts")
    L.append(f"- candidates considered: {c.get('candidates')}")
    L.append(f"- **held out: {c.get('held_out')}**  (reclassified subset: {c.get('reclassified')})")
    L.append("")
    L.append("| excluded reason | n |")
    L.append("|---|---|")
    for reason, n in (c.get("excluded") or {}).items():
        L.append(f"| {reason} | {n} |")
    L.append("")

    L.append("## Blinding headroom (days from each model cutoff to the earliest held-out label)")
    b = summary["blinding"]
    L.append(f"- earliest held-out label first-available: **{b['earliest_label_first_available']}**")
    L.append(f"- all labels post-date all model cutoffs: **{b['all_labels_postdate_all_model_cutoffs']}**")
    L.append("")
    L.append("| model | cutoff | headroom (days) |")
    L.append("|---|---|---|")
    for model, e in b["per_model"].items():
        L.append(f"| {model} | {e.get('cutoff')} | {e.get('headroom_days_to_earliest_label')} |")
    L.append("")

    L.append("## By review stars")
    L.append("| stars | n |")
    L.append("|---|---|")
    for k in sorted(summary["by_review_stars"], key=lambda x: (x is None, x), reverse=True):
        L.append(f"| {k} | {summary['by_review_stars'][k]} |")
    L.append("")

    L.append("## By classification")
    L.append("| class | n |")
    L.append("|---|---|")
    for k, n in sorted(summary["by_class"].items(), key=lambda kv: -kv[1]):
        L.append(f"| {k} | {n} |")
    L.append("")

    L.append(f"## Top genes ({summary['n_genes']} total)")
    L.append("| gene | n |")
    L.append("|---|---|")
    for gene, n in summary["by_gene_top"]:
        L.append(f"| {gene or '(none)'} | {n} |")
    L.append("")

    L.append("## Reclassification transitions")
    r = summary["reclassification"]
    L.append(f"- reclassified held-out variants: **{r['n']}**")
    if r["by_transition"]:
        L.append("")
        L.append("| transition | n |")
        L.append("|---|---|")
        for t, n in sorted(r["by_transition"].items(), key=lambda kv: -kv[1]):
            L.append(f"| {t} | {n} |")
    L.append("")
    return "\n".join(L)
