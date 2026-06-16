# ClawBench Exp 1 — points-combiner decomposition (2026-06-16)

Question: is the systematic Pathogenic->Likely-Pathogenic shift caused by evidence deprivation
(Scenario A) or by the ACMG rule thresholds (Scenario B)? Method: re-score every skill_execution
record's model-assigned codes through the Tavtigian/ClinGen Bayesian points combiner (acmg_points)
and compare to the Richards rule combiner (acmg_engine) and to truth. n = 2,928 skill_execution calls.

## Answer: Scenario B for the LP->P shift. It is combiner conservatism, not evidence deprivation.

- **100% of the LP->P gap is recovered by points.** Of the 556 truth=Pathogenic variants the rule
  combiner capped at Likely Pathogenic, the points combiner classifies **556/556 (100%) as Pathogenic**
  (gpt-5.2 222/222, sonnet 281/281, gemini-flash 53/53). The models DID assign enough evidence to reach
  Pathogenic (PVS1 8 + PM2 2 = 10 = Pathogenic under points); the Richards rule-counting combiner
  artificially capped them at LP (its rule needs PVS1 + >=2 PM for Pathogenic).

So the earlier reading ("the P->LP shift is the evidence-acquisition gap quantified") was WRONG for that
specific shift. That shift is a property of the deterministic combiner's thresholds, not of missing evidence.

## But the P/LP boundary is combiner-dependent, so 5-tier exact is not a sound metric
Overall 5-tier exact concordance is **identical: rule 50% vs points 50%.** Points fixes truth=Pathogenic
(reaches P) but over-calls truth=Likely-Pathogenic to Pathogenic, moving the errors rather than removing
them. Neither Richards nor Tavtigian is uniquely "correct" at the P/LP boundary given consequence+AF.
=> The combiner threshold is itself a tunable layer, and the actionable-binary / 3-class metrics (which
collapse P and LP) are the robust endpoints, not 5-tier exact.

## The genuine evidence-deprivation residual is elsewhere (VUS on definitive variants)
For truth=Pathogenic variants:
- rule combiner mix:   {Likely Pathogenic 556, Uncertain Significance 194, Benign 5}
- points combiner mix: {Pathogenic 556, Likely Pathogenic 49, Uncertain Significance 140, Likely Benign 5, Benign 5}
The ~140 truth=Pathogenic variants that remain VUS even under points (and the 5 Benign) ARE evidence
deprivation: the model could not assign enough non-ClinVar evidence (consequence+AF) to reach a
definitive call. That is the real upstream-acquisition gap (~19% of truth-Pathogenic), and it is in the
VUS->definitive direction, not the LP<->P direction.

## Refined layered conclusion
1. Safety layer: solved, model-invariant (dangerous P<->B 0-2%).
2. Combiner layer: a TUNABLE design choice; the P/LP boundary is set by Richards-vs-Tavtigian, not by
   the model. This is a distinct, newly-identified layer with its own threshold decision.
3. Evidence-acquisition layer: the genuine residual gap (definitive variants stuck at VUS) ~19% of
   truth-Pathogenic, attributable to the deliberately-blinded non-ClinVar evidence.

## Limitation
proposed_codes captured code+strength but not source provenance, so clinvar-sourced PS1/PM5 could not be
re-stripped here (only PP5/BP6 by code). For the LoF/PVS1-driven LP->P gap this is immaterial (PVS1/PM2
are not assertion codes). Future runs should capture full provenance per code.

## Scaling decision
Do NOT scale to 6,929 yet on the strength of 5-tier accuracy (it is combiner-confounded). The defensible
primary endpoints are safety (dangerous rate), actionable-binary, 3-class, fabrication-neutralisation,
and assignment stability. A scaled run should report against those, with both combiners shown.
