# RAGBench Accuracy Benchmark

This harness evaluates the currently deployed NVFP4 Nemotron model and NVIDIA
RAG pipeline on deterministic samples from `galileo-ai/ragbench`.

The default pilot uses 100 test questions from each of `emanual`, `techqa`,
`cuad`, `finqa`, and `hotpotqa`. Documents are deduplicated within each subset
and ingested into a separate collection.

## Prepare

```bash
python3 scripts/prepare_ragbench.py
```

Generated data is stored under `benchmarks/ragbench/data/`.

## Ingest

The first run should replace any old benchmark collections:

```bash
python3 scripts/benchmark_ragbench.py ingest --replace
```

Subsequent runs can reuse those collections by omitting `--replace`.

## Smoke Test

```bash
python3 scripts/benchmark_ragbench.py run --limit 2
```

## Full NVFP4 Run

```bash
python3 scripts/benchmark_ragbench.py run
```

The accuracy run defaults to 2,048 generated tokens so Nemotron can complete
its reasoning and still emit a final answer. Truncation is reported explicitly.
The report also flags responses that appear to expose reasoning in user-facing
content. Reference token F1 is diagnostic rather than a standalone accuracy
score, especially when reasoning leakage is present.

Each result directory contains:

- `config.json`: immutable run settings and model identity.
- `responses.jsonl`: one resumable record per question.
- `report.json`: aggregate metrics by subset and across the run.
- `summary.csv`: compact comparison table.

Use `--resume-dir <existing-result-directory>` to continue an interrupted run.

## Interpretation

Retrieval is scored using RAGBench's annotated relevant sentences and their
source documents. Generation includes token F1 against the supplied response
as a secondary diagnostic. Add `--judge` to request local model scores for
correctness, faithfulness, completeness, and answer relevance.

The optional local judge uses the same NVFP4 model as the generator. Smoke tests
showed self-judge inconsistencies, so it is disabled by default and its scores
must not be presented as independent accuracy. Review a stratified output
sample before presenting answer-quality claims.

RAGBench stores extracted text rather than original source files. This harness
does not evaluate PDF parsing, OCR, image understanding, or preservation of
original table layout.
