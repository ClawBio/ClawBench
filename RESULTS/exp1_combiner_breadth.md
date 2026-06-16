# ClawBench Exp 1 — combiner-sensitivity breadth (experiment 1)

Per-(variant,model) layer attribution from skill_execution. Tests whether `combiner_sensitive`
is a LoF special case or a general architectural layer. Acquisition is NOT measured here
(evidence was provided); these layers are safety, assignment, sufficiency, and combiner threshold.

| consequence group | n | combiner_sensitive | evidence_insufficient | assignment_unstable | safety_clean |
|---|---|---|---|---|---|
| LoF | 501 | 74% | 18% | 34% | 99% |
| missense | 195 | 6% | 55% | 20% | 100% |
| other | 147 | 0% | 0% | 38% | 100% |

## combiner-sensitive transitions (rule -> points), by group
- LoF: {'Uncertain Significance -> Likely Benign': 4, 'Uncertain Significance -> Likely Pathogenic': 17, 'Likely Pathogenic -> Pathogenic': 349, 'Uncertain Significance -> Pathogenic': 1}
- missense: {'Uncertain Significance -> Likely Benign': 11}

## Verdict
Combiner-sensitivity is LARGELY a LoF / Tier-A phenomenon (the PVS1+PM2 = 10-point boundary).
In rare missense it is minor (~7%) and at the VUS<->Likely-Benign boundary, not Pathogenic/LP.
The dominant layer for missense is EVIDENCE INSUFFICIENCY (~72%): consequence+AF is not enough
to classify missense, pointing to acquisition/sufficiency as the real frontier there. Different
variant classes have different dominant uncertainty layers: LoF -> combiner threshold;
missense -> evidence sufficiency. Safety is clean everywhere (~100%).
=> Do NOT split a standalone combiner-sensitivity paper: breadth shows it is a LoF-specific
   result, a paragraph in Paper 1, not a general phenomenon.