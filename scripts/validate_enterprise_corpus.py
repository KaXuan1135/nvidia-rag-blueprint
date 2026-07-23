#!/usr/bin/env python3
"""Validate generated enterprise corpus files, hashes, and ground truth."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import zipfile
from collections import Counter
from pathlib import Path

from PIL import Image


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-dir", required=True)
    return parser.parse_args()


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def validate_file(path: Path) -> None:
    suffix = path.suffix.lower()
    if suffix in {".docx", ".pptx", ".xlsx"}:
        with zipfile.ZipFile(path) as archive:
            bad = archive.testzip()
            if bad:
                raise ValueError(f"corrupt ZIP member: {bad}")
    elif suffix in {".png", ".jpg", ".jpeg"}:
        with Image.open(path) as image:
            image.verify()
    elif suffix == ".pdf":
        with path.open("rb") as handle:
            if handle.read(5) != b"%PDF-":
                raise ValueError("invalid PDF signature")
    elif suffix in {".txt", ".md", ".html", ".csv", ".json"}:
        text = path.read_text(encoding="utf-8")
        if not text.strip():
            raise ValueError("empty text file")
        if suffix == ".json":
            json.loads(text)
        elif suffix == ".csv":
            with path.open(newline="", encoding="utf-8") as handle:
                next(csv.reader(handle))
    else:
        raise ValueError(f"unexpected extension: {suffix}")


def main() -> int:
    options = parse_args()
    root = Path(options.corpus_dir).resolve()
    records = [
        json.loads(line)
        for line in (root / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    failures, extensions = [], Counter()
    total = 0
    for index, record in enumerate(records, 1):
        path = root / record["relative_path"]
        try:
            if not path.is_file():
                raise ValueError("missing file")
            if path.stat().st_size != record["size_bytes"]:
                raise ValueError("size mismatch")
            if digest(path) != record["sha256"]:
                raise ValueError("sha256 mismatch")
            canonical = root / "ground_truth" / "documents" / f"{record['document_id']}.md"
            if not canonical.is_file() or not canonical.read_text(encoding="utf-8").strip():
                raise ValueError("missing canonical ground truth")
            validate_file(path)
            extensions[path.suffix.lower()] += 1
            total += path.stat().st_size
        except Exception as exc:
            failures.append({"relative_path": record["relative_path"], "error": str(exc)})
        if index % 100 == 0:
            print(f"Validated {index}/{len(records)}", flush=True)
    result = {
        "documents": len(records),
        "valid": len(records) - len(failures),
        "failed": len(failures),
        "total_size_bytes": total,
        "extensions": dict(extensions),
        "failures": failures,
    }
    (root / "validation.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
