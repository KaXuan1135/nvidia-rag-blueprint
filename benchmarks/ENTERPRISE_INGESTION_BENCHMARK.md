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

## Representative DGX Spark baseline

The first baseline used the generated 2.95 GB enterprise corpus and the local
NV-Ingest stack. TXT was measured across all 200 files. The other formats were
sampled with five files each so that a useful estimate was available before the
full-corpus run completed.

| Format | Sample | MB/min | Pages/min | Notes |
| --- | ---: | ---: | ---: | --- |
| TXT | 200 files | 0.877 | 3.437 | Full-format run |
| Markdown | 5 files | 0.977 | 3.836 | One page-equivalent per file |
| HTML | 5 files | 1.006 | 1.968 | One page-equivalent per file |
| JSON | 5 files | 0.921 | 1.803 | One page-equivalent per file |
| CSV | 5 files | 0.794 | 0.311 | Page rate means files, not physical pages |
| XLSX | 5 files | 0.356 | 0.287 | Page rate means workbooks, not sheets |
| DOCX | 5 files | 5.519 | 4.676 | Generated manifest counts one document equivalent |
| PPTX | 5 files | 1.840 | 6.239 | Manifest slide count |
| PDF | 5 files | 33.085 | 78.217 | Mixed native/scanned sample, 50 pages total |
| PNG | 5 files | 16.778 | 3.113 | One image per page-equivalent |
| JPG | 5 files | 5.288 | 4.526 | One image per page-equivalent |

Using these format-specific rates, the complete 2.95 GB corpus is initially
estimated at 809 minutes (about 13.5 hours). A planning range of 607-1,214
minutes (about 10.1-20.2 hours) is reported to account for content complexity,
warm-up, contention, and the small samples used for most formats.

The machine-readable baseline is at
`benchmarks/enterprise-ingestion-results/20260723-consolidated/report.json`.
Replace it with the completed full-corpus report before quoting a production
estimate to a customer.

## Resume and monitor

An interrupted run can safely continue by comparing filenames already present
in the collection:

```bash
python3 scripts/benchmark_enterprise_ingestion.py \
  --corpus-dir benchmarks/enterprise-corpus \
  --collection-name enterprise-corpus-benchmark \
  --resume
```

For a short representative run, add `--sample-per-format 5`. To inspect the
current persistent run:

```bash
tmux attach -t enterprise-ingestion
tail -f benchmarks/enterprise-ingestion-results/background/full-ingestion.log
```
