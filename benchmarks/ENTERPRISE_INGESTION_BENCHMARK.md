# Enterprise Ingestion Benchmark

The benchmark ingests all selected formats into one collection, records every
batch, and reports throughput as MB/min, MiB/min, pages/min, and documents/min.

Before running a large OCR benchmark, stop inference-only services so that
NV-Ingest has enough unified memory:

```bash
sudo docker stop nim-llm-ms nemotron-ranking-ms rag-server rag-frontend
free -h
```

Run the full benchmark:

```bash
python3 scripts/benchmark_enterprise_ingestion.py \
  --corpus-dir benchmarks/enterprise-corpus \
  --collection-name enterprise-corpus-benchmark \
  --replace-collection
```

The script uses one collection and processes formats sequentially. It uses
larger batches for text and smaller batches for PDFs and images. Reports are
written below `benchmarks/enterprise-ingestion-results/<timestamp>/`.

Estimate another folder after the benchmark:

```bash
python3 scripts/estimate_ingestion_time.py \
  --folder /path/to/customer/documents \
  --benchmark-report benchmarks/enterprise-ingestion-results/<timestamp>/report.json \
  --json-output /tmp/ingestion-estimate.json
```

For the generated corpus, pass its manifest to use accurate page-equivalent
counts:

```bash
python3 scripts/estimate_ingestion_time.py \
  --folder benchmarks/enterprise-corpus/documents \
  --benchmark-report benchmarks/enterprise-ingestion-results/<timestamp>/report.json \
  --manifest benchmarks/enterprise-corpus/manifest.jsonl
```

The estimate is a planning aid. OCR quality, page complexity, charts, tables,
model warm-up, and batch-size changes can materially affect runtime.
