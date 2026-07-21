# Ingestion Benchmark

This benchmark measures document ingestion only. It does not send RAG queries.

## Corpus

Generate the smoke corpus (20 documents, 42 page-equivalents):

```bash
python3 scripts/generate_ingestion_benchmark.py --profile smoke --force
```

Generate the larger standard corpus (about four times the smoke workload):

```bash
python3 scripts/generate_ingestion_benchmark.py --profile standard --force
```

The corpus includes native-text, scanned, mixed, table-heavy, and chart-heavy
PDFs, plus DOCX, XLSX, TXT, Markdown, CSV, PNG, and JPEG files. Facts are
deterministic so extraction and retrieval can be checked later.

Generated files:

- `corpus/manifest.json`: document class, size, page-equivalents, and QA data.
- `corpus/questions.jsonl`: manual questions and expected answers.

## Memory Preparation

For ingestion-only measurements, stop query-only services before running:

```bash
sudo docker stop nim-llm-ms nemotron-ranking-ms rag-server rag-frontend
```

Keep the ingestion API, NV-Ingest, Redis, Elasticsearch, SeaweedFS, embedding,
OCR, page-elements, graphic-elements, and table-structure services running.

Confirm there is comfortable memory headroom:

```bash
free -h
```

## Run

Use one file per asynchronous ingestion task for clear per-document timing:

```bash
python3 scripts/benchmark_ingestion.py \
  --corpus-dir benchmarks/ingestion/corpus \
  --collection-prefix ingestion-bench \
  --batch-size 1 \
  --poll-interval 2 \
  --pause-between-batches 2
```

Run selected classes during troubleshooting:

```bash
python3 scripts/benchmark_ingestion.py \
  --categories native_pdf text docx
```

Each category uses a fresh collection. Results are written under a timestamped
directory in `benchmarks/ingestion/results/`:

- `report.json`: configuration, task timelines, resource snapshots, and summary.
- `batches.csv`: flat per-batch timing data.

The primary customer-planning metric is page-equivalents per minute by content
class. Use repeated warm runs and report the slower p90 result with operational
headroom rather than quoting a single blended rate.
