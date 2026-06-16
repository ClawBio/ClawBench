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
| free_prompted | 50.6% | -- | 0.9% | 8.1% | -- | 96.1% | 0.006 | 0.0% | 0.0% | 1155 |
| skill_reasoning | 50.1% | -- | 2.2% | 1.4% | -- | 97.0% | 0.002 | 0.0% | 0.0% | 1155 |
| skill_execution | 49.3% | -- | 1.0% | 5.7% | 0.0% | 80.5% | 0.005 | 0.0% | 0.0% | 1155 |

## gemini-2.5-flash

| condition | label conc | criteria F1 | DANGEROUS | abstention | fabricated ClinVar | replicate agree | acc std | fmt-fail | infra-fail | n |
|---|---|---|---|---|---|---|---|---|---|---|
| free_prompted | 47.9% | -- | 1.0% | 40.3% | -- | 36.8% | 0.008 | 0.0% | 0.0% | 1155 |
| skill_reasoning | 51.3% | -- | 0.5% | 2.4% | -- | 91.3% | 0.005 | 0.0% | 0.0% | 1155 |
| skill_execution | 48.2% | -- | 0.5% | 46.6% | 12.6% | 65.0% | 0.027 | 0.0% | 0.0% | 1155 |

## gpt-5.2

| condition | label conc | criteria F1 | DANGEROUS | abstention | fabricated ClinVar | replicate agree | acc std | fmt-fail | infra-fail | n |
|---|---|---|---|---|---|---|---|---|---|---|
| free_prompted | 54.5% | -- | 0.9% | 17.7% | -- | 76.2% | 0.007 | 0.0% | 0.0% | 1155 |
| skill_reasoning | 49.4% | -- | 0.9% | 14.2% | -- | 77.1% | 0.011 | 0.0% | 0.0% | 1155 |
| skill_execution | 52.7% | -- | 0.5% | 19.3% | 17.2% | 64.9% | 0.008 | 0.0% | 0.0% | 1155 |
