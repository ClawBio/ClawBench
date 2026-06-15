# ClawBench Exp 1 — held-out ClinVar slice

**Foundation:** We constructed a temporally blinded ClinVar held-out set in which labels post-date model cutoffs and are segregated from interpretive evidence.

## Construction
- effective cutoff: **2025-11-29** (max model cutoff + 90-day safety margin)
- minimum review stars: 2
- content hash (immutable manifest): `8d745d32ad8a377f05022174f80041d0f237aa24fc5c1dcb87fcebe16c242c66`

## Counts
- candidates considered: 166437
- **held out: 6929**  (reclassified subset: 206)

| excluded reason | n |
|---|---|
| pre_cutoff | 159300 |
| below_min_stars | 0 |
| unusable_label | 0 |
| missing_or_ambiguous_date | 208 |
| malformed | 0 |

## Blinding headroom (days from each model cutoff to the earliest held-out label)
- earliest held-out label first-available: **2025-11-30**
- all labels post-date all model cutoffs: **True**

| model | cutoff | headroom (days) |
|---|---|---|
| gpt-5.2 | 2025-08-31 | 91 |
| claude-opus-4 | 2025-03-31 | 244 |
| claude-sonnet-4 | 2025-03-31 | 244 |
| gemini-2.5-flash | 2025-01-31 | 303 |
| deepseek-v3 | 2024-07-31 | 487 |
| mistral-large-2 | 2024-07-24 | 494 |
| gpt-4.1 | 2024-06-01 | 547 |
| o3 | 2024-06-01 | 547 |
| o4-mini | 2024-06-01 | 547 |

## By review stars
| stars | n |
|---|---|
| 3 | 536 |
| 2 | 6393 |

## By classification
| class | n |
|---|---|
| Benign | 3852 |
| Likely Benign | 1941 |
| Uncertain Significance | 778 |
| Likely Pathogenic | 231 |
| Pathogenic | 127 |

## Top genes (2014 total)
| gene | n |
|---|---|
| MYOC | 152 |
| COL27A1 | 41 |
| FBN3 | 39 |
| PCLO | 33 |
| FASN | 31 |
| GCK | 30 |
| LAMA5 | 28 |
| MYO18B | 28 |
| PIK3CD | 28 |
| TTN | 28 |
| ADAMTS18 | 27 |
| DIP2C | 27 |
| RYR3 | 27 |
| ARHGEF18 | 26 |
| SORL1 | 26 |
| BMPR2 | 25 |
| HTT | 25 |
| MYH7B | 24 |
| KMT2C | 22 |
| C2CD3 | 21 |
| ABCA4 | 20 |
| COL18A1 | 20 |
| DYSF | 20 |
| HNF1A | 20 |
| CARD8 | 19 |

## Reclassification transitions
- reclassified held-out variants: **206**

| transition | n |
|---|---|
| Uncertain Significance -> Likely Benign | 66 |
| Uncertain Significance -> Likely Pathogenic | 47 |
| Likely Benign -> Uncertain Significance | 20 |
| Uncertain Significance -> Pathogenic | 18 |
| Uncertain Significance -> Benign | 16 |
| Likely Pathogenic -> Uncertain Significance | 14 |
| Pathogenic -> Uncertain Significance | 13 |
| Benign -> Uncertain Significance | 5 |
| Pathogenic -> Benign | 2 |
| Likely Pathogenic -> Benign | 2 |
| Likely Pathogenic -> Likely Benign | 1 |
| Pathogenic -> Likely Benign | 1 |
| Benign -> Pathogenic | 1 |
