# DGX Spark Ingestion Benchmark Results

Run date: 2026-07-16

Hardware: DGX Spark, 128 GB unified memory

Configuration:

- NVIDIA RAG Blueprint with local ARM64 services
- NV-Ingest 26.3.0
- Ray 2.53.0
- One file per asynchronous task
- 0.5-second status polling
- Query-only LLM, reranker, RAG API, and frontend stopped
- Summarization disabled
- Conservative NV-Ingest concurrency settings from `.env.dgx-spark`

## Standard Supported-Format Run

The run ingested 44 documents and 100 page-equivalents in 131.311 seconds of
wall-clock time. All 44 documents succeeded. The blended wall-clock rate was
45.69 page-equivalents per minute, including collection creation and a
0.5-second pause between tasks.

| Content class | Documents | Page-equivalents | Median per document | p90 per document | Pages/min |
|---|---:|---:|---:|---:|---:|
| Native-text PDF | 12 | 36 | 2.559 s | 2.569 s | 83.82 |
| Table-heavy PDF | 8 | 16 | 2.571 s | 2.584 s | 46.67 |
| Chart-heavy PDF | 8 | 16 | 2.575 s | 2.582 s | 46.62 |
| DOCX | 8 | 24 | 1.566 s | 1.575 s | 115.01 |
| PNG/JPEG image | 8 | 8 | 3.571 s | 3.597 s | 16.79 |

Indexed-content validation:

- Native PDF: 12 files, 36 text elements
- Table PDF: 8 files, 16 table and 16 text elements
- Chart PDF: 8 files, 16 chart and 16 text elements
- DOCX: 8 files, 8 text elements
- Images: 8 files, 16 OCR-derived title/paragraph elements

Memory available decreased from 81.36 GiB to 78.73 GiB during the run. No Ray
actors were killed, and disk utilization remained stable.

## Compatibility Findings

The smoke corpus exposed these current deployment limitations:

- Image-only scanned PDFs produced zero extracted text and no vectors. The
  default `APP_NVINGEST_EXTRACTPAGEASIMAGE=False` configuration does not route
  scanned PDF pages through page-image OCR.
- CSV is rejected by NV-Ingest 26.3.0 even though the existing
  `batch_ingestion.py` default extension list includes CSV.
- XLSX is rejected by NV-Ingest 26.3.0. Spreadsheet files need conversion to a
  supported representation such as PDF, HTML, JSON, or text before ingestion.

These are functional compatibility results, so no ingestion-speed estimate
should be quoted for scanned PDF, CSV, or XLSX until the relevant conversion or
OCR path is enabled and validated.

## Customer Estimate Guidance

Use content-mix estimates rather than one universal rate. For a supported
workload, estimate each class independently and add 20-30% operational
headroom. The measurements above are ingestion-only rates with query models
stopped; concurrent chat and ingestion must be benchmarked separately.

The generated QA prompts are in each corpus `questions.jsonl`. They verify
retrieval quality but are not included in the ingestion timing.
