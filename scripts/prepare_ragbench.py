#!/usr/bin/env python3
"""Download deterministic RAGBench samples and build deduplicated text corpora."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "benchmarks/ragbench/data"
DEFAULT_DATASETS = ["emanual", "techqa", "cuad", "finqa", "hotpotqa"]
ROWS_URL = "https://datasets-server.huggingface.co/rows"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--datasets", nargs="+", default=DEFAULT_DATASETS)
    parser.add_argument("--split", default="test")
    parser.add_argument("--samples-per-dataset", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--timeout", type=float, default=60.0)
    return parser.parse_args()


def fetch_rows(
    session: requests.Session,
    dataset: str,
    split: str,
    page_size: int,
    timeout: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    offset = 0
    total: int | None = None
    while total is None or offset < total:
        response = session.get(
            ROWS_URL,
            params={
                "dataset": "galileo-ai/ragbench",
                "config": dataset,
                "split": split,
                "offset": offset,
                "length": page_size,
            },
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
        total = int(payload["num_rows_total"])
        page = [item["row"] for item in payload.get("rows", [])]
        rows.extend(page)
        offset += len(page)
        print(f"  downloaded {len(rows)}/{total}", flush=True)
        if not page:
            break
    if total is None or len(rows) != total:
        raise RuntimeError(f"Expected {total} {dataset} rows, downloaded {len(rows)}")
    return rows


def normalized_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def document_hash(value: str) -> str:
    return hashlib.sha256(normalized_text(value).encode("utf-8")).hexdigest()


def normalized_sentence_key(value: str) -> str:
    """Normalize occasional annotation punctuation such as ``1a.`` vs ``1a``."""
    return value.strip().rstrip(".,:;")


def sentence_map(sample: dict[str, Any]) -> dict[str, dict[str, Any]]:
    mapped: dict[str, dict[str, Any]] = {}
    for document_index, groups in enumerate(sample.get("documents_sentences") or []):
        for group in groups or []:
            if not isinstance(group, list) or len(group) != 2:
                continue
            key, text = normalized_sentence_key(str(group[0])), str(group[1])
            mapped[key] = {
                "text": normalized_text(text),
                "document_index": document_index,
            }
    return mapped


def enrich_sample(sample: dict[str, Any]) -> dict[str, Any]:
    documents = [normalized_text(item) for item in sample.get("documents") or []]
    hashes = [document_hash(item) for item in documents]
    sentences = sentence_map(sample)
    relevant_sentences = []
    relevant_hashes = set()
    missing_keys = []
    for key in sample.get("all_relevant_sentence_keys") or []:
        sentence = sentences.get(normalized_sentence_key(str(key)))
        if sentence is None:
            missing_keys.append(str(key))
            continue
        document_index = sentence["document_index"]
        if document_index >= len(hashes):
            missing_keys.append(str(key))
            continue
        relevant_sentences.append(
            {
                "key": str(key),
                "text": sentence["text"],
                "document_hash": hashes[document_index],
            }
        )
        relevant_hashes.add(hashes[document_index])
    return {
        **sample,
        "documents": documents,
        "document_hashes": hashes,
        "relevant_document_hashes": sorted(relevant_hashes),
        "relevant_sentences": relevant_sentences,
        "missing_relevant_sentence_keys": missing_keys,
    }


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=True) + "\n")


def main() -> int:
    args = parse_args()
    if args.samples_per_dataset < 1:
        raise SystemExit("--samples-per-dataset must be positive")
    if not 1 <= args.page_size <= 100:
        raise SystemExit("--page-size must be between 1 and 100")

    output_dir = args.output_dir.resolve()
    corpus_dir = output_dir / "corpus"
    output_dir.mkdir(parents=True, exist_ok=True)
    corpus_dir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    all_samples: list[dict[str, Any]] = []
    manifest_documents: list[dict[str, Any]] = []
    dataset_summary: dict[str, Any] = {}

    for dataset in args.datasets:
        print(f"Fetching {dataset}/{args.split}")
        rows = fetch_rows(session, dataset, args.split, args.page_size, args.timeout)
        sample_count = min(args.samples_per_dataset, len(rows))
        rng = random.Random(f"{args.seed}:{dataset}:{args.split}")
        selected_indices = sorted(rng.sample(range(len(rows)), sample_count))
        samples = [enrich_sample(rows[index]) for index in selected_indices]
        all_samples.extend(samples)

        dataset_corpus = corpus_dir / dataset
        dataset_corpus.mkdir(parents=True, exist_ok=True)
        unique_documents: dict[str, str] = {}
        for sample in samples:
            for digest, document in zip(sample["document_hashes"], sample["documents"]):
                unique_documents.setdefault(digest, document)
        for digest, document in sorted(unique_documents.items()):
            filename = f"{dataset}-{digest[:20]}.txt"
            path = dataset_corpus / filename
            path.write_text(document + "\n", encoding="utf-8")
            manifest_documents.append(
                {
                    "dataset": dataset,
                    "document_hash": digest,
                    "filename": filename,
                    "relative_path": str(path.relative_to(output_dir)),
                    "characters": len(document),
                }
            )
        dataset_summary[dataset] = {
            "available_rows": len(rows),
            "selected_rows": len(samples),
            "selected_indices": selected_indices,
            "unique_documents": len(unique_documents),
            "relevant_sentences": sum(len(item["relevant_sentences"]) for item in samples),
        }
        print(
            f"  selected {len(samples)} questions; wrote {len(unique_documents)} unique documents"
        )

    samples_path = output_dir / "samples.jsonl"
    manifest_path = output_dir / "manifest.json"
    write_jsonl(samples_path, all_samples)
    manifest = {
        "created_at": datetime.now(UTC).isoformat(),
        "source": "galileo-ai/ragbench",
        "split": args.split,
        "seed": args.seed,
        "samples_per_dataset": args.samples_per_dataset,
        "datasets": dataset_summary,
        "documents": manifest_documents,
        "total_samples": len(all_samples),
        "total_unique_documents": len(manifest_documents),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Samples: {samples_path}")
    print(f"Corpus: {corpus_dir}")
    print(f"Manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
