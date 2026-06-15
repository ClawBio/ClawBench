"""TDD for the held-out slice summary report (counts by cutoff/status/gene/class/reclassification)."""
from __future__ import annotations

import slice_summary as S


def _variant(vid, gene, clnsig, stars, lfa, reclassified=False, frm=None, to=None):
    return {"variant_id": vid, "genomic_context": {"gene": gene},
            "truth": {"clnsig": clnsig, "review_stars": stars, "label_first_available": lfa},
            "reclassified": reclassified, "from_class": frm, "to_class": to}


MANIFEST = {
    "effective_cutoff": "2025-11-28", "min_review_stars": 2, "safety_margin_days": 180,
    "model_cutoffs": {"gpt-5.2": "2025-06-01", "gpt-4.1": "2024-06-01"},
    "content_hash": "abc123",
    "counts": {"candidates": 10, "held_out": 3, "reclassified": 1,
               "excluded": {"pre_cutoff": 5, "below_min_stars": 1, "unusable_label": 1,
                            "missing_or_ambiguous_date": 0, "malformed": 0}},
    "variants": [
        _variant("V1", "BRCA1", "Pathogenic", 3, "2026-01-01"),
        _variant("V2", "BRCA1", "Likely Pathogenic", 2, "2026-02-01",
                 reclassified=True, frm="Uncertain Significance", to="Likely Pathogenic"),
        _variant("V3", "TP53", "Benign", 3, "2026-03-01"),
    ],
}


def test_headline_present():
    s = S.summarise_slice(MANIFEST)
    assert "temporally blinded" in s["headline"]
    assert "post-date model cutoffs" in s["headline"]


def test_counts_by_dimension():
    s = S.summarise_slice(MANIFEST)
    assert s["by_review_stars"] == {3: 2, 2: 1}
    assert s["by_class"] == {"Pathogenic": 1, "Likely Pathogenic": 1, "Benign": 1}
    assert s["by_gene_top"][0] == ("BRCA1", 2)
    assert s["n_genes"] == 2
    assert s["counts"]["held_out"] == 3


def test_reclassification_transitions():
    s = S.summarise_slice(MANIFEST)
    assert s["reclassification"]["n"] == 1
    assert s["reclassification"]["by_transition"] == {"Uncertain Significance -> Likely Pathogenic": 1}


def test_blinding_headroom():
    s = S.summarise_slice(MANIFEST)
    b = s["blinding"]
    assert b["earliest_label_first_available"] == "2026-01-01"
    assert b["all_labels_postdate_all_model_cutoffs"] is True
    # earliest label 2026-01-01 is 214 days after the latest model cutoff 2025-06-01
    assert b["per_model"]["gpt-5.2"]["headroom_days_to_earliest_label"] == 214
    assert b["per_model"]["gpt-4.1"]["cutoff"] == "2024-06-01"


def test_render_markdown():
    s = S.summarise_slice(MANIFEST)
    md = S.render_markdown(s)
    assert md.startswith("# ")
    assert "temporally blinded" in md
    assert "BRCA1" in md
    assert "abc123" in md  # content hash recorded
    assert "Uncertain Significance -> Likely Pathogenic" in md
