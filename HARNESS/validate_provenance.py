"""Effect-size provenance gate: fail closed when a cited paper does not support the claim.

For each association entry a skill emits (variant, trait, ancestry, effect, source), this
resolves the cited PMID against a citation ORACLE (GWAS Catalog + PubMed) and verifies the
paper actually reports that variant/trait in that ancestry with a comparable effect. A
citation is a falsifiable claim, not a label: "cited but wrong" is the same safety hazard as
"missing", and it is invisible to secret/lint scanners.

Layer 1 of the scientific-correctness CI gate (ClawBio/ClawBench#3). Mirrors the pattern of
HARNESS/validate_evidence.py: a schema in SCHEMAS/, machine-readable error codes, and an
entry point that is exception-guarded so it can never raise.

The oracle is injected (see the Oracle protocol). Tests pass a deterministic fixture oracle;
production wires LiveOracle (GWAS Catalog REST + PubMed efetch). No side effects at import.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

# Ordered roughly by where in the pipeline the check fires.
ERROR_CODES = (
    "PARSE_ERROR",            # entry was not a dict / unexpected shape
    "SCHEMA_INVALID",         # fails effect_size_provenance_schema.json
    "PMID_UNRESOLVABLE",      # PubMed has no such PMID (typo / fabricated)
    "ASSOC_NOT_FOUND",        # GWAS Catalog has no variant+trait association and topic does not match
    "PMID_STUDY_MISMATCH",    # association exists, but the cited PMID is not one of its studies
    "ANCESTRY_MISMATCH",      # cited study reports a different ancestry than the entry claims
    "EFFECT_OUT_OF_RANGE",    # effect size deviates implausibly from the catalog value
    "TOPIC_MATCH_LOW",        # WARN: no catalog association, but PMID topic overlaps the trait
)

# An effect within [LO x, HI x] of the catalog value is accepted (same direction assumed).
EFFECT_RATIO_LO = 0.5
EFFECT_RATIO_HI = 2.0

_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "SCHEMAS" / "effect_size_provenance_schema.json"


class Oracle(Protocol):
    """Citation oracle. LiveOracle wraps GWAS Catalog + PubMed; tests inject a fixture."""

    def pmid_exists(self, pmid: str) -> bool: ...

    def associations_for(self, rsid: str) -> list[dict]:
        """Return GWAS Catalog study records for an rsid.

        Each record: {efo_id, trait, pmid, ancestries: set[str], or_value: float | None}.
        """
        ...

    def pubmed_topic_terms(self, pmid: str) -> set[str]:
        """Lower-cased topic terms (MeSH / title) for the topic-match fallback."""
        ...


def _finding(index, rsid, code, severity, field, message, valid):
    return {
        "valid": valid,
        "error_code": code,
        "severity": severity,   # "block" | "warn" | None
        "field": field,
        "message": message,
        "rsid": rsid,
        "index": index,
    }


def _ok(index, rsid):
    return _finding(index, rsid, None, None, None, "ok", True)


def _load_schema() -> dict:
    with open(_SCHEMA_PATH) as fh:
        return json.load(fh)


def _schema_error(entry) -> str | None:
    """Return a human-readable schema error, or None if the entry is structurally valid."""
    try:
        from jsonschema import Draft202012Validator
    except Exception:  # pragma: no cover - jsonschema is a declared dependency
        return None
    validator = Draft202012Validator(_load_schema())
    errs = sorted(validator.iter_errors(entry), key=lambda e: list(e.path))
    if errs:
        e = errs[0]
        path = "/".join(str(p) for p in e.path) or "<root>"
        return f"{path}: {e.message}"
    return None


def _trait_tokens(label: str) -> set[str]:
    return {t for t in "".join(c.lower() if c.isalnum() else " " for c in label).split() if len(t) > 2}


def validate_entry(entry, oracle: Oracle, index: int = 0) -> dict:
    """Validate one association entry. Fail-closed, never raises."""
    try:
        if not isinstance(entry, dict):
            return _finding(index, None, "PARSE_ERROR", "block", "<root>",
                            "entry is not an object", False)

        schema_msg = _schema_error(entry)
        if schema_msg is not None:
            return _finding(index, (entry.get("variant") or {}).get("rsid"),
                            "SCHEMA_INVALID", "block", "<schema>", schema_msg, False)

        rsid = entry["variant"]["rsid"]
        efo = entry["trait"]["efo_id"]
        label = entry["trait"]["label"]
        ancestry = entry["ancestry"]
        pmid = entry["source"]["pmid"]
        value = entry["effect"]["value"]

        # 1. PMID must resolve at all.
        if not oracle.pmid_exists(pmid):
            return _finding(index, rsid, "PMID_UNRESOLVABLE", "block", "source.pmid",
                            f"PMID {pmid} does not resolve in PubMed", False)

        # 2. Is there a catalog association for this variant + trait?
        records = oracle.associations_for(rsid)
        matching = [r for r in records if r.get("efo_id") == efo]

        if not matching:
            # Fallback: does the PMID's topic at least overlap the trait?
            terms = oracle.pubmed_topic_terms(pmid)
            if terms & _trait_tokens(label):
                return _finding(index, rsid, "TOPIC_MATCH_LOW", "warn", "source.pmid",
                                f"No GWAS Catalog {rsid}-{efo} association; PMID {pmid} topic "
                                "overlaps the trait. Needs human sign-off.", True)
            return _finding(index, rsid, "ASSOC_NOT_FOUND", "block", "variant.rsid",
                            f"No GWAS Catalog association for {rsid} with trait {efo}", False)

        # 3. Is the cited PMID one of the studies behind that association?
        studies_with_pmid = [r for r in matching if r.get("pmid") == pmid]
        if not studies_with_pmid:
            return _finding(index, rsid, "PMID_STUDY_MISMATCH", "block", "source.pmid",
                            f"PMID {pmid} is not a source for the {rsid}-{efo} association "
                            f"(cited paper does not report this variant/trait)", False)

        # 4. Does the cited study's ancestry match the entry?
        anc_ok = any(ancestry in (r.get("ancestries") or set()) for r in studies_with_pmid)
        if not anc_ok:
            reported = sorted({a for r in studies_with_pmid for a in (r.get("ancestries") or set())})
            return _finding(index, rsid, "ANCESTRY_MISMATCH", "block", "ancestry",
                            f"Entry claims {ancestry}; cited study reports {reported}", False)

        # 5. Is the effect size in a plausible range of the catalog value?
        for r in studies_with_pmid:
            cat = r.get("or_value")
            if cat and value and cat > 0 and value > 0:
                ratio = value / cat
                if not (EFFECT_RATIO_LO <= ratio <= EFFECT_RATIO_HI):
                    return _finding(index, rsid, "EFFECT_OUT_OF_RANGE", "block", "effect.value",
                                    f"Effect {value} deviates from catalog {cat} "
                                    f"(ratio {ratio:.2f}, allowed {EFFECT_RATIO_LO}-{EFFECT_RATIO_HI}x)",
                                    False)

        return _ok(index, rsid)
    except Exception as exc:  # never raise: an unexpected shape is a fail-closed PARSE_ERROR
        return _finding(index, None, "PARSE_ERROR", "block", "<root>",
                        f"unexpected error: {exc}", False)


def validate_panel(entries, oracle: Oracle) -> dict:
    """Validate a list of entries. Returns a summary + per-entry findings. Never raises."""
    try:
        items = list(entries)
    except Exception:
        return {"passed": False, "n_entries": 0, "n_blocking": 0, "n_warnings": 0,
                "findings": [_finding(0, None, "PARSE_ERROR", "block", "<root>",
                                      "panel is not iterable", False)]}
    findings = [validate_entry(e, oracle, i) for i, e in enumerate(items)]
    blocking = [f for f in findings if f["severity"] == "block"]
    warnings = [f for f in findings if f["severity"] == "warn"]
    return {
        "passed": len(blocking) == 0,
        "n_entries": len(items),
        "n_blocking": len(blocking),
        "n_warnings": len(warnings),
        "findings": [f for f in findings if not f["valid"] or f["severity"] == "warn"],
    }


class LiveOracle:
    """Production oracle: GWAS Catalog REST + PubMed E-utilities.

    REMAINING BUILD TARGET (ClawBio/ClawBench#3). Endpoints:
      - PubMed efetch: https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id=<pmid>
      - GWAS Catalog:  https://www.ebi.ac.uk/gwas/rest/api/singleNucleotidePolymorphisms/<rsid>/associations
        (each association links a study with a pubmedId and ancestry/initialSampleSize fields)
    Cache a snapshot under TRUTH/gwas_catalog/ so CI is deterministic and offline.
    """

    def pmid_exists(self, pmid: str) -> bool:  # pragma: no cover - network, not unit-tested
        raise NotImplementedError("wire PubMed efetch - ClawBio/ClawBench#3 L1")

    def associations_for(self, rsid: str) -> list[dict]:  # pragma: no cover - network
        raise NotImplementedError("wire GWAS Catalog REST - ClawBio/ClawBench#3 L1")

    def pubmed_topic_terms(self, pmid: str) -> set[str]:  # pragma: no cover - network
        raise NotImplementedError("wire PubMed efetch MeSH/title - ClawBio/ClawBench#3 L1")


def main(argv=None) -> int:  # pragma: no cover - CLI wiring
    import argparse

    ap = argparse.ArgumentParser(description="Validate a skill's effect-size provenance panel.")
    ap.add_argument("panel", help="JSON file: a list of association entries")
    args = ap.parse_args(argv)
    with open(args.panel) as fh:
        entries = json.load(fh)
    report = validate_panel(entries, LiveOracle())
    print(json.dumps(report, indent=2, default=list))
    return 0 if report["passed"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
