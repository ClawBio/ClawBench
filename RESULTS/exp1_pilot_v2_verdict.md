# ClawBench Exp 1 pilot v2 — verdict (2026-06-16)

231 Tier-A held-out variants x 3 conditions (free_prompted, skill_reasoning, skill_execution) x
5 replicates x 3 models (gpt-5.2, claude-sonnet-4-5, gemini-2.5-flash) = 10,395 calls.
**All three arms clean: 0% infra-fail.** Per-replicate evidence-code capture enabled.

## The framing
ClawBench shows that agentic variant interpretation has **three separable layers**: safety control,
combiner-threshold choice, and evidence acquisition. The paper does NOT claim that execution improves
5-tier accuracy. It claims the benchmark reveals **where apparent errors originate**.

**Central conceptual upgrade: the deterministic combiner is not ground truth. It is a design layer.**
The Pathogenic/Likely-Pathogenic boundary is set by the choice of ACMG combiner (Richards rule-counting
vs Tavtigian points), not by the model. This prevents overclaiming ACMG 5-tier exact-match.

## Endpoints (all clean; safety/calibration axes are primary, 5-tier is not)
| model | cond | 3-class | actionable-binary | benign-conc | overcall | DANGEROUS | abstention | fabricated-CV | replicate-agree | assign-agree |
|---|---|---|---|---|---|---|---|---|---|---|
| gpt-5.2 | free | 78% | 82% | 95% | 1% | 1% | 18% | -- | 76% | 83% |
| gpt-5.2 | reason | 74% | 82% | 93% | 1% | 1% | 14% | -- | 77% | 52% |
| gpt-5.2 | exec | 75% | 79% | 92% | 1% | 1% | 19% | 17% | 65% | 61% |
| sonnet-4.5 | free | 79% | 92% | 94% | 1% | 1% | 8% | -- | 96% | 88% |
| sonnet-4.5 | reason | 78% | 97% | 93% | 6% | 2% | 1% | -- | 97% | 100% |
| sonnet-4.5 | exec | 77% | 92% | 93% | 3% | 1% | 6% | 0% | 81% | 91% |
| gemini-flash | free | 64% | 47% | 94% | 2% | 1% | 40% | -- | 37% | 23% |
| gemini-flash | reason | 79% | 99% | 92% | 2% | 1% | 2% | -- | 91% | 74% |
| gemini-flash | exec | 59% | 35% | 90% | 1% | 0% | 47% | 13% | 65% | 42% |

## Where apparent errors originate (the five claims)
1. **Dangerous errors:** already low and model-invariant. Pathogenic<->Benign misclassification is
   0-2% in every cell; benign concordance 90-95%. The safety layer is solved across models/conditions.
2. **Fabricated evidence:** real, model-dependent, neutralised by execution. In skill_execution models
   invent ClinVar evidence they were never shown (gpt-5.2 17%, gemini-flash 13%, sonnet 0%); the
   execution layer strips it before deterministic classification.
3. **P/LP disagreement:** mostly combiner-threshold dependent. 100% of truth=Pathogenic variants the
   Richards rule capped at Likely Pathogenic (556/556) score Pathogenic under the Tavtigian points
   combiner. The models assigned enough evidence; the rule combiner capped them. (Decomposition:
   exp1_points_decomposition.md.) 5-tier exact is identical under both combiners (50% vs 50%) because
   the choice moves errors across the P/LP line rather than removing them.
4. **VUS residuals:** the true evidence-acquisition gap. ~19% of truth=Pathogenic variants remain VUS
   even under points: the model could not assign enough non-ClinVar evidence (consequence+AF) to reach
   a definitive call. This is the genuine upstream frontier (VUS->definitive direction).
5. **Weak-model gains:** the skill scaffolds weaker models most strongly. gemini-flash free->skill_reasoning:
   actionable detection 47%->99%, replicate agreement 37%->91%, assignment agreement 23%->74%,
   abstention 40%->2%. Strong models are already near-ceiling in free mode, so the skill adds little.
   The scaffold's value scales INVERSELY with model capability (infrastructure-like behaviour).

Also: skill_execution is the SAFEST arm, not the most accurate (a weak model whose fabrications are
stripped falls back to VUS); execution's contribution is safety, auditability and determinism.

## SUPERSEDED
The earlier interpretation that "the Pathogenic->Likely-Pathogenic shift is the evidence-acquisition gap
quantified" (pilot v1 verdict, and an earlier draft of this file) is SUPERSEDED by the points-combiner
decomposition: that specific shift is combiner-threshold dependent, not evidence deprivation. The pilot
v1 verdict (exp1_pilot_verdict.md) is also superseded as a contaminated run (Gemini lost to Google quota).

## Before scaling to 6,929
1. Capture full per-code provenance: code + strength + source + rationale (currently code+strength only;
   without source, large-scale execution is not audit-complete and clinvar-sourced PS1/PM5 cannot be
   re-stripped). [implemented for future runs]
2. Report safety/calibration/assignment endpoints with BOTH combiners shown; do not headline 5-tier exact.
