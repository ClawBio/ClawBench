# ClawBench Exp 1 — model training-cutoff evidence (Tier 1)

Retrieval date: 2026-06-15. Method: per-provider primary-source research (model cards, provider API
docs/system cards), cross-checked. Blinding rule: use the LATEST documented cutoff (the training-data
cutoff where a provider also publishes an earlier "reliable knowledge" cutoff), converted to the
conservative end-of-period ISO date (latest plausible date the model could have trained on data).

## Confirmed cutoffs

| Model | Release | Cutoff (blinding) | Stated as | Confidence | Primary source |
|---|---|---|---|---|---|
| **GPT-5.2** | 2025-12-11 | **2025-08-31** | "Aug 31, 2025 knowledge cutoff" | high | OpenAI API model page (developers.openai.com/api/docs/models/gpt-5.2) |
| Claude Opus 4 | 2025-05-22 | 2025-03-31 | "trained on data as of March 2025" (System Card §1.1.1) | high | Anthropic Claude 4 System Card (PDF) |
| Claude Sonnet 4 | 2025-05-22 | 2025-03-31 | "trained on data as of March 2025" (System Card §1.1.1) | high | Anthropic Claude 4 System Card (PDF) |
| Gemini 2.5 Flash | 2025-04-17 | 2025-01-31 | "knowledge cutoff … January 2025" | high | Google DeepMind Gemini 2.5 Flash Model Card (PDF) |
| DeepSeek-V3 | 2024-12-26 | 2024-07-31 | "knowledge cutoff is July 2024" (deployed system prompt) | medium | arXiv:2412.19437 (paper); cutoff is a self-report, no official doc |
| Mistral Large 2 (2407) | 2024-07-24 | 2024-07-24 | undocumented; release date as upper bound | low | HF model card mistralai/Mistral-Large-Instruct-2407 |
| GPT-4.1 | 2025-04-14 | 2024-06-01 | "Jun 01, 2024 knowledge cutoff" | high | OpenAI API model page (developers.openai.com/api/docs/models/gpt-4.1) |
| o3 | 2025-04-16 | 2024-06-01 | "Jun 01, 2024 knowledge cutoff" | high | OpenAI API model page (developers.openai.com/api/docs/models/o3) |
| o4-mini | 2025-04-16 | 2024-06-01 | "Jun 01, 2024 knowledge cutoff" | high | OpenAI API model page (developers.openai.com/api/docs/models/o4-mini) |

## Boundary and reviewer posture

- **Effective blinding boundary = the latest confirmed cutoff = GPT-5.2 @ 2025-08-31**, a HIGH-confidence, verbatim, primary-source value. The slice's validity rests on this single certain date.
- The two non-high-confidence cutoffs (DeepSeek-V3 medium/self-report; Mistral Large 2 low/undocumented) are both **2024-07**, ~13 months *below* the boundary. Their uncertainty therefore **cannot affect** the blinding bound: even if their true cutoffs were months later than stated, they would remain far below 2025-08-31. This removes the usual "your weakest cutoff is unsourced" attack.
- For the two undocumented/self-reported models we use the conservative latest-plausible upper bound (release date for Mistral; stated July 2024 for DeepSeek), which over-blinds rather than under-blinds.
- Caveat to disclose: the Anthropic System Card PDF could not be text-extracted in-session; the "March 2025" training date rests on a prior fetch + secondary corroboration + Anthropic's documented two-cutoff convention. It is the second-latest cutoff (2025-03-31) and still below the boundary.

Full machine-readable research record: `RESULTS/.model_cutoffs_research.json`.
