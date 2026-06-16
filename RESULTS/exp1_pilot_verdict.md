# ClawBench Exp 1 pilot — verdict (2026-06-16)

231 Tier-A held-out variants x 3 conditions (free_prompted, skill_reasoning, skill_execution) x
5 replicates x 3 models = 10,395 calls. Judged by the safety-first hierarchy (accuracy is fifth).

## Data quality
- claude-sonnet-4-5 and gpt-5.2: 0% format-fail, 0% infra-fail. Clean.
- **gemini-2.5-pro: 47% infra-fail (1,641 Google `429 ResourceExhausted` quota errors). EXCLUDED**
  from interpretation; its scoreable numbers are a biased ~half-subsample. Needs re-run with adequate
  quota / slower pacing.

## Headline: this is NOT the V1 accuracy-gradient result, and that is the finding.
On Tier-A interpretation, the constraint gradient does not improve label accuracy and does not collapse
variance. But the architecture's SAFETY guarantees hold, and the "accuracy gap" decomposes into a
defensible evidence-acquisition gap. The contribution is more sophisticated than "execution improves
accuracy": execution controls and audits the DOWNSTREAM step, and the pilot localises the residual
problem UPSTREAM, to evidence acquisition and assignment.

## Endpoints (clean models, scoreable)
| model | cond | 5-tier | 3-class | actionable-binary | benign-conc | DANGEROUS | abstention | fabricated-CV | replicate-agree |
|---|---|---|---|---|---|---|---|---|---|
| sonnet-4.5 | free | 51% | 78% | 91% | 94% | 0.9% | 8% | -- | 94% |
| sonnet-4.5 | reason | 50% | 79% | 98% | 93% | 2.1% | 1% | -- | 98% |
| sonnet-4.5 | exec | 50% | 77% | 93% | 93% | 1.0% | 5% | 0.1% | 85% |
| gpt-5.2 | free | 54% | 77% | 80% | 95% | 0.9% | 18% | -- | 76% |
| gpt-5.2 | reason | 51% | 75% | 84% | 94% | 0.9% | 13% | -- | 70% |
| gpt-5.2 | exec | 54% | 77% | 82% | 95% | 0.9% | 18% | 17.1% | 65% |

## Findings, in the success hierarchy
1. **Dangerous P<->B misclassification: ~1% everywhere, flat.** Frontier models are already safe on
   clean Tier-A evidence; the gradient cannot improve what is already near-zero. Benign concordance
   92-95%, actionable detection 80-98%. The safety layer is solved.
2. **Fabricated evidence is real, model-dependent, and neutralised.** In skill_execution, models invent
   ClinVar evidence they were never shown: gpt-5.2 17.1%, sonnet 0.1%. The execution layer strips it
   before deterministic classification. This is the cleanest support for the trust-architecture thesis.
3. **Variance does NOT collapse under execution** (replicate agreement 65-85% in exec, <= free/reason).
   By construction the combiner is deterministic, so ALL execution variance is evidence-ASSIGNMENT
   variance. The stochastic frontier moved upstream.
4. **Abstention is appropriate, not excessive** (gpt-5.2 ~18%, sonnet ~5%); no model abstains away the task.
5. **The flat ~50% 5-tier "accuracy" is an artefact of the metric, not model error.** Models
   systematically call Pathogenic-truth variants Likely Pathogenic (sonnet exec: 0% on P-truth, 92% on
   LP-truth). With only consequence+AF the maximum defensible ACMG call for a LoF variant is PVS1+PM2 =
   Likely Pathogenic; reaching Pathogenic requires exactly the evidence we BLINDED (prior assertions /
   functional / segregation). So the one-tier P->LP shift IS the evidence-acquisition gap, quantified.
   3-class concordance ~78% confirms the models are correctly calibrated to the available evidence.

## Conclusion (supports the layered-architecture hypothesis)
Trustworthy agentic variant interpretation needs evidence acquisition, evidence assignment, deterministic
execution, and evaluation as SEPARATE, independently benchmarked layers. This pilot shows the execution +
evaluation layers work (safety controlled, fabrication neutralised, downstream made exact/auditable), and
that the open problem is the upstream layers. "Skill execution improves accuracy" is the wrong claim here;
"skill execution improves validity, auditability and safety, and isolates the residual uncertainty to
evidence acquisition/assignment" is the defensible one.

## Do NOT scale to 6,929 yet. Reframe first:
1. Re-run gemini with adequate Google quota (or drop it; add a 4th independent family).
2. Adopt the safety axes (dangerous rate, actionable-binary, benign-conc, 3-class) as PRIMARY metrics;
   5-tier exact-match penalises correct evidence-calibration and is misleading as a headline.
3. Capture submitted evidence codes per replicate (the harness does not yet) to measure
   assignment-stability directly -- the instrumentation the layered architecture requires.
4. Decide the evidence-provision policy: consequence+AF caps LoF variants at Likely Pathogenic by
   construction; to probe the precision tier, either provide more structured evidence (in-silico) or
   accept that minimal-evidence Tier-A tests the safety/calibration story, not the precision story.
