# GWAS Catalog + PubMed snapshot (provenance gate)

`snapshot.json` is a frozen extract of the GWAS Catalog REST API and PubMed E-utilities,
used by `HARNESS/validate_provenance.py` (`CachedOracle`) so the provenance gate runs
deterministically and offline in CI. See ClawBio/ClawBench#3 (L1).

## Contents
- `associations`: `rsid -> [ {efo_id, trait, pmid, ancestries[], or_value} ]` — for each
  variant, the studies GWAS Catalog links it to (filtered to the traits of interest), with
  the study PMID, mapped super-population ancestry, and per-copy OR.
- `pmid_titles` / `pmid_topic`: PubMed title + tokenised topic terms, for the coverage-gap
  fallback (a cited PMID absent from the catalog but on-topic is flagged for sign-off, not
  hard-blocked).

## Regenerate
```
python scripts/build_provenance_snapshot.py
```
Hits the live APIs and overwrites this file. The committed snapshot is the truth-of-record;
refresh it when the panel of variants under test changes.

## Scope
This is a demonstration freeze for the audited `ancestry-risk-profiler` variants, not the
full catalog. Scaling the panel and wiring the gate to block on `skills/*` PRs that declare
`emits_effect_sizes` is tracked in the issue.
