# ClawBench Exp 1 — pilot endpoints

**Primary claim (validity/safety, NOT raw accuracy):** skill execution improves validity, auditability and safety by preventing unsupported or circular evidence from entering the classification path, even when this increases abstention to VUS. In clinical genomics, safe uncertainty beats confident hallucination.

**Success hierarchy (judge in this order; accuracy is fifth):**
1. dangerous misclassification (Pathogenic<->Benign) decreases
2. fabricated evidence decreases or becomes harmless (stripped before execution)
3. between-run variance collapses (replicate agreement -> 1, acc std -> 0)
4. abstention increases appropriately
5. label concordance improves

_Caveat: 'label concordance' is agreement with the ClinVar truth class, NOT validated accuracy. Criteria-level concordance (criteria F1) needs a gold ACMG-criteria reference we do not yet have, so it appears only where available._

## claude-sonnet-4-5

| condition | label conc | criteria F1 | DANGEROUS | abstention | fabricated ClinVar | replicate agree | acc std | fmt-fail | infra-fail | n |
|---|---|---|---|---|---|---|---|---|---|---|
| skill_execution | 20.0% | -- | 0.0% | 100.0% | 0.0% | 100.0% | 0.000 | 0.0% | 0.0% | 150 |

## gemini-2.5-flash

| condition | label conc | criteria F1 | DANGEROUS | abstention | fabricated ClinVar | replicate agree | acc std | fmt-fail | infra-fail | n |
|---|---|---|---|---|---|---|---|---|---|---|
| skill_execution | 18.5% | -- | 0.0% | 100.0% | 34.7% | 100.0% | 0.043 | 0.0% | 0.0% | 150 |

## gpt-5.2

| condition | label conc | criteria F1 | DANGEROUS | abstention | fabricated ClinVar | replicate agree | acc std | fmt-fail | infra-fail | n |
|---|---|---|---|---|---|---|---|---|---|---|
| skill_execution | 20.8% | -- | 0.0% | 98.7% | 13.3% | 96.0% | 0.009 | 0.0% | 0.0% | 150 |
