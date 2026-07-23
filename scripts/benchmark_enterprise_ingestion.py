#!/usr/bin/env python3
"""Ingest a manifest corpus into one collection and benchmark each file format."""

from __future__ import annotations

import argparse
import csv
import json
import mimetypes
import shutil
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import median

import requests


MIME_TYPES = {
    ".csv": "text/csv",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".html": "text/html",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".json": "application/json",
    ".md": "text/markdown",
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".txt": "text/plain",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
FORMAT_ORDER = [
    ".txt", ".md", ".html", ".json", ".csv", ".xlsx",
    ".docx", ".pptx", ".pdf", ".png", ".jpg", ".jpeg",
]
DEFAULT_BATCH_SIZES = {
    ".txt": 100, ".md": 100, ".html": 50, ".json": 50, ".csv": 10,
    ".xlsx": 5, ".docx": 5, ".pptx": 5, ".pdf": 1,
    ".png": 2, ".jpg": 2, ".jpeg": 2,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-dir", default="benchmarks/enterprise-corpus")
    parser.add_argument("--collection-name", default="enterprise-corpus-benchmark")
    parser.add_argument("--results-dir", default="benchmarks/enterprise-ingestion-results")
    parser.add_argument("--ingestor-url", default="http://localhost:8082")
    parser.add_argument("--formats", nargs="*", help="Extensions to ingest, such as pdf png txt")
    parser.add_argument(
        "--sample-per-format",
        type=int,
        help="Only ingest the first N remaining files of each format",
    )
    parser.add_argument("--batch-size", type=int, help="Override all per-format batch sizes")
    parser.add_argument("--poll-interval", type=float, default=2)
    parser.add_argument("--timeout", type=int, default=21600)
    parser.add_argument("--pause-between-batches", type=float, default=1)
    parser.add_argument("--replace-collection", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--generate-summary", action="store_true")
    return parser.parse_args()


def snapshot() -> dict:
    memory = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, raw = line.split(":", 1)
        memory[key] = int(raw.strip().split()[0]) * 1024
    disk = shutil.disk_usage("/")
    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "memory_available_bytes": memory.get("MemAvailable", 0),
        "swap_free_bytes": memory.get("SwapFree", 0),
        "disk_free_bytes": disk.free,
    }


class Client:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()

    def request(self, method: str, path: str, **kwargs) -> dict:
        response = self.session.request(method, self.base_url + path, **kwargs)
        response.raise_for_status()
        return response.json() if response.content else {}

    def health(self) -> dict:
        return self.request("GET", "/v1/health", timeout=30)

    def collections(self) -> set[str]:
        data = self.request("GET", "/v1/collections", timeout=60)
        return {item["collection_name"] for item in data.get("collections", [])}

    def create_collection(self, name: str) -> None:
        self.request(
            "POST", "/v1/collection",
            json={"collection_name": name, "embedding_dimension": 2048, "metadata_schema": []},
            timeout=60,
        )

    def delete_collection(self, name: str) -> None:
        self.request("DELETE", "/v1/collections", json=[name], timeout=180)

    def document_names(self, collection: str) -> set[str]:
        data = self.request(
            "GET", "/v1/documents", params={"collection_name": collection}, timeout=120
        )
        return {
            (item.get("metadata") or {}).get("filename") or item.get("document_name")
            for item in data.get("documents", [])
            if (item.get("metadata") or {}).get("filename") or item.get("document_name")
        }

    def upload(self, collection: str, paths: list[Path], generate_summary: bool) -> tuple[str, float]:
        payload = {
            "collection_name": collection,
            "blocking": False,
            "split_options": {"chunk_size": 512, "chunk_overlap": 150},
            "custom_metadata": [],
            "generate_summary": generate_summary,
        }
        handles, parts = [], []
        try:
            for path in paths:
                handle = path.open("rb")
                handles.append(handle)
                mime = MIME_TYPES.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0]
                parts.append(("documents", (path.name, handle, mime or "application/octet-stream")))
            parts.append(("data", (None, json.dumps(payload), "application/json")))
            started = time.perf_counter()
            data = self.request("POST", "/v1/documents", files=parts, timeout=600)
            elapsed = time.perf_counter() - started
            task_id = data.get("task_id") or data.get("task") or data.get("id")
            if not task_id:
                raise RuntimeError(f"Upload response has no task ID: {data}")
            return str(task_id), elapsed
        finally:
            for handle in handles:
                handle.close()

    def wait(self, task_id: str, interval: float, timeout: int) -> tuple[dict, float]:
        started = time.perf_counter()
        last_state = None
        while True:
            status = self.request(
                "GET", "/v1/status", params={"task_id": task_id}, timeout=60
            )
            state = status.get("state")
            elapsed = time.perf_counter() - started
            nv_status = status.get("nv_ingest_status") or {}
            signature = (state, nv_status.get("extraction_completed"))
            if signature != last_state:
                print(
                    f"    state={state}, extraction_completed="
                    f"{nv_status.get('extraction_completed', '?')}, elapsed={elapsed:.1f}s",
                    flush=True,
                )
                last_state = signature
            if state in {"FINISHED", "FAILED", "UNKNOWN"}:
                return status, elapsed
            if elapsed > timeout:
                raise TimeoutError(f"Task {task_id} exceeded {timeout}s")
            time.sleep(interval)


def chunks(items: list[dict], size: int):
    for index in range(0, len(items), size):
        yield items[index:index + size]


def summarize(rows: list[dict]) -> list[dict]:
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["extension"]].append(row)
    output = []
    for extension in FORMAT_ORDER:
        items = grouped.get(extension, [])
        if not items:
            continue
        successful = [item for item in items if item["outcome"] == "SUCCEEDED"]
        seconds = sum(item["total_seconds"] for item in items)
        successful_bytes = sum(item["successful_bytes"] for item in successful)
        successful_pages = sum(item["successful_pages"] for item in successful)
        successful_documents = sum(item["successful_documents"] for item in successful)
        durations = [item["total_seconds"] for item in successful]
        output.append({
            "extension": extension,
            "batches": len(items),
            "successful_batches": len(successful),
            "failed_batches": len(items) - len(successful),
            "documents_ingested": successful_documents,
            "megabytes_ingested": round(successful_bytes / 1_000_000, 3),
            "mebibytes_ingested": round(successful_bytes / 1024**2, 3),
            "page_equivalents_ingested": successful_pages,
            "total_seconds": round(seconds, 3),
            "mb_per_minute": round(successful_bytes / 1_000_000 * 60 / seconds, 3) if seconds else 0,
            "mib_per_minute": round(successful_bytes / 1024**2 * 60 / seconds, 3) if seconds else 0,
            "pages_per_minute": round(successful_pages * 60 / seconds, 3) if seconds else 0,
            "documents_per_minute": round(successful_documents * 60 / seconds, 3) if seconds else 0,
            "median_batch_seconds": round(median(durations), 3) if durations else None,
        })
    return output


def write_checkpoint(path: Path, report: dict) -> None:
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    options = parse_args()
    if options.batch_size is not None and options.batch_size < 1:
        raise SystemExit("--batch-size must be at least 1")
    if options.sample_per_format is not None and options.sample_per_format < 1:
        raise SystemExit("--sample-per-format must be at least 1")
    repo = Path(__file__).resolve().parents[1]
    corpus = (repo / options.corpus_dir).resolve()
    records = [
        json.loads(line)
        for line in (corpus / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    selected = {
        extension if extension.startswith(".") else "." + extension
        for extension in (options.formats or FORMAT_ORDER)
    }
    records = [item for item in records if item["extension"].lower() in selected]
    grouped = defaultdict(list)
    for item in records:
        grouped[item["extension"].lower()].append(item)

    client = Client(options.ingestor_url)
    print(f"Health: {client.health()}")
    existing_collections = client.collections()
    if options.collection_name in existing_collections and options.replace_collection:
        print(f"Deleting collection {options.collection_name}")
        client.delete_collection(options.collection_name)
        existing_collections.remove(options.collection_name)
    if options.collection_name not in existing_collections:
        print(f"Creating collection {options.collection_name}")
        client.create_collection(options.collection_name)
        existing_documents = set()
    elif options.resume:
        existing_documents = client.document_names(options.collection_name)
        print(f"Resuming with {len(existing_documents)} existing document(s)")
    else:
        raise SystemExit(
            f"Collection exists: {options.collection_name}; use --resume or --replace-collection"
        )

    run_id = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    result_dir = (repo / options.results_dir / run_id).resolve()
    result_dir.mkdir(parents=True)
    checkpoint = result_dir / "report.json"
    report = {
        "run_id": run_id,
        "collection_name": options.collection_name,
        "corpus_dir": str(corpus),
        "configuration": vars(options),
        "started_snapshot": snapshot(),
        "batches": [],
        "format_summary": [],
    }
    run_started = time.perf_counter()

    for extension in FORMAT_ORDER:
        items = [
            item for item in grouped.get(extension, [])
            if item["filename"] not in existing_documents
        ]
        if options.sample_per_format is not None:
            items = items[: options.sample_per_format]
        if not items:
            continue
        batch_size = options.batch_size or DEFAULT_BATCH_SIZES[extension]
        total_batches = (len(items) + batch_size - 1) // batch_size
        print(f"\n{extension}: {len(items)} files in {total_batches} batch(es)", flush=True)
        for batch_index, batch in enumerate(chunks(items, batch_size), 1):
            paths = [corpus / item["relative_path"] for item in batch]
            before = snapshot()
            started = time.perf_counter()
            task_id, state, failures, error = "", "ERROR", [], None
            submit_seconds = processing_seconds = 0.0
            print(
                f"  batch {batch_index}/{total_batches}: {len(paths)} files, "
                f"{sum(path.stat().st_size for path in paths) / 1_000_000:.2f} MB",
                flush=True,
            )
            try:
                task_id, submit_seconds = client.upload(
                    options.collection_name, paths, options.generate_summary
                )
                status, processing_seconds = client.wait(
                    task_id, options.poll_interval, options.timeout
                )
                state = status.get("state", "UNKNOWN")
                failures = status.get("result", {}).get("failed_documents", [])
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                print(f"    ERROR: {error}", flush=True)
            failure_names = {item.get("document_name") for item in failures}
            successful_items = [
                item for item in batch
                if item["filename"] not in failure_names
            ] if state == "FINISHED" else []
            total_seconds = time.perf_counter() - started
            outcome = "SUCCEEDED" if state == "FINISHED" and not failures else "FAILED"
            row = {
                "extension": extension,
                "batch_index": batch_index,
                "filenames": [item["filename"] for item in batch],
                "task_id": task_id,
                "state": state,
                "outcome": outcome,
                "failed_documents": failures,
                "attempted_documents": len(batch),
                "attempted_bytes": sum(item["size_bytes"] for item in batch),
                "attempted_pages": sum(item["page_count"] for item in batch),
                "successful_documents": len(successful_items),
                "successful_bytes": sum(item["size_bytes"] for item in successful_items),
                "successful_pages": sum(item["page_count"] for item in successful_items),
                "submit_seconds": round(submit_seconds, 3),
                "processing_seconds": round(processing_seconds, 3),
                "total_seconds": round(total_seconds, 3),
                "snapshot_before": before,
                "snapshot_after": snapshot(),
                "error": error,
            }
            report["batches"].append(row)
            report["format_summary"] = summarize(report["batches"])
            report["elapsed_seconds"] = round(time.perf_counter() - run_started, 3)
            write_checkpoint(checkpoint, report)
            print(
                f"    outcome={outcome}, total={total_seconds:.1f}s, "
                f"failed_documents={len(failures)}",
                flush=True,
            )
            if options.pause_between_batches:
                time.sleep(options.pause_between_batches)

    report["elapsed_seconds"] = round(time.perf_counter() - run_started, 3)
    report["finished_snapshot"] = snapshot()
    report["format_summary"] = summarize(report["batches"])
    write_checkpoint(checkpoint, report)
    csv_path = result_dir / "format-summary.csv"
    fields = list(report["format_summary"][0]) if report["format_summary"] else []
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        if fields:
            writer.writeheader()
            writer.writerows(report["format_summary"])
    print("\n" + json.dumps(report["format_summary"], indent=2))
    print(f"Report: {checkpoint}")
    print(f"CSV: {csv_path}")
    return 1 if any(item["outcome"] != "SUCCEEDED" for item in report["batches"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
