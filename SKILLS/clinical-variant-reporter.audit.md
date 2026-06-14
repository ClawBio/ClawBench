# Audit: clinical-variant-reporter (Step 1 determinism gate)

Date: 2026-06-14. Skill pinned at ClawBio/ClawBio commit `d25071be` (see `.pinned-commit`).
Auditor question: does the skill deterministically combine structured ACMG evidence codes into the
final 5-tier classification through code, independent of the model?

## Verdict: PASS

The final ACMG class is computed by deterministic code, not narrated by a model.

Evidence:
- Execution path: `main()` -> `run_classification()` -> `classify_variant()` -> `classify(evaluate_criteria(ev))`.
  `classify()` (acmg_engine.py) is a pure function implementing Richards et al. 2015 Table 5 combining rules.
- No model in the loop: grep for `anthropic|openai|completion|llm|prompt|messages.create|model=` across
  `acmg_engine.py` and `clinical_variant_reporter.py` returns nothing. The skill is a pure-Python CLI; the
  "agent" framing in SKILL.md governs skill selection/triggering, not classification.
- Exceeds the V1 bar: evidence-code assignment (`evaluate_criteria`) is also deterministic code derived from
  structured annotation (VEP/gnomAD/ClinVar). The combiner accepts `list[EvidenceCriterion]`, so it can also be
  driven by model-assigned codes for the V1-analogue "model supplies codes, code combines" arm.
- Empirical: vendored test suite 36/36 pass; two independent demo runs produce byte-identical per-variant
  classification + triggered criteria. Reproducible by construction.

No combiner replacement is needed. We pin and treat `classify()` as the unit under test.

## Findings that gate Exp 1 validity (do not change PASS, but must be handled before the headline run)

### F1 (critical) ClinVar circularity / label leakage — RESOLVED 2026-06-14
Resolved by `HARNESS/blinding.py` (TDD, 7 tests). Two modes: `clinvar_blinded` (primary; nulls
clinvar_significance, disables PS1/PP5/BP6, records `blinded_criteria_removed=[PS1,PP5,BP6]`,
`clinvar_used_as_evidence=false`) and `clinvar_unblinded_sensitivity` (control). Skill left pristine; blinding
is harness-side. Sensitivity demonstration (`HARNESS/demo_blinding_sensitivity.py`): 7/20 (35%) demo variants
change class when ClinVar evidence is blinded, quantifying the circularity inflation. Original finding below.


PS1, PP5 (pathogenic) and BP6 (benign) read `clinvar_significance` directly as input. If Exp 1 ground truth is
the ClinVar classification, the skill is partly reading the answer key, so the skill-execution arm will look
artificially perfect and a reviewer will reject it. PP5/BP6 are also deprecated by ClinGen SVI (2018) for this
exact circularity. Required: a ClinVar-blinded benchmark configuration that disables PS1/PP5/BP6 (or nulls
`clinvar_significance`) so classification is independent of the truth label. This is the V2 "anti-shortcut /
untouched" principle made operational. The demo's 100% is likewise partly circular (cached ClinVar feeds PP5/PS1).

### F2 (scope) only 12 of 28 criteria automatable
PS2/PM6, PS3/BS3, PS4, PM3, PP1/BS4, PP2/BP1, PP4, BP2/3/5, BS2 are documented as not assessed (need
de novo/functional/segregation/cohort data). Honest and stated. Implication: many real held-out variants will
land VUS for lack of evidence. That abstain-on-uncertainty behavior is the safe/correct outcome and must be
scored as such, not as error. Choose the held-out slice so the automatable criteria can actually classify, and
measure the abstention rate explicitly.

### F3 (overclaim vs implementation) PVS1
SKILL.md claims "Automated PVS1 decision tree following the ClinGen SVI flowchart (Abou Tayoun 2018)." The code
triggers PVS1 at full very_strong on any LoF consequence, with no NMD / last-exon / rescue logic and no strength
downgrade. PVS1 therefore over-triggers. Either implement the decision tree or soften the SKILL.md claim before
publication (project rule: audit every claim against the code).

### F4 (combining-rule calibration)
- PM2 is emitted at strength `moderate` while its own detail text says "applied conservatively as supporting."
  ClinGen recommends PM2_Supporting. As moderate it inflates pathogenic combinations. Real bug; fix strength to supporting.
- Conflicting -> VUS triggers on ANY both-direction evidence (e.g. PVS1+PS1 with a stray BP4 flips to VUS).
  ACMG default-to-VUS-on-conflict is defensible but blunt; document the decision.
- Pure rule-count combining; the Tavtigian/ClinGen Bayesian point system is not used. Fine for v0.1; a
  rule-based vs points-based combiner comparison is a candidate secondary result.

## Immediate next build (revised by this audit)
Not a combiner rewrite. Instead:
1. ClinVar-blinded mode in the harness (F1) — the one must-fix before the Exp 1 headline. Likely a small skill
   flag to disable PS1/PP5/BP6, or harness-side nulling of `clinvar_significance`.
2. `evidence_schema.json` — JSON schema for structured evidence-code input, enabling the
   model-supplies-codes -> `classify()` arm and criteria-level concordance scoring.
3. `tests/test_acmg_edge_cases.py` — benchmark-side conformance tests covering F4 (PM2 strength, PVS1
   over-trigger, conflict-with-supporting) and F1 (blinded behavior).
4. Report abstention rate (F2) as a first-class metric.
