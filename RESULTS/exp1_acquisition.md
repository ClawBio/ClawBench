# ClawBench Exp 1 — Acquisition arm (oracle, single model)

Model: **claude-sonnet-4-5**. 27 rare missense (Tier-B), 24 definitive + VUS controls. Condition A = consequence+AF; Condition B = oracle non-ClinVar evidence (VEP/REVEL/AlphaMissense/CADD; calibrated PP3/BP4 per Pejaver 2022). Same frozen truth, same scorer, same attribution. 5 replicates/arm.

## Primary endpoint: evidence_insufficient (definitive variants)
- Condition A (thin):     24/24 evidence_insufficient
- Condition B (enriched): 17/24 evidence_insufficient
- Resolution of thin-ei variants: 7/24 (29%)

## Ceiling vs realised (definitive)
- Resolvable at theoretical ceiling (PM2 moderate + calibrated PP3/BP4): 9/24
- Actually resolved by the model (enriched): 7/24

## thin -> enriched transitions (definitive)
- evidence_insufficient -> evidence_insufficient: 17
- evidence_insufficient -> resolved: 4
- evidence_insufficient -> combiner_sensitive: 2
- evidence_insufficient -> assignment_unstable: 1

## evidence_insufficient by truth class (thin -> enriched)
| truth | n | thin ei | enriched ei |
|---|---|---|---|
| Pathogenic | 6 | 6 | 6 |
| Likely Pathogenic | 6 | 6 | 6 |
| Likely Benign | 6 | 6 | 2 |
| Benign | 6 | 6 | 3 |

## Assignment-layer behaviour (enriched arm, code strengths)
- PM2: {'supporting': 101}
- PP3: {'moderate': 35, 'supporting': 33, 'strong': 10}
- BP4: {'supporting': 35}

## Strength-calibration arm (PM2 licensed at moderate per the 2015 combiner)
- PM2 strength shifted: enriched {'supporting': 101} -> calibrated {'moderate': 134}
- evidence_insufficient (definitive): enriched 17/24 -> calibrated 22/24
- recovered vs enriched (2): ['VCV000007957', 'VCV000007961']
- regressed vs enriched (7): ['VCV000038885', 'VCV000051085', 'VCV000133793', 'VCV000133973', 'VCV000197093', 'VCV000225921', 'VCV000239929']
- VUS controls overcalled: none

### enriched -> calibrated transitions (definitive)
- evidence_insufficient -> evidence_insufficient: 15
- resolved -> evidence_insufficient: 4
- evidence_insufficient -> resolved: 2
- combiner_sensitive -> evidence_insufficient: 2
- assignment_unstable -> evidence_insufficient: 1