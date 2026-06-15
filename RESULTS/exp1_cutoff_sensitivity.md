# ClawBench Exp 1 — cutoff sensitivity analysis (Tier 3)

Latest confirmed model cutoff (boundary): **2025-08-31** (GPT-5.2, high confidence). Held-out variants must have their current label first-available strictly after effective_cutoff = this boundary + margin.

Candidate superset (at margin 0): 166,437

| margin (days) | effective cutoff | held out | reclassified | earliest label | min headroom past latest cutoff |
|---|---|---|---|---|---|
| 0 | 2025-08-31 | 12,464 | 342 | 2025-09-01 | 1 |
| 30 | 2025-09-30 | 10,435 | 294 | 2025-10-01 | 31 |
| 90 | 2025-11-29 | 6,929 | 206 | 2025-11-30 | 91 |
| 180 | 2026-02-27 | 175 | 49 | 2026-03-01 | 182 |

Frozen manifest margin: **90 days** (sha256 `eca96b8ea6f25dc3…`)
