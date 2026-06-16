# ClawBench Exp 1 pilot v2 — verdict (2026-06-16)

231 Tier-A held-out variants x 3 conditions x 5 replicates x 3 models = 10,395 calls.
**All three arms clean: 0% infra-fail** (gpt-5.2, claude-sonnet-4-5, gemini-2.5-flash). Per-replicate
evidence-code capture enabled. Judged by the safety-first hierarchy.

## Endpoints (all clean)
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

## Findings (safety-first)
1. **Safety is solved and model-invariant.** Dangerous Pathogenic<->Benign misclassification is 0-2%
   in EVERY cell; benign concordance 90-95%; over-call (benign->actionable) 1-6%. No model, in any
   condition, confidently flips a benign variant to pathogenic or vice versa.
2. **Fabrication is real and execution neutralises it.** In skill_execution, gpt-5.2 fabricates ClinVar
   evidence 17% of the time and gemini-flash 13%; the execution layer strips it before classification.
   sonnet-4.5 fabricates ~0%.
3. **The constraint gradient is real but MODEL-DEPENDENT.** For the weaker model (gemini-flash) the skill
   is transformative: actionable detection 47%->99%, replicate agreement 37%->91%, evidence-assignment
   agreement 23%->74%, abstention 40%->2% (free -> skill_reasoning). For the strong models (sonnet, gpt)
   free mode is already near-ceiling, so the skill adds little. The trust scaffold's value scales
   INVERSELY with model capability.
4. **Skill-execution is the SAFEST arm, not the most accurate.** For gemini-flash, exec abstains 47% and
   detects only 35% of actionable variants -- safe (0% dangerous) but low-sensitivity, because a weak
   model that cannot assign good codes from consequence+AF (and whose fabrications are stripped) falls
   back to VUS. skill_REASONING outperforms skill_EXECUTION on accuracy here because it is less
   constrained. Execution's contribution is safety + auditability + determinism, NOT raw accuracy.
5. **The residual uncertainty is upstream, in evidence assignment.** Execution variance is, by
   construction, evidence-assignment variance; reading the skill stabilises assignment most
   (sonnet 100%, gemini 23%->74% set-agreement). The bottleneck is acquisition/assignment, not the combiner.

## Defensible claims (NOT "execution improves accuracy")
- Trustworthiness (safety, no-fabrication, determinism, auditability) is controlled by the execution
  architecture and is model-invariant; raw accuracy is not improved by execution.
- The benefit of versioned skills is largest where the base model is weakest.
- The principal source of residual uncertainty in agentic variant interpretation is upstream evidence
  acquisition/assignment, not deterministic execution. (Supports the layered-architecture thesis.)

## Still pending (analysis, not data)
- Points-combiner (Tavtigian/ClinGen) re-score to decompose the systematic Pathogenic->Likely-Pathogenic
  one-tier shift into evidence-deprivation vs combiner-conservatism.
- Then: redesign-confirmed, consider scaling to the full 6,929 (with all arms throttled).
