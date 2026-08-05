# Corpus QA Benchmark

This benchmark queries the NVIDIA RAG Server directly. It does not open or
automate either frontend. The command-line script calls `/v1/search` and the
streaming `/v1/generate` endpoint, then compares the returned retrieval results
and answer against each corpus's annotations.

## Supported corpora

- `enterprise_v2`: English, Chinese and Malay authored questions, canonical
  answers, and authoritative/supporting/stale document annotations.
- `rag_playbook`: English and Chinese authored questions, Chinese reference
  answers, and document plus PDF-page annotations.

The script does not manufacture translations. Requesting a language absent
from a dataset fails explicitly instead of silently weakening the benchmark.

## Smoke tests

Run one base question in every authored Enterprise v2 query language:

```bash
python3 scripts/benchmark_corpus_qa.py \
  --dataset enterprise_v2 \
  --collection enterprise-corpus-v2 \
  --query-languages en zh ms \
  --limit 1 \
  --no-judge
```

Run one playbook question in English and Chinese, including the local semantic
judge:

```bash
python3 scripts/benchmark_corpus_qa.py \
  --dataset rag_playbook \
  --collection rag-playbook-pdfs \
  --query-languages en zh \
  --limit 1
```

## Sampled and full runs

```bash
python3 scripts/benchmark_corpus_qa.py \
  --dataset enterprise_v2 \
  --collection enterprise-corpus-v2 \
  --query-languages en zh ms \
  --sample-size 100 \
  --seed 1135 \
  --reranker on \
  --query-rewriting off

python3 scripts/benchmark_corpus_qa.py \
  --dataset rag_playbook \
  --collection rag-playbook-pdfs \
  --query-languages en zh \
  --reranker on \
  --query-rewriting off
```

Use `--modes retrieval` for a fast retrieval-only run. Use
`--resume-dir <result-directory>` to continue an interrupted run without
repeating successful samples. `--question-ids Q-00001 Q-00042` selects exact
questions and `--limit N` limits base questions before language expansion.
`--sample-size N --seed S` draws a reproducible random sample before language
expansion; therefore 100 Enterprise base questions with `en zh ms` produce 300
query instances.

## Metrics

Retrieval metrics include gold-document recall, authoritative-document recall,
MRR and, where available, PDF-page recall. The default assumes NV-Ingest page
metadata is zero-based and converts it to one-based PDF page numbers; override
this with `--retrieved-page-base 1` if the deployment already returns one-based
pages.

Generation metrics include Unicode-aware sequence F1, Chinese character-bigram
F1, annotated answer-value matching, TTFT, total latency, truncation and visible
reasoning leakage. The optional local LLM judge evaluates correctness,
faithfulness, completeness, relevance and answer-language adherence across
languages.

Playbook English answers are compared semantically against Chinese references.
Their lexical F1 is diagnostic only and must not be interpreted as English
answer accuracy.

The current generator and judge use the same local model. Reports record this
self-judge limitation; judge scores are useful for triage but are not an
independent accuracy claim. Audit a stratified sample manually before presenting
results to customers.

Each result directory contains `config.json`, resumable `responses.jsonl`,
`failures.jsonl`, `report.json` and grouped `summary.csv`. Summary groups include
query language, source-document language and document-to-query language pairs.
