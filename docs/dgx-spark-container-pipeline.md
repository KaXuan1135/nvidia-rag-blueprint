# DGX Spark Container Pipeline

All containers communicate over the Docker network `nvidia-rag`. Host ports
are shown only where a user or administrator can access a service directly.

```mermaid
flowchart LR
    subgraph Clients["Clients"]
        Browser["Web browser"]
        Batch["Batch ingestion script"]
    end

    subgraph Application["Application containers"]
        Frontend["rag-frontend<br/>UI<br/>host :8090"]
        Rag["rag-server<br/>query orchestration<br/>host :8081"]
        Ingestor["ingestor-server<br/>collections and ingestion<br/>host :8082"]
    end

    subgraph Processing["Ingestion processing"]
        Redis[("redis<br/>task queue and status<br/>host :6379")]
        NvIngest["nv-ingest-ms-runtime<br/>Ray extraction pipeline<br/>host :7670<br/>Ray dashboard :8265"]
    end

    subgraph LocalModels["Local GPU model containers"]
        LLM["nim-llm-ms<br/>Nemotron 3 Nano<br/>host :8999"]
        Embed["nemotron-vlm-embedding-ms<br/>query and chunk embeddings<br/>host :9081"]
        Rank["nemotron-ranking-ms<br/>reranker<br/>host :1976"]
        Page["nemotron-page-elements<br/>layout detection<br/>host :8000"]
        Graphic["nemotron-graphic-elements<br/>chart and graphic detection<br/>host :8003"]
        Table["nemotron-table-structure<br/>table structure<br/>host :8006"]
        OCR["nemotron-ocr<br/>OCR text extraction<br/>host :8012"]
    end

    subgraph Storage["Persistent data containers"]
        ES[("elasticsearch<br/>chunks, metadata, vectors<br/>host :9200")]
        Seaweed[("seaweedfs<br/>source and citation assets<br/>S3 host :9010")]
    end

    Browser --> Frontend
    Batch -->|"upload documents"| Ingestor
    Frontend -->|"chat and search"| Rag
    Frontend -->|"collections and documents"| Ingestor

    Ingestor -->|"submit extraction job"| NvIngest
    Ingestor -.->|"optional summaries"| LLM
    Ingestor -.->|"optional task status"| Redis
    NvIngest <-->|"ingestion work queue"| Redis

    NvIngest -->|"PDF/image layout"| Page
    NvIngest -->|"charts and graphics"| Graphic
    NvIngest -->|"tables"| Table
    NvIngest -->|"scans and image text"| OCR
    NvIngest -->|"embed extracted chunks"| Embed
    NvIngest -->|"write vectors and metadata"| ES
    NvIngest -->|"write extracted assets"| Seaweed

    Rag -->|"embed user query"| Embed
    Rag -->|"dense or hybrid retrieval"| ES
    Rag -->|"rerank retrieved chunks"| Rank
    Rag -->|"load citation assets"| Seaweed
    Rag -->|"answer generation"| LLM
    Rag -.->|"optional query rewrite, reflection,<br/>filters, or agentic steps"| LLM
```

## Document Ingestion

```mermaid
sequenceDiagram
    actor User
    participant UI as rag-frontend
    participant API as ingestor-server
    participant Queue as Redis
    participant NV as nv-ingest-ms-runtime
    participant Extract as Extraction NIMs
    participant Embed as Embedding NIM
    participant ES as Elasticsearch
    participant S3 as SeaweedFS

    User->>UI: Select documents and collection
    UI->>API: POST documents
    API-->>UI: Task ID
    API->>NV: Submit extraction pipeline
    NV->>Queue: Queue and coordinate work
    opt PDF, scan, table, chart, or image
        NV->>Extract: Layout, table, graphic, or OCR inference
        Extract-->>NV: Structured extracted content
    end
    NV->>NV: Normalize and split into chunks
    NV->>Embed: Embed chunks
    Embed-->>NV: Dense vectors
    NV->>ES: Store chunks, vectors, and metadata
    NV->>S3: Store source and citation assets
    API-->>UI: Finished or failed status
```

CSV and XLSX files take a compatibility path in `ingestor-server`: their cells
are rendered as Markdown tables first, while their original filenames are
preserved. NV-Ingest then handles that Markdown as ordinary text.

## Question Answering

```mermaid
sequenceDiagram
    actor User
    participant UI as rag-frontend
    participant RAG as rag-server
    participant LLM as Nemotron LLM
    participant Embed as Embedding NIM
    participant ES as Elasticsearch
    participant Rank as Reranker NIM
    participant S3 as SeaweedFS

    User->>UI: Ask a question
    UI->>RAG: Generate request and selected collections
    opt Query rewriting enabled
        RAG->>LLM: Rewrite follow-up into a retrieval query
        LLM-->>RAG: Standalone query
    end
    RAG->>Embed: Embed retrieval query
    Embed-->>RAG: Query vector
    RAG->>ES: Search selected collection indexes
    ES-->>RAG: Candidate chunks
    RAG->>Rank: Rerank query and candidate chunks
    Rank-->>RAG: Top relevant chunks
    opt Citation assets required
        RAG->>S3: Load source images or document assets
        S3-->>RAG: Citation assets
    end
    RAG->>LLM: System prompt, history, question, and context
    LLM-->>RAG: Generated answer stream
    RAG-->>UI: Answer, citations, and metrics
    UI-->>User: Render response
```

## Container Roles

| Container | Main role |
|---|---|
| `rag-frontend` | Browser interface for chat, collections, and uploads |
| `rag-server` | Retrieval, reranking, prompt construction, and answer generation |
| `ingestor-server` | Collection APIs, upload validation, task orchestration, and status |
| `nv-ingest-ms-runtime` | Ray-based extraction, splitting, embedding, storage, and vector upload |
| `redis` | NV-Ingest work queue and optional asynchronous task/status backend |
| `elasticsearch` | Persistent document chunks, metadata, and vectors |
| `seaweedfs` | S3-compatible storage for source and citation assets |
| `nim-llm-ms` | Local answer generation and optional LLM-assisted pipeline stages |
| `nemotron-vlm-embedding-ms` | Embeddings for both ingested chunks and user queries |
| `nemotron-ranking-ms` | Relevance reranking after vector retrieval |
| Extraction NIMs | Page layout, graphics, table structure, and OCR processing |
