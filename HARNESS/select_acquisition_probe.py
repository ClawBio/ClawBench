"""Select + freeze the acquisition-arm probe set (Exp 1, acquisition layer).

The acquisition arm asks: if an agent is allowed to retrieve additional NON-CLINVAR evidence
(VEP consequence detail, calibrated in-silico predictors, gnomAD frequency, domain context), does
the per-variant attribution profile change, i.e. does the `evidence_insufficient` layer shrink?

This selector freezes the variant set the experiment runs on:
  * rare missense (Tier-B), where the pilot showed evidence-insufficiency dominates (~72%);
  * enriched for variants already flagged `evidence_insufficient` under thin (consequence+AF) evidence
    for the model under test, so the baseline reliably exhibits the layer we want to move;
  * balanced across the definitive classes (P / LP / LB / B);
  * plus a few VUS negative controls, which acquisition should NOT move out of VUS.

Genomic coordinates + gene are recovered by joining onto the held-out manifest (the Tier-B probe
file carries only variant_id/consequence/max_af/clnsig). Selection is deterministic (no randomness):
ei-preferred, then variant_id-sorted. No side effects at import; run main() to write the frozen set.

Run: python3 HARNESS/select_acquisition_probe.py
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]

VUS = "Uncertain Significance"
DEFINITIVE = ("Pathogenic", "Likely Pathogenic", "Likely Benign", "Benign")


def join_genomic_context(probe_variants: list[dict], manifest_by_id: dict) -> list[dict]:
    """Build full runner-ready variant dicts by joining the thin Tier-B probe rows onto the
    held-out manifest (authoritative genomic_context + truth). Raise KeyError naming any probe
    variant absent from the manifest (a frozen-truth integrity failure, never silently dropped)."""
    missing = [p["variant_id"] for p in probe_variants if p["variant_id"] not in manifest_by_id]
    if missing:
        raise KeyError(f"probe variants absent from held-out manifest: {missing}")
    out = []
    for p in probe_variants:
        m = manifest_by_id[p["variant_id"]]
        out.append({
            "variant_id": p["variant_id"],
            "genomic_context": dict(m["genomic_context"]),
            "evidence_context": {"molecular_consequence": p.get("consequence"),
                                 "population_max_af": p.get("max_af")},
            "truth": {"clnsig": m["truth"]["clnsig"], "review_stars": m["truth"].get("review_stars")},
            "tier": p.get("tier", "B"),
        })
    return out


def ei_variants_for_model(attribution_records: list[dict], model: str) -> set:
    """variant_ids flagged evidence_insufficient for the given model under thin evidence."""
    return {a["variant_id"] for a in attribution_records
            if a.get("model") == model and a.get("flags", {}).get("evidence_insufficient")}


def select_probe(joined: list[dict], ei_ids: set, *, per_class: int = 6, vus_controls: int = 3,
                 definitive: tuple = DEFINITIVE) -> list[dict]:
    """Deterministically pick up to `per_class` variants per definitive class (ei-preferred,
    then variant_id-sorted) plus `vus_controls` VUS negative controls. Stable ordering."""
    def clnsig(v):
        return v["truth"]["clnsig"]

    selected = []
    for cls in definitive:
        pool = [v for v in joined if clnsig(v) == cls]
        pool.sort(key=lambda v: (0 if v["variant_id"] in ei_ids else 1, v["variant_id"]))
        selected.extend(pool[:per_class])
    vus_pool = sorted((v for v in joined if clnsig(v) == VUS), key=lambda v: v["variant_id"])
    selected.extend(vus_pool[:vus_controls])
    return selected


def freeze(selected: list[dict], *, model: str) -> dict:
    """Wrap the selection with a content hash + provenance so the probe set is immutable and
    reproducible, mirroring the held-out slice's freeze discipline."""
    variants = sorted(selected, key=lambda v: v["variant_id"])
    canonical = json.dumps(variants, sort_keys=True, separators=(",", ":"))
    content_hash = hashlib.sha256(canonical.encode()).hexdigest()
    counts = {"selected": len(variants)}
    for cls in DEFINITIVE + (VUS,):
        counts[cls] = sum(1 for v in variants if v["truth"]["clnsig"] == cls)
    return {
        "schema_version": 1,
        "name": "acquisition_probe_v1",
        "principle": ("Same frozen truth, same scoring, same attribution as the pilot; the ONLY "
                      "manipulated factor is the non-ClinVar evidence the model is given."),
        "selection_model": model,
        "selection_rule": ("rare missense (Tier-B), ei-enriched for the selection_model under thin "
                           "evidence, balanced across definitive classes, plus VUS controls"),
        "immutable": True,
        "counts": counts,
        "content_hash": content_hash,
        "variants": variants,
    }


def main() -> None:
    truth = _ROOT / "TRUTH/clinvar"
    probe = json.loads((truth / "tier_b_probe_v1.json").read_text())["variants"]
    manifest = json.loads((truth / "heldout_manifest.json").read_text())
    manifest_by_id = {m["variant_id"]: m for m in manifest["variants"]}

    att_path = _ROOT / "RESULTS/exp1_attribution.json"
    attribution = json.loads(att_path.read_text()) if att_path.exists() else []

    model = "claude-sonnet-4-5"
    joined = join_genomic_context(probe, manifest_by_id)
    ei = ei_variants_for_model(attribution, model)
    selected = select_probe(joined, ei, per_class=6, vus_controls=3)
    frozen = freeze(selected, model=model)

    out = truth / "acquisition_probe_v1.json"
    out.write_text(json.dumps(frozen, indent=2))
    print(f"wrote {out.relative_to(_ROOT)}")
    print(f"selected {frozen['counts']['selected']} variants: "
          + ", ".join(f"{k}={frozen['counts'][k]}" for k in DEFINITIVE + (VUS,)))
    print(f"ei-enriched for {model}: {sum(1 for v in selected if v['variant_id'] in ei)}"
          f"/{frozen['counts']['selected']} were evidence_insufficient under thin evidence")
    print(f"content_hash {frozen['content_hash'][:16]}...")


if __name__ == "__main__":
    main()
