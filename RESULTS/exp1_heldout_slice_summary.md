# ClawBench Exp 1 — held-out ClinVar slice

**Foundation:** We constructed a temporally blinded ClinVar held-out set in which labels post-date model cutoffs and are segregated from interpretive evidence.

## Construction
- effective cutoff: **2025-11-28** (max model cutoff + 180-day safety margin)
- minimum review stars: 2
- content hash (immutable manifest): `7795edc03a47741638c54ddcbe3ea9784e54220252f28aa3a180adf24996f0d0`

## Counts
- candidates considered: 100104
- **held out: 6941**  (reclassified subset: 207)

| excluded reason | n |
|---|---|
| pre_cutoff | 92955 |
| below_min_stars | 0 |
| unusable_label | 0 |
| missing_or_ambiguous_date | 208 |
| malformed | 0 |

## Blinding headroom (days from each model cutoff to the earliest held-out label)
- earliest held-out label first-available: **2025-11-29**
- all labels post-date all model cutoffs: **True**

| model | cutoff | headroom (days) |
|---|---|---|
| claude-opus-4 | 2025-03-01 | 273 |
| claude-sonnet-4 | 2025-03-01 | 273 |
| gpt-5.2 | 2025-06-01 | 181 |
| gpt-4.1 | 2024-06-01 | 546 |
| o3 | 2024-12-01 | 363 |
| o4-mini | 2024-12-01 | 363 |
| gemini-2.5-flash | 2025-01-01 | 332 |
| deepseek-v3 | 2024-07-01 | 516 |
| mistral-large-2 | 2024-07-01 | 516 |

## By review stars
| stars | n |
|---|---|
| 3 | 542 |
| 2 | 6399 |

## By classification
| class | n |
|---|---|
| Benign | 3854 |
| Likely Benign | 1942 |
| Uncertain Significance | 781 |
| Likely Pathogenic | 235 |
| Pathogenic | 129 |

## Top genes (2015 total)
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
- reclassified held-out variants: **207**

| transition | n |
|---|---|
| Uncertain Significance -> Likely Benign | 66 |
| Uncertain Significance -> Likely Pathogenic | 48 |
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
