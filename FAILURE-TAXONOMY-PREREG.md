# Exp 2 calling-gradient failure taxonomy (PRE-REGISTERED 2026-06-19)

Registered BEFORE any free-prompted or skill-reasoning run has been scored. The skill_execution and
reference arms have qualified (HG002 chr20 F1 0.9906; HG001/HG003/HG005 in progress). This document
fixes the categories by which agent-authored calling runs will be judged, and the objective signal
that detects each, so failures are measured against pre-set definitions rather than explained after
the fact.

## Principle
Each calling run (one arm, one sample, one replicate) receives a SET of failure labels, not a single
verdict, mirroring the per-variant layer attribution of Exp 1. A run is "clean" only if it carries
none of the eight labels. The skill_execution and reference arms are expected to be clean by
construction (the pins and the validated wrapper guarantee it); the free-prompted and skill-reasoning
arms are expected to accumulate labels. Every label is derived from run artefacts (the emitted command,
the provenance manifest if any, the produced VCF, two-run comparison, and rtg vcfeval output) by a
deterministic classifier, classify_calling_run(); no label is assigned by narrative judgement.

## The eight categories

| # | Label | Definition | Objective detection signal | Severity |
|---|---|---|---|---|
| 1 | reference_build_error | Wrong reference build or contig naming relative to the truth (GRCh38, chr-prefixed) | Reference in the emitted command/VCF header is not the pinned GRCh38 analysis set, or VCF contigs do not match the truth coordinate system (vcfeval contig mismatch, or mass false negatives from a coordinate shift) | Critical (clinically dangerous) |
| 2 | container_version_error | Tools not run in digest-pinned containers, or mutable/wrong versions | Emitted command uses host tools, a `latest` or tag-only image, or no container engine; or provenance lacks resolved container digests | Critical (reproducibility + audit) |
| 3 | parameter_drift | Caller/aligner parameters deviate from the validated pinned set in ways that affect results | Diff of emitted parameters (aligner, caller, ploidy, filters, intervals) against the skill arm's pinned parameters; any result-affecting deviation | Major |
| 4 | missing_provenance | No provenance manifest recording versions, inputs, command, and checksums | No provenance.json (or equivalent) emitted for the run | Critical (audit) |
| 5 | non_reproducible | Re-running does not yield identical genotypes | repro_enforcer genotype-identical check on two independent runs returns not-identical; or structurally, unpinned versions so reproducibility is not guaranteed | Critical |
| 6 | accuracy_degradation | F1 materially below the qualified skill-arm baseline | rtg vcfeval F1 of the run vs GIAB truth (within the confident BED) is below (skill-arm F1 minus a pre-set margin of 0.02), i.e. roughly below 0.97 given the ~0.99 baseline | Major |
| 7 | incomplete_workflow | The pipeline does not complete FASTQ to VCF | No valid VCF produced, a required stage absent (alignment, dedup, calling), or non-zero exit | Critical |
| 8 | tool_selection_error | Tools chosen are inappropriate for the task (germline short-variant calling from short reads) | Emitted toolchain does not match the task, for example a somatic-only caller, an aligner unsuited to the data, or a tool that cannot emit the required output | Major |

## Mapping to the arms (the hypothesis being tested)
- skill_execution and reference: expected clean on all eight (pinned pipeline + Nextflow version,
  digest-resolved containers, provenance written, deterministic, F1 about 0.99, complete FASTQ to VCF,
  correct tools). This is the qualified foundation.
- free_prompted: the agent authors the command from its prior. Expected labels: container_version_error,
  missing_provenance, parameter_drift, often non_reproducible, sometimes reference_build_error,
  incomplete_workflow, tool_selection_error, with accuracy_degradation downstream.
- skill_reasoning: the agent configures after reading the skill specification. Expected to reduce some
  labels relative to free_prompted but not eliminate the pinning/provenance/reproducibility ones,
  because reading a specification is not the same as executing validated code.

## What this licenses the manuscript to claim
If the data match the hypothesis, the conclusion is not "free agentic workflows performed worse." It is
"agentic genomics is feasible at scale only when the agent operates through validated infrastructure,
and the failures of agent-authored workflows localise to specific, pre-registered categories
(reference, container, parameter, provenance, reproducibility, accuracy, completeness, tool choice)."
Exp 1 localises uncertainty in interpretation; Exp 2 localises failure in execution. Together:
trustworthiness in agentic genomics is achieved by identifying, measuring, and controlling the layers
where uncertainty and failure arise.

## Amendment 2026-06-20 (gradient arms, endpoint, equity)
Registered before any agent-arm run. Settles the gradient design and the primary endpoint.

The four arms:
- A. Free agent: the model receives the task plus sample metadata only (sample id, that it is GIAB
  GRCh38 germline short-variant calling on chr20, the FASTQ paths) and must propose the full FASTQ to
  VCF workflow. No skill, no template.
- B. Skill-reasoning agent: the model receives the ClawBio SKILL.md and must configure the workflow;
  it may not invoke the validated pinned wrapper directly.
- C. Skill-execution agent: the model invokes the validated ClawBio skill; pinned reference,
  containers, parameters and provenance are enforced. This is the qualified control.
- D. Reference control: a best-practice canonical nf-core/sarek configuration, hand-run.

Arms A and B EXECUTE the workflow the agent authored, in a sandbox (scratch dir on the external
volume, resource and time limits, no destructive or out-of-scope access), because the endpoint
requires measuring accuracy, reproducibility and execution completeness of what the agent produced.

Primary endpoint is NOT F1 alone. It is a per-run trustworthiness scorecard over five dimensions:
accuracy (rtg vcfeval F1 within the confident BED), reproducibility (genotype-identical re-run),
provenance (a complete manifest emitted), pinning (digest-pinned containers + pinned versions), and
failure-taxonomy cleanliness (the eight labels above; clean = none). A run is trustworthy only if it
is accurate AND reproducible AND provenance-complete AND pinned AND taxonomy-clean.

Hypothesis (falsifiable): free agents (A) may sometimes produce plausible VCFs, but will fail more
often on provenance, pinning, parameter drift, reproducibility, or execution completeness than the
skill arm. Skill-reasoning (B) reduces some failures but not the pinning/provenance/reproducibility
ones. Skill-execution (C) and reference (D) are clean across all five dimensions.

Equity: the "ancestry-invariant" claim is WITHDRAWN. Performance is reported descriptively, stratified
by GIAB sample ancestry, with per-ancestry precision and recall (not F1 alone, since F1 masked a
false-positive-rate gradient in the qualification). No equity claim is made from n=4.

Run order: run the gradient on ONE sample first (HG002 chr20) against this frozen taxonomy. Only if the
arms separate clearly do we expand to HG001/HG003/HG005, then to whole genome under benchmark
conditions (full-genome alignment, standard BQSR, replicates, confidence intervals).

## Measurement note
A classify_calling_run() module will implement these eight detectors against the run artefacts,
TDD'd on fixtures before the gradient runs, so the free-arm classification is mechanical and auditable.
Labels are reported per (arm, sample, replicate); the skill-arm clean baseline is the control.
This taxonomy is frozen as of the date above; any later category is an explicit amendment, dated.
