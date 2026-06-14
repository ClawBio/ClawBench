"""ACMG/AMP 2015 code vocabulary, strength ladders, mode + circularity registries.

The single source of truth for the ClawBench evidence contract. The 28-code table
below is NOT hand-typed from memory: it is the reconciled output of two independent
agent builds (one web-grounded against ClinGen SVI), verified for ladder consistency.
Full provenance incl. per-code definitions and the reconciliation disagreements:
  SKILLS/.acmg_contract_workflow_output.json

Principle the whole contract enforces:
  "Truth labels are scoring artefacts, not interpretive evidence."

Sources: Richards et al. 2015 (PMID 25741868); ClinGen SVI strength modulation
(PVS1 Abou Tayoun 2018; de novo points 2021; PP3/BP4 Pejaver 2022).
"""
from __future__ import annotations

import re

# code -> operational fields. direction and clinvar_derived are intrinsic to the
# code and are NEVER taken from a model submission. allowed = baseline + sanctioned
# downgrades + ClinGen-endorsed upgrades (the upgrades additionally require an
# explicit strength_basis at validation time).
_VOCAB = {
    "PVS1": dict(direction="pathogenic", baseline="very_strong", allowed=['very_strong', 'strong', 'moderate', 'supporting'], modulatable_up=False, clinvar_derived=False),
    "PS1": dict(direction="pathogenic", baseline="strong", allowed=['strong', 'moderate', 'supporting'], modulatable_up=False, clinvar_derived=True),
    "PS2": dict(direction="pathogenic", baseline="strong", allowed=['very_strong', 'strong', 'moderate', 'supporting'], modulatable_up=True, clinvar_derived=False),
    "PS3": dict(direction="pathogenic", baseline="strong", allowed=['strong', 'moderate', 'supporting'], modulatable_up=False, clinvar_derived=False),
    "PS4": dict(direction="pathogenic", baseline="strong", allowed=['strong', 'moderate', 'supporting'], modulatable_up=False, clinvar_derived=False),
    "PM1": dict(direction="pathogenic", baseline="moderate", allowed=['moderate', 'supporting'], modulatable_up=False, clinvar_derived=False),
    "PM2": dict(direction="pathogenic", baseline="moderate", allowed=['moderate', 'supporting'], modulatable_up=False, clinvar_derived=False),
    "PM3": dict(direction="pathogenic", baseline="moderate", allowed=['moderate', 'supporting'], modulatable_up=False, clinvar_derived=False),
    "PM4": dict(direction="pathogenic", baseline="moderate", allowed=['moderate', 'supporting'], modulatable_up=False, clinvar_derived=False),
    "PM5": dict(direction="pathogenic", baseline="moderate", allowed=['moderate', 'supporting'], modulatable_up=False, clinvar_derived=True),
    "PM6": dict(direction="pathogenic", baseline="moderate", allowed=['very_strong', 'strong', 'moderate', 'supporting'], modulatable_up=True, clinvar_derived=False),
    "PP1": dict(direction="pathogenic", baseline="supporting", allowed=['supporting', 'moderate', 'strong'], modulatable_up=True, clinvar_derived=False),
    "PP2": dict(direction="pathogenic", baseline="supporting", allowed=['supporting'], modulatable_up=False, clinvar_derived=False),
    "PP3": dict(direction="pathogenic", baseline="supporting", allowed=['supporting', 'moderate', 'strong'], modulatable_up=True, clinvar_derived=False),
    "PP4": dict(direction="pathogenic", baseline="supporting", allowed=['supporting', 'moderate'], modulatable_up=True, clinvar_derived=False),
    "PP5": dict(direction="pathogenic", baseline="supporting", allowed=['supporting'], modulatable_up=False, clinvar_derived=True),
    "BA1": dict(direction="benign", baseline="stand_alone", allowed=['stand_alone', 'strong', 'supporting'], modulatable_up=False, clinvar_derived=False),
    "BS1": dict(direction="benign", baseline="strong", allowed=['strong', 'supporting'], modulatable_up=False, clinvar_derived=False),
    "BS2": dict(direction="benign", baseline="strong", allowed=['strong', 'supporting'], modulatable_up=False, clinvar_derived=False),
    "BS3": dict(direction="benign", baseline="strong", allowed=['strong', 'supporting'], modulatable_up=False, clinvar_derived=False),
    "BS4": dict(direction="benign", baseline="strong", allowed=['strong', 'supporting'], modulatable_up=False, clinvar_derived=False),
    "BP1": dict(direction="benign", baseline="supporting", allowed=['supporting'], modulatable_up=False, clinvar_derived=False),
    "BP2": dict(direction="benign", baseline="supporting", allowed=['supporting'], modulatable_up=False, clinvar_derived=False),
    "BP3": dict(direction="benign", baseline="supporting", allowed=['supporting'], modulatable_up=False, clinvar_derived=False),
    "BP4": dict(direction="benign", baseline="supporting", allowed=['supporting', 'strong'], modulatable_up=True, clinvar_derived=False),
    "BP5": dict(direction="benign", baseline="supporting", allowed=['supporting'], modulatable_up=False, clinvar_derived=False),
    "BP6": dict(direction="benign", baseline="supporting", allowed=['supporting'], modulatable_up=False, clinvar_derived=True),
    "BP7": dict(direction="benign", baseline="supporting", allowed=['supporting'], modulatable_up=False, clinvar_derived=False),
}

VALID_CODES = frozenset(_VOCAB)
STRENGTHS = ("stand_alone", "very_strong", "strong", "moderate", "supporting")

# Strength rank within a direction's ladder. Pathogenic: supporting<moderate<strong<very_strong.
# Benign has NO moderate level (2015 framework): supporting<strong<stand_alone.
_RANK = {"supporting": 1, "moderate": 2, "strong": 3, "very_strong": 4, "stand_alone": 4}

# ACMG assertion-database codes: "a reputable source already classified this".
# Always blocked in any primary (blinded) mode because they are definitionally circular
# with a classification truth label, regardless of declared source_type.
ASSERTION_CODES = frozenset({"PP5", "BP6"})
# Codes that lean on a prior database assertion only when ClinVar-sourced.
CLINVAR_GATED_CODES = frozenset({"PS1", "PM5"})

# Truth-source circularity registry: a truth label cross-pollinates with these source
# families. ClinGen VCEP and LOVD classifications co-deposit into ClinVar (and reach each
# other through it), so the relation is symmetric: when truth is ClinVar, evidence from
# clingen_vcep/lovd is circular, and vice versa. In primary mode evidence from any member
# of the active truth source's family is circular with that truth label. Extensible.
TRUTH_CIRCULAR_FAMILIES = {
    "clinvar": {"clinvar", "clingen_vcep", "lovd"},
    "clingen_vcep": {"clingen_vcep", "clinvar", "lovd"},
    "lovd": {"lovd", "clinvar", "clingen_vcep"},
    "hgmd": {"hgmd"},
}

# Markers that betray a ClinVar provenance even when source_type is relabelled. The
# accession prefix may be followed by separators / leading zeros (e.g. "VCV 0012345",
# "RCV-99", "SCV_1.2"), so do not require a digit immediately after the prefix.
_CLINVAR_MARKER = re.compile(r"(?i)(clinvar|\b(?:vcv|rcv|scv)[\s._-]*0*\d)")

# A string has content if it contains at least one alphanumeric word character. This is
# robust to zero-width / format characters (U+200B etc.) that survive str.strip().
_HAS_CONTENT = re.compile(r"[^\W_]", re.UNICODE)


def has_content(s) -> bool:
    return isinstance(s, str) and bool(_HAS_CONTENT.search(s))
# Markers for other curated assertion DBs, used for general truth-leakage detection.
_SOURCE_MARKERS = {
    "clingen_vcep": re.compile(r"(?i)(clingen|vcep|variant curation expert panel)"),
    "lovd": re.compile(r"(?i)\blovd\b"),
    "hgmd": re.compile(r"(?i)\bhgmd\b"),
}

# Minimal per-code admissible source_type map (only unambiguous cases; extensible).
# A code paired with an inadmissible source_type signals fabricated/laundered provenance.
ADMISSIBLE_SOURCE_TYPES = {
    "BA1": {"population_frequency", "database"},
    "BS1": {"population_frequency", "database"},
    "PM2": {"population_frequency", "database"},
    "PP3": {"computational", "in_silico"},
    "BP4": {"computational", "in_silico"},
    "PS3": {"functional", "literature"},
    "BS3": {"functional", "literature"},
}


def is_valid_code(code: str) -> bool:
    return code in VALID_CODES


def direction(code: str) -> str:
    return _VOCAB[code]["direction"]


def baseline_strength(code: str) -> str:
    return _VOCAB[code]["baseline"]


def allowed_strengths(code: str) -> list[str]:
    return list(_VOCAB[code]["allowed"])


def is_clinvar_derived(code: str) -> bool:
    return _VOCAB[code]["clinvar_derived"]


def is_modulatable_up(code: str) -> bool:
    return _VOCAB[code]["modulatable_up"]


def strength_rank(strength: str) -> int:
    return _RANK[strength]


def is_upgrade(code: str, strength: str) -> bool:
    """True if the strength is above the code's baseline on its ladder."""
    return _RANK[strength] > _RANK[_VOCAB[code]["baseline"]]


def strength_status(code: str, strength: str) -> str:
    """Classify a (code, strength) pair: 'ok_downgrade_or_baseline', 'needs_basis',
    or 'invalid' (off-ladder or beyond the sanctioned cap)."""
    if strength not in _VOCAB[code]["allowed"]:
        return "invalid"
    if is_upgrade(code, strength):
        return "needs_basis"
    return "ok_downgrade_or_baseline"


# ---- mode registry -------------------------------------------------------------
PRIMARY_MODE_RE = re.compile(r"^(clinvar_blinded|primary_.+)$")

# The ONLY vetted mode in which ClinVar/assertion evidence is legitimately permitted
# (the control arm that measures circularity inflation). ClinVar checks are fail-closed:
# enabled for every other mode, including dev/test and any unknown mode, so a model can
# never disable blinding by self-selecting a mode the harness did not authorise.
NON_BLINDED_MODES = frozenset({"clinvar_unblinded_sensitivity"})


def is_primary_mode(mode: str) -> bool:
    return bool(PRIMARY_MODE_RE.match(mode or ""))


def requires_truth_source(mode: str) -> bool:
    return is_primary_mode(mode)


def clinvar_checks_enabled(mode: str) -> bool:
    """Fail-closed: block ClinVar/assertion evidence in every mode except the vetted control."""
    return mode not in NON_BLINDED_MODES


def expected_blinded_status(mode: str) -> bool:
    """The clinvar_blinded_status a well-formed submission must declare for this mode."""
    return is_primary_mode(mode)


# ---- circularity ---------------------------------------------------------------
def is_clinvar_sourced(source_type: str, source_id: str = "", rationale: str = "") -> bool:
    """ClinVar provenance via source_type or laundering markers in id/rationale."""
    if (source_type or "").lower() == "clinvar":
        return True
    blob = f"{source_id} {rationale}"
    return bool(_CLINVAR_MARKER.search(blob))


def circular_source_family(source_type: str, source_id: str, rationale: str, truth_source: str) -> str | None:
    """Return the circular source family name if this evidence's provenance overlaps the
    active truth source (excluding the ClinVar case, which the validator names separately),
    else None."""
    families = TRUTH_CIRCULAR_FAMILIES.get(truth_source, {truth_source})
    blob = f"{source_type} {source_id} {rationale}"
    for fam in families:
        if fam == "clinvar":
            continue  # handled by the named DISALLOWED_CLINVAR_CRITERION path
        if (source_type or "").lower() == fam:
            return fam
        marker = _SOURCE_MARKERS.get(fam)
        if marker and marker.search(blob):
            return fam
    return None
