# NVIDIA RAG Blueprint on DGX Spark

This repository tracks NVIDIA's official RAG Blueprint and adds a cautious
single-device path for DGX Spark.

## Current phase

The DGX Spark profile builds the Blueprint UI, RAG server, ingestor server, and
NV-Ingest 26.3.0 from source as native ARM64 images. Elasticsearch, SeaweedFS,
and Redis use existing ARM64 images.

All content-bearing inference runs locally. Nemotron 3 Nano 30B A3B NVFP4
provides generation, query rewriting, filtering, summaries, and reflection.
The original Llama Nemotron VL embedding, reranking, page-element, graphic-
element, and table-structure models remain in local NIM services. Nemotron OCR
v1 is built from NVIDIA's public C++/CUDA and model source for ARM64, targeting
GB10 compute capability 12.1, and served through NV-Ingest's HTTP OCR contract.
This source-built OCR service is not an NVIDIA-supported ARM64 NIM release.

The profile replaces the upstream multi-GPU device assignments with a
single-GB10 configuration, smaller extraction batches, a 32K LLM context, and a
persistent NIM model cache. No `NVIDIA_API_KEY` is used at runtime.

## Prerequisites

- DGX Spark with at least 200 GB free disk space for images and model caches
- Docker Engine 24 or later, excluding the unsupported 29.5.x release
- Docker Compose 2.29.1 or later
- NVIDIA Container Toolkit
- Git LFS for the pinned Nemotron OCR checkpoints
- An NGC personal key with permission to pull the required NIM artifacts

Run the read-only host check:

```bash
./scripts/dgx-spark-check.sh
```

## Configure

```bash
cp .env.dgx-spark.example .env.dgx-spark
chmod 600 .env.dgx-spark
```

Edit `.env.dgx-spark` and add the NGC key. A build.nvidia.com
`NVIDIA_API_KEY` is not required because inference remains local.

If the host check says Docker is not reachable by the current account, also
set:

```text
DGX_SPARK_DOCKER_SUDO=true
```

Authenticate Docker to NVIDIA NGC once:

```bash
set -a
source .env.dgx-spark
set +a
if [[ "${DGX_SPARK_DOCKER_SUDO}" == "true" ]]; then
  echo "${NGC_API_KEY}" | sudo docker login nvcr.io -u '$oauthtoken' --password-stdin
else
  echo "${NGC_API_KEY}" | docker login nvcr.io -u '$oauthtoken' --password-stdin
fi
```

## Build the ARM64 images

Fetch the pinned NeMo Retriever and Nemotron OCR sources, download the pinned
OCR checkpoints, and build the native ARM64 application images:

```bash
./scripts/dgx-spark-build-arm64.sh
```

The first build downloads base images and compiles Python dependencies, so it
can take a substantial amount of time. The source is pinned to NeMo Retriever
`26.3.0` commit `b1aa9729809bd46c0b4f089ccd0ead946303eba3` under the ignored
`.sources/` directory. Nemotron OCR v1 is pinned to NVIDIA commit
`8657d08d3279f4864002d5fd3fdcd47ad8c96bcb`; its CUDA extension is compiled
for `sm_121`. The build does not start the application.

Pull the six local NIM images separately:

```bash
./scripts/dgx-spark-pull-models.sh
```

The model weights are cached in the persistent `rag-vol-nim-cache` volume when
the NIMs first start. Pulling images does not start containers.

## Spreadsheet ingestion

The DGX Spark build adds compatibility ingestion for `.csv` and `.xlsx` files.
Before submitting them to NV-Ingest, the ingestor renders worksheets as Markdown
tables while preserving the original spreadsheet filename for document listings
and citations. CSV encoding, multiple XLSX sheets, shared strings, inline strings,
sparse cells, booleans, and cached formula values are supported.

This is content extraction rather than Excel rendering. Cell formatting, charts,
macros, comments, embedded objects, and formulas without cached values are not
indexed. Export unusually complex workbooks to PDF when visual structure matters.

## Start

After the ARM64 build and NIM image pull succeed, start the complete local stack:

```bash
./scripts/dgx-spark-up.sh
```

The services are exposed at:

- Web UI: `http://<dgx-spark-host>:8090`
- RAG API: `http://<dgx-spark-host>:8081`
- Ingestion API: `http://<dgx-spark-host>:8082`

When connecting through VS Code Remote SSH, forward port `8090` in the Ports
panel and open `http://localhost:8090` locally.

Check status and health:

```bash
./scripts/dgx-spark-status.sh
curl http://localhost:8081/v1/health?check_dependencies=true
curl http://localhost:8082/v1/health?check_dependencies=true
```

Stop the application without deleting its named volumes:

```bash
./scripts/dgx-spark-down.sh
```

## Local-runtime verification

The configured runtime endpoints are Docker service names; no model client is
pointed at `integrate.api.nvidia.com` or `ai.api.nvidia.com`. The NGC key is
still passed to NIM containers so they can download entitled model artifacts.

Before describing a customer deployment as data sovereign:

1. Start once with network access so all model artifacts populate
   `rag-vol-nim-cache`.
2. Ingest and query a representative text, scanned, table-heavy, and
   chart-heavy document.
3. Restart with outbound network access blocked and repeat those tests.
4. Verify logs and network telemetry contain no attempted hosted inference.

The NIM image manifests must include Linux ARM64 support. Nemotron OCR is the
one explicit source-built exception because NVIDIA's supported OCR NIM requires
an x86 host. Validate its output against representative company documents
before treating this unsupported ARM64 port as production-ready.

## Upstream maintenance

The official NVIDIA repository is configured as the `upstream` Git remote.
Review release notes and merge deliberately rather than tracking `main`
automatically:

```bash
git fetch upstream --tags
git log --oneline HEAD..upstream/main
```
