"""Effect-size provenance gate: fail closed when a cited paper does not support the claim.

For each association entry a skill emits (variant, trait, ancestry, effect, source), this
resolves the cited PMID against a citation ORACLE (GWAS Catalog + PubMed) and verifies the
paper actually reports that variant/trait in that ancestry with a comparable effect. A
citation is a falsifiable claim, not a label: "cited but wrong" is the same safety hazard as
"missing", and it is invisible to secret/lint scanners.

Layer 1 of the scientific-correctness CI gate (ClawBio/ClawBench#3). Mirrors the pattern of
HARNESS/validate_evidence.py: a schema in SCHEMAS/, machine-readable error codes, and an
entry point that is exception-guarded so it can never raise.

Coverage-gap handling: GWAS Catalog does not index every primary paper (e.g. it links
rs73885319/kidney to PAGE/MVP, not the original Genovese 2010 APOL1 paper). So when a cited
PMID is not a registered study for a (variant, trait), the gate does NOT hard-block; it falls
back to a PubMed topic check. If the paper's topic overlaps the trait it is flagged
TOPIC_MATCH_LOW (advisory, human sign-off); only a genuinely off-topic paper (head-and-neck
cancer cited for kidney disease) is a hard block. This keeps the gate from false-rejecting
correct-but-uncatalogued citations while still catching fabricated ones.

The oracle is injected. Tests use a deterministic fixture or the committed snapshot
(CachedOracle); production may use LiveOracle (GWAS Catalog REST + PubMed). No import-time I/O.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

ERROR_CODES = (
    "PARSE_ERROR",            # entry was not a dict / unexpected shape
    "SCHEMA_INVALID",         # fails effect_size_provenance_schema.json
    "PMID_UNRESOLVABLE",      # PubMed has no such PMID (typo / fabricated)
    "ASSOC_NOT_FOUND",        # no catalog association AND PMID topic does not match the trait
    "PMID_STUDY_MISMATCH",    # association exists, cited PMID is off-topic and not a source for it
    "ANCESTRY_MISMATCH",      # cited study reports a different ancestry than the entry claims
    "EFFECT_OUT_OF_RANGE",    # effect size deviates implausibly from the catalog value
    "TOPIC_MATCH_LOW",        # WARN: PMID not in catalog for this assoc, but topic overlaps the trait
)

# An effect within [LO x, HI x] of the catalog value is accepted (same direction assumed).
EFFECT_RATIO_LO = 0.5
EFFECT_RATIO_HI = 2.0

_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "SCHEMAS" / "effect_size_provenance_schema.json"
_DEFAULT_SNAPSHOT = Path(__file__).resolve().parents[1] / "TRUTH" / "gwas_catalog" / "snapshot.json"


class Oracle(Protocol):
    """Citation oracle. CachedOracle reads the committed snapshot; LiveOracle hits the network."""

    def pmid_exists(self, pmid: str) -> bool: ...

    def associations_for(self, rsid: str) -> list[dict]:
        """GWAS Catalog study records: {efo_id, trait, pmid, ancestries: list[str], or_value}."""
        ...

    def pubmed_topic_terms(self, pmid: str) -> set[str]:
        """Lower-cased topic terms (title/MeSH) for the coverage-gap fallback."""
        ...


def _finding(index, rsid, code, severity, field, message, valid):
    return {"valid": valid, "error_code": code, "severity": severity,
            "field": field, "message": message, "rsid": rsid, "index": index}


def _ok(index, rsid):
    return _finding(index, rsid, None, None, None, "ok", True)


def _load_schema() -> dict:
    with open(_SCHEMA_PATH) as fh:
        return json.load(fh)


def _schema_error(entry) -> str | None:
    try:
        from jsonschema import Draft202012Validator
    except Exception:  # pragma: no cover - declared dependency
        return None
    errs = sorted(Draft202012Validator(_load_schema()).iter_errors(entry), key=lambda e: list(e.path))
    if errs:
        e = errs[0]
        return f"{'/'.join(str(p) for p in e.path) or '<root>'}: {e.message}"
    return None


def _trait_tokens(label: str) -> set[str]:
    stop = {"the", "and", "for", "with", "disease", "disorder"}
    toks = "".join(c.lower() if c.isalnum() else " " for c in label).split()
    return {t for t in toks if len(t) > 2 and t not in stop}


def validate_entry(entry, oracle: Oracle, index: int = 0) -> dict:
    """Validate one association entry. Fail-closed, never raises."""
    try:
        if not isinstance(entry, dict):
            return _finding(index, None, "PARSE_ERROR", "block", "<root>", "entry is not an object", False)

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

        if not oracle.pmid_exists(pmid):
            return _finding(index, rsid, "PMID_UNRESOLVABLE", "block", "source.pmid",
                            f"PMID {pmid} does not resolve in PubMed", False)

        matching = [r for r in oracle.associations_for(rsid) if r.get("efo_id") == efo]
        pmid_studies = [r for r in matching if str(r.get("pmid")) == str(pmid)]

        if not pmid_studies:
            # Cited PMID is not a registered study for this variant+trait. Coverage gap or wrong cite?
            if oracle.pubmed_topic_terms(pmid) & _trait_tokens(label):
                return _finding(index, rsid, "TOPIC_MATCH_LOW", "warn", "source.pmid",
                                f"PMID {pmid} is not a GWAS Catalog source for {rsid}-{efo}, but its "
                                "topic overlaps the trait. Needs human sign-off.", True)
            if matching:
                return _finding(index, rsid, "PMID_STUDY_MISMATCH", "block", "source.pmid",
                                f"PMID {pmid} is not a source for the {rsid}-{efo} association and its "
                                "topic does not match the trait (cited paper is about something else)", False)
            return _finding(index, rsid, "ASSOC_NOT_FOUND", "block", "variant.rsid",
                            f"No GWAS Catalog association for {rsid} with trait {efo}, and PMID {pmid} "
                            "topic does not match the trait", False)

        # Cited PMID IS a catalog study for this variant+trait: check ancestry then effect.
        known_anc = {a for r in pmid_studies for a in (r.get("ancestries") or [])}
        if known_anc and ancestry not in known_anc:
            return _finding(index, rsid, "ANCESTRY_MISMATCH", "block", "ancestry",
                            f"Entry claims {ancestry}; cited study reports {sorted(known_anc)}", False)

        for r in pmid_studies:
            cat = r.get("or_value")
            if cat and value and cat > 0 and value > 0:
                ratio = value / cat
                if not (EFFECT_RATIO_LO <= ratio <= EFFECT_RATIO_HI):
                    return _finding(index, rsid, "EFFECT_OUT_OF_RANGE", "block", "effect.value",
                                    f"Effect {value} deviates from catalog {cat} (ratio {ratio:.2f}, "
                                    f"allowed {EFFECT_RATIO_LO}-{EFFECT_RATIO_HI}x)", False)
        return _ok(index, rsid)
    except Exception as exc:
        return _finding(index, None, "PARSE_ERROR", "block", "<root>", f"unexpected error: {exc}", False)


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
    return {"passed": len(blocking) == 0, "n_entries": len(items),
            "n_blocking": len(blocking), "n_warnings": len(warnings),
            "findings": [f for f in findings if not f["valid"] or f["severity"] == "warn"]}


class CachedOracle:
    """Offline oracle backed by the committed TRUTH/gwas_catalog/snapshot.json freeze."""

    def __init__(self, snapshot_path: Path | str | None = None):
        with open(snapshot_path or _DEFAULT_SNAPSHOT) as fh:
            snap = json.load(fh)
        self._assoc = snap.get("associations", {})
        self._titles = snap.get("pmid_titles", {})
        self._topic = snap.get("pmid_topic", {})

    def pmid_exists(self, pmid: str) -> bool:
        pmid = str(pmid)
        if pmid in self._titles:
            return True
        return any(str(r.get("pmid")) == pmid for recs in self._assoc.values() for r in recs)

    def associations_for(self, rsid: str) -> list[dict]:
        return self._assoc.get(rsid, [])

    def pubmed_topic_terms(self, pmid: str) -> set[str]:
        return set(self._topic.get(str(pmid), []))


class LiveOracle:  # pragma: no cover - network, exercised by scripts/build_provenance_snapshot.py
    """Production oracle: GWAS Catalog REST + PubMed E-utilities. Prefer CachedOracle in CI."""

    GWAS = "https://www.ebi.ac.uk/gwas/rest/api"
    EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

    def _get(self, url: str) -> dict:
        import urllib.request
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as fh:
            return json.load(fh)

    def pmid_exists(self, pmid: str) -> bool:
        r = self._get(f"{self.EUTILS}/esummary.fcgi?db=pubmed&retmode=json&id={pmid}")
        return str(pmid) in r.get("result", {}).get("uids", [])

    def associations_for(self, rsid: str) -> list[dict]:
        url = f"{self.GWAS}/singleNucleotidePolymorphisms/{rsid}/associations?projection=associationBySnp"
        out = []
        for a in self._get(url).get("_embedded", {}).get("associations", []):
            try:
                study = self._get(a["_links"]["study"]["href"])
            except Exception:
                continue
            pmid = str(study.get("publicationInfo", {}).get("pubmedId") or "")
            for t in a.get("efoTraits", []) or []:
                out.append({"efo_id": t.get("shortForm"), "trait": t.get("trait"),
                            "pmid": pmid, "ancestries": [], "or_value": a.get("orPerCopyNum")})
        return out

    def pubmed_topic_terms(self, pmid: str) -> set[str]:
        r = self._get(f"{self.EUTILS}/esummary.fcgi?db=pubmed&retmode=json&id={pmid}")
        title = r.get("result", {}).get(str(pmid), {}).get("title", "")
        return {t for t in "".join(c.lower() if c.isalnum() else " " for c in title).split() if len(t) > 2}


def main(argv=None) -> int:  # pragma: no cover - CLI wiring
    import argparse

    ap = argparse.ArgumentParser(description="Validate a skill's effect-size provenance panel.")
    ap.add_argument("panel", help="JSON file: a list of association entries")
    ap.add_argument("--live", action="store_true", help="use the live GWAS Catalog/PubMed oracle")
    args = ap.parse_args(argv)
    with open(args.panel) as fh:
        entries = json.load(fh)
    oracle = LiveOracle() if args.live else CachedOracle()
    report = validate_panel(entries, oracle)
    print(json.dumps(report, indent=2, default=list))
    return 0 if report["passed"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
