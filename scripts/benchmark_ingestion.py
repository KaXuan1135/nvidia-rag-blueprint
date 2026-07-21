#!/usr/bin/env python3
"""Run timed NVIDIA RAG ingestion benchmarks from a generated manifest."""

from __future__ import annotations

import argparse
import csv
import json
import math
import mimetypes
import re
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import median

import requests


MIME_TYPES = {
    ".csv": "text/csv",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".md": "text/markdown",
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".txt": "text/plain",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-dir", default="benchmarks/ingestion/corpus")
    parser.add_argument("--results-dir", default="benchmarks/ingestion/results")
    parser.add_argument("--collection-prefix", default="ingestion-bench")
    parser.add_argument("--ingestor-url", default="http://localhost:8082")
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--poll-interval", type=float, default=2.0)
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--pause-between-batches", type=float, default=2.0)
    parser.add_argument("--categories", nargs="*", help="Run only selected manifest categories")
    parser.add_argument("--replace", action="store_true", help="Delete matching benchmark collections first")
    parser.add_argument("--generate-summary", action="store_true")
    return parser.parse_args()


def chunks(items: list[dict], size: int) -> list[list[dict]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-")


def read_meminfo() -> dict[str, int]:
    values: dict[str, int] = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, raw = line.split(":", 1)
        values[key] = int(raw.strip().split()[0]) * 1024
    return values


def system_snapshot() -> dict:
    memory = read_meminfo()
    disk = __import__("shutil").disk_usage("/")
    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "memory_total_bytes": memory.get("MemTotal", 0),
        "memory_available_bytes": memory.get("MemAvailable", 0),
        "swap_total_bytes": memory.get("SwapTotal", 0),
        "swap_free_bytes": memory.get("SwapFree", 0),
        "disk_total_bytes": disk.total,
        "disk_free_bytes": disk.free,
    }


class Ingestor:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()

    def health(self) -> dict:
        response = self.session.get(f"{self.base_url}/v1/health", timeout=30)
        response.raise_for_status()
        return response.json()

    def list_collections(self) -> set[str]:
        response = self.session.get(f"{self.base_url}/v1/collections", timeout=60)
        response.raise_for_status()
        return {item["collection_name"] for item in response.json().get("collections", [])}

    def create_collection(self, name: str) -> dict:
        response = self.session.post(
            f"{self.base_url}/v1/collection",
            json={"collection_name": name, "embedding_dimension": 2048, "metadata_schema": []},
            timeout=60,
        )
        response.raise_for_status()
        return response.json()

    def delete_collection(self, name: str) -> dict:
        response = self.session.delete(
            f"{self.base_url}/v1/collections", json=[name], timeout=120
        )
        response.raise_for_status()
        return response.json()

    def upload(self, collection: str, paths: list[Path], generate_summary: bool) -> tuple[str, float]:
        payload = {
            "collection_name": collection,
            "blocking": False,
            "split_options": {"chunk_size": 512, "chunk_overlap": 150},
            "custom_metadata": [],
            "generate_summary": generate_summary,
        }
        handles = []
        files = []
        try:
            for path in paths:
                handle = path.open("rb")
                handles.append(handle)
                content_type = MIME_TYPES.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0]
                files.append(("documents", (path.name, handle, content_type or "application/octet-stream")))
            files.append(("data", (None, json.dumps(payload), "application/json")))
            start = time.perf_counter()
            response = self.session.post(
                f"{self.base_url}/v1/documents", files=files, timeout=300
            )
            submit_seconds = time.perf_counter() - start
            response.raise_for_status()
            data = response.json()
            task_id = data.get("task_id") or data.get("task") or data.get("id")
            if not task_id:
                raise RuntimeError(f"Upload response has no task ID: {data}")
            return str(task_id), submit_seconds
        finally:
            for handle in handles:
                handle.close()

    def wait(self, task_id: str, interval: float, timeout: int) -> tuple[dict, float, list[dict]]:
        started = time.perf_counter()
        timeline = []
        last_signature = None
        while True:
            response = self.session.get(
                f"{self.base_url}/v1/status", params={"task_id": task_id}, timeout=60
            )
            response.raise_for_status()
            status = response.json()
            elapsed = time.perf_counter() - started
            nv_status = status.get("nv_ingest_status") or {}
            signature = (
                status.get("state"),
                nv_status.get("extraction_completed"),
                json.dumps(nv_status.get("document_wise_status", {}), sort_keys=True),
            )
            if signature != last_signature:
                timeline.append({"elapsed_seconds": round(elapsed, 3), "status": status})
                last_signature = signature
            state = status.get("state")
            if state in {"FINISHED", "FAILED", "UNKNOWN"}:
                return status, elapsed, timeline
            if elapsed > timeout:
                raise TimeoutError(f"Task {task_id} exceeded {timeout} seconds")
            time.sleep(interval)


def summarize(rows: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[row["category"]].append(row)
    summaries = []
    for category, items in sorted(grouped.items()):
        successful = [item for item in items if item["state"] == "FINISHED" and not item["failed_documents"]]
        seconds = sum(item["total_seconds"] for item in items)
        pages = sum(item["page_equivalents"] for item in successful)
        documents = sum(item["document_count"] for item in successful)
        durations = [item["total_seconds"] for item in successful]
        sorted_durations = sorted(durations)
        p90_seconds = (
            sorted_durations[max(0, math.ceil(0.9 * len(sorted_durations)) - 1)]
            if sorted_durations
            else None
        )
        summaries.append(
            {
                "category": category,
                "batches": len(items),
                "successful_batches": len(successful),
                "failed_batches": len(items) - len(successful),
                "documents_ingested": documents,
                "page_equivalents_ingested": pages,
                "total_seconds": round(seconds, 3),
                "documents_per_minute": round(documents * 60 / seconds, 3) if seconds else 0,
                "pages_per_minute": round(pages * 60 / seconds, 3) if seconds else 0,
                "median_batch_seconds": round(median(durations), 3) if durations else None,
                "p90_batch_seconds": round(p90_seconds, 3) if p90_seconds is not None else None,
            }
        )
    return summaries


def write_csv(path: Path, rows: list[dict]) -> None:
    fields = [
        "category",
        "collection",
        "batch_index",
        "document_count",
        "page_equivalents",
        "bytes",
        "filenames",
        "task_id",
        "state",
        "failed_documents",
        "submit_seconds",
        "processing_seconds",
        "total_seconds",
        "memory_available_before_bytes",
        "memory_available_after_bytes",
        "swap_free_before_bytes",
        "swap_free_after_bytes",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            csv_row = {field: row.get(field) for field in fields}
            csv_row["failed_documents"] = json.dumps(row.get("failed_documents", []))
            writer.writerow(csv_row)


def main() -> int:
    args = parse_args()
    if args.batch_size < 1:
        raise SystemExit("--batch-size must be at least 1")
    root = Path(__file__).resolve().parents[1]
    corpus = (root / args.corpus_dir).resolve()
    manifest_path = corpus / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    documents = manifest["documents"]
    if args.categories:
        selected = set(args.categories)
        documents = [item for item in documents if item["category"] in selected]
        missing = selected - {item["category"] for item in documents}
        if missing:
            raise SystemExit(f"Unknown or empty categories: {sorted(missing)}")

    grouped: dict[str, list[dict]] = defaultdict(list)
    for item in documents:
        grouped[item["category"]].append(item)

    client = Ingestor(args.ingestor_url)
    print(f"Health: {client.health()}")
    existing = client.list_collections()
    run_id = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    run_prefix = slug(f"{args.collection_prefix}-{manifest['profile']}-{run_id}")
    results_dir = (root / args.results_dir / run_id).resolve()
    results_dir.mkdir(parents=True)
    rows = []
    run_started = time.perf_counter()
    run_snapshot_before = system_snapshot()

    for category in sorted(grouped):
        collection = slug(f"{run_prefix}-{category}")
        if collection in existing:
            if not args.replace:
                raise SystemExit(f"Collection already exists: {collection}")
            print(f"Deleting existing collection {collection}")
            client.delete_collection(collection)
        print(f"Creating collection {collection}")
        client.create_collection(collection)

        for batch_index, batch in enumerate(chunks(grouped[category], args.batch_size), start=1):
            paths = [corpus / item["relative_path"] for item in batch]
            page_equivalents = sum(item["page_equivalents"] for item in batch)
            total_bytes = sum(path.stat().st_size for path in paths)
            before = system_snapshot()
            print(
                f"[{category}] batch {batch_index}: {len(paths)} file(s), "
                f"{page_equivalents} page-equivalents"
            )
            batch_started = time.perf_counter()
            task_id = ""
            state = "ERROR"
            failed_documents: list = []
            submit_seconds = 0.0
            processing_seconds = 0.0
            timeline: list[dict] = []
            error = None
            try:
                task_id, submit_seconds = client.upload(
                    collection, paths, args.generate_summary
                )
                status, processing_seconds, timeline = client.wait(
                    task_id, args.poll_interval, args.timeout
                )
                state = status.get("state", "UNKNOWN")
                failed_documents = status.get("result", {}).get("failed_documents", [])
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                print(f"  ERROR: {error}")
            total_seconds = time.perf_counter() - batch_started
            after = system_snapshot()
            row = {
                "category": category,
                "collection": collection,
                "batch_index": batch_index,
                "document_count": len(paths),
                "page_equivalents": page_equivalents,
                "bytes": total_bytes,
                "filenames": ";".join(path.name for path in paths),
                "task_id": task_id,
                "state": state,
                "failed_documents": failed_documents,
                "submit_seconds": round(submit_seconds, 3),
                "processing_seconds": round(processing_seconds, 3),
                "total_seconds": round(total_seconds, 3),
                "memory_available_before_bytes": before["memory_available_bytes"],
                "memory_available_after_bytes": after["memory_available_bytes"],
                "swap_free_before_bytes": before["swap_free_bytes"],
                "swap_free_after_bytes": after["swap_free_bytes"],
                "timeline": timeline,
                "error": error,
            }
            rows.append(row)
            succeeded = state == "FINISHED" and not failed_documents
            outcome = "SUCCEEDED" if succeeded else "FAILED"
            print(
                f"  outcome={outcome}, state={state}, failed_documents={len(failed_documents)}, "
                f"total={total_seconds:.2f}s, task={task_id or 'none'}"
            )
            for failure in failed_documents:
                document_name = failure.get("document_name", "unknown")
                error_message = failure.get("error_message", failure)
                print(f"    - {document_name}: {error_message}")
            if args.pause_between_batches:
                time.sleep(args.pause_between_batches)

    run_seconds = time.perf_counter() - run_started
    report = {
        "run_id": run_id,
        "manifest": str(manifest_path),
        "profile": manifest["profile"],
        "configuration": vars(args),
        "started_snapshot": run_snapshot_before,
        "finished_snapshot": system_snapshot(),
        "total_seconds": round(run_seconds, 3),
        "batches": rows,
        "category_summary": summarize(rows),
    }
    json_path = results_dir / "report.json"
    csv_path = results_dir / "batches.csv"
    json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    write_csv(csv_path, rows)
    print(json.dumps(report["category_summary"], indent=2))
    print(f"Report: {json_path}")
    print(f"CSV: {csv_path}")
    return 1 if any(row["state"] != "FINISHED" or row["failed_documents"] for row in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
