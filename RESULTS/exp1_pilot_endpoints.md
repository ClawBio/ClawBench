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
| free_prompted | 50.6% | -- | 0.9% | 8.2% | -- | 93.9% | 0.003 | 0.0% | 0.0% | 1155 |
| skill_reasoning | 50.3% | -- | 2.1% | 1.2% | -- | 98.3% | 0.002 | 0.0% | 0.0% | 1155 |
| skill_execution | 49.5% | -- | 1.0% | 5.2% | 0.1% | 85.3% | 0.004 | 0.0% | 0.0% | 1155 |

## gemini-2.5-pro

| condition | label conc | criteria F1 | DANGEROUS | abstention | fabricated ClinVar | replicate agree | acc std | fmt-fail | infra-fail | n |
|---|---|---|---|---|---|---|---|---|---|---|
| free_prompted | 61.6% | -- | 1.1% | 3.6% | -- | 59.5% | 0.033 | 0.0% | 47.3% | 1155 |
| skill_reasoning | 90.5% | -- | 1.0% | 3.1% | -- | 99.2% | 0.009 | 0.0% | 47.4% | 1155 |
| skill_execution | 85.4% | -- | 0.6% | 7.9% | 6.6% | 85.0% | 0.037 | 0.0% | 47.4% | 1155 |

## gpt-5.2

| condition | label conc | criteria F1 | DANGEROUS | abstention | fabricated ClinVar | replicate agree | acc std | fmt-fail | infra-fail | n |
|---|---|---|---|---|---|---|---|---|---|---|
| free_prompted | 53.5% | -- | 0.9% | 18.1% | -- | 75.8% | 0.012 | 0.0% | 0.0% | 1155 |
| skill_reasoning | 50.9% | -- | 0.9% | 13.4% | -- | 69.7% | 0.012 | 0.0% | 0.0% | 1155 |
| skill_execution | 54.1% | -- | 0.9% | 18.3% | 17.1% | 64.5% | 0.009 | 0.0% | 0.0% | 1155 |
