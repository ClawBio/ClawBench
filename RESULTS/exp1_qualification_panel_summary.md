# ClawBench Exp 1 — qualification panel v1

Stratifies the frozen held-out set by ACMG automatability so performance is read per tier; a drop in Tier C localises to evidence acquisition, not execution.

Source held-out manifest content_hash: `8d745d32ad8a377f05022174f80041d0f237aa24fc5c1dcb87fcebe16c242c66`

Tier rule: A: AF>=5% (BA1) or LoF consequence (PVS1). B: 1%<=AF<5% (BS1) or missense/inframe/protein-altering. C: synonymous/intronic/UTR/non-coding/underdetermined. ClinVar-assertion criteria (PS1/PM5/PP5/BP6) excluded (blinded in primary mode).

## Tiers

| Tier | N | % | expected ceiling |
|---|---|---|---|
| A | 894 | 12.9% | high |
| B | 2,906 | 41.9% | moderate |
| C | 3,129 | 45.2% | lower |

Total: 6,929; consequence unavailable (ClinVar VCF miss): 11

## Tier x classification

| Tier | Pathogenic | Likely Pathogenic | Uncertain Significance | Likely Benign | Benign |
|---|---|---|---|---|---|
| A | 74 | 63 | 42 | 9 | 706 |
| B | 44 | 155 | 660 | 364 | 1683 |
| C | 9 | 13 | 76 | 1568 | 1463 |

## Tier-A pilot (first run)

- N = 231 (per-class cap 60)
- class mix: {'Benign': 60, 'Likely Benign': 9, 'Likely Pathogenic': 60, 'Pathogenic': 60, 'Uncertain Significance': 42}
- reclassified included: 14
