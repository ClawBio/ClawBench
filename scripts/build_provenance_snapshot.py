"""Build the offline GWAS Catalog + PubMed snapshot for the provenance gate (ClawBio/ClawBench#3).

Queries the live GWAS Catalog REST API and PubMed E-utilities for a fixed panel of variants and
PMIDs, then writes TRUTH/gwas_catalog/snapshot.json so CI can run the gate deterministically and
offline. Re-run this to refresh the freeze; the committed snapshot is the truth-of-record.

Usage:
    python scripts/build_provenance_snapshot.py

No side effects at import. Network only inside main().
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

GWAS = "https://www.ebi.ac.uk/gwas/rest/api"
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
SNAPSHOT = Path(__file__).resolve().parents[1] / "TRUTH" / "gwas_catalog" / "snapshot.json"

# Panel: rsid -> trait keywords whose associations we resolve to studies (bounds study fetches).
PANEL = {
    "rs7903146": ["diabetes"],
    "rs73885319": ["kidney", "renal", "glomerulo", "creatinine"],
    "rs429358": ["alzheimer"],
    "rs2981582": ["breast"],
    "rs11591147": ["cholesterol", "ldl", "lipid", "coronary"],
}
# PMIDs we need PubMed topic terms for (cited + correct + discovery references).
TOPIC_PMIDS = ["20566908", "20647424", "22158537", "23945395", "27005778",
               "17478679", "16415884", "24162737", "17529973", "18193044"]

ANCESTRY_MAP = [
    ("european", "EUR"), ("east asian", "EAS"), ("south asian", "SAS"),
    ("central asian", "SAS"), ("african american", "AFR"), ("afro-caribbean", "AFR"),
    ("sub-saharan", "AFR"), ("african unspecified", "AFR"), ("african", "AFR"),
    ("hispanic", "AMR"), ("latin american", "AMR"),
]


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as fh:
        return json.load(fh)


def _map_ancestry(group: str) -> str | None:
    g = (group or "").lower()
    for needle, code in ANCESTRY_MAP:
        if needle in g:
            return code
    return None


def _topic_terms(title: str) -> list[str]:
    return sorted({t for t in "".join(c.lower() if c.isalnum() else " " for c in title).split() if len(t) > 2})


def main() -> int:
    associations: dict[str, list[dict]] = {}
    for rsid, keywords in PANEL.items():
        url = f"{GWAS}/singleNucleotidePolymorphisms/{rsid}/associations?projection=associationBySnp"
        assoc = _get(url).get("_embedded", {}).get("associations", [])
        records, seen = [], set()
        for a in assoc:
            traits = a.get("efoTraits", []) or []
            if not any(any(k in t.get("trait", "").lower() for k in keywords) for t in traits):
                continue
            try:
                study = _get(a["_links"]["study"]["href"])
            except Exception:
                continue
            pmid = str(study.get("publicationInfo", {}).get("pubmedId") or "")
            ancestries = sorted({c for anc in study.get("ancestries", [])
                                 for grp in anc.get("ancestralGroups", [])
                                 if (c := _map_ancestry(grp.get("ancestralGroup")))})
            for t in traits:
                key = (t.get("shortForm"), pmid)
                if not pmid or key in seen:
                    continue
                seen.add(key)
                records.append({
                    "efo_id": t.get("shortForm"), "trait": t.get("trait"),
                    "pmid": pmid, "ancestries": ancestries,
                    "or_value": a.get("orPerCopyNum"),
                })
            time.sleep(0.1)
        associations[rsid] = records
        print(f"  {rsid}: {len(records)} study-trait records", file=sys.stderr)

    pmid_titles, pmid_topic = {}, {}
    ids = ",".join(TOPIC_PMIDS)
    res = _get(f"{EUTILS}/esummary.fcgi?db=pubmed&retmode=json&id={ids}")["result"]
    for u in res.get("uids", []):
        title = res[u].get("title", "")
        pmid_titles[u] = title
        pmid_topic[u] = _topic_terms(title)

    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(json.dumps(
        {"associations": associations, "pmid_titles": pmid_titles, "pmid_topic": pmid_topic},
        indent=2, sort_keys=True) + "\n")
    print(f"wrote {SNAPSHOT} :: {sum(len(v) for v in associations.values())} records, "
          f"{len(pmid_titles)} PMIDs", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
