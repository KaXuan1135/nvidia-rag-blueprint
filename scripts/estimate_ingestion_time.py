#!/usr/bin/env python3
"""Estimate folder ingestion time from a per-format ingestion benchmark report."""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", required=True)
    parser.add_argument("--benchmark-report", required=True)
    parser.add_argument("--manifest", help="Optional manifest.jsonl with accurate page counts")
    parser.add_argument("--json-output")
    return parser.parse_args()


def approximate_pdf_pages(path: Path) -> int:
    try:
        data = path.read_bytes()
        count = len(re.findall(rb"/Type\s*/Page(?!s)", data))
        return max(1, count)
    except OSError:
        return 1


def main() -> int:
    options = parse_args()
    folder = Path(options.folder).resolve()
    report = json.loads(Path(options.benchmark_report).read_text(encoding="utf-8"))
    rates = {
        item["extension"]: item
        for item in report.get("format_summary", [])
        if item.get("mb_per_minute", 0) > 0
    }
    manifest_pages = {}
    if options.manifest:
        for line in Path(options.manifest).read_text(encoding="utf-8").splitlines():
            item = json.loads(line)
            manifest_pages[item["filename"]] = item.get("page_count", 1)

    grouped = defaultdict(lambda: {"files": 0, "bytes": 0, "pages": 0})
    unsupported = []
    for path in sorted(item for item in folder.rglob("*") if item.is_file()):
        extension = path.suffix.lower()
        if extension not in rates:
            unsupported.append(str(path))
            continue
        grouped[extension]["files"] += 1
        grouped[extension]["bytes"] += path.stat().st_size
        grouped[extension]["pages"] += manifest_pages.get(
            path.name, approximate_pdf_pages(path) if extension == ".pdf" else 1
        )

    rows = []
    total_minutes = 0.0
    for extension, values in sorted(grouped.items()):
        rate = rates[extension]
        megabytes = values["bytes"] / 1_000_000
        mb_minutes = megabytes / rate["mb_per_minute"]
        page_minutes = (
            values["pages"] / rate["pages_per_minute"]
            if rate.get("pages_per_minute", 0) > 0 else None
        )
        # MB/min works without document parsing; pages/min is shown as a second estimate.
        chosen = mb_minutes
        total_minutes += chosen
        rows.append({
            "extension": extension,
            "files": values["files"],
            "megabytes": round(megabytes, 3),
            "pages": values["pages"],
            "benchmark_mb_per_minute": rate["mb_per_minute"],
            "benchmark_pages_per_minute": rate.get("pages_per_minute"),
            "estimated_minutes_by_size": round(mb_minutes, 3),
            "estimated_minutes_by_pages": round(page_minutes, 3) if page_minutes is not None else None,
        })
    result = {
        "folder": str(folder),
        "benchmark_report": str(Path(options.benchmark_report).resolve()),
        "formats": rows,
        "estimated_minutes": round(total_minutes, 3),
        "estimated_range_minutes": {
            "optimistic": round(total_minutes * 0.75, 3),
            "conservative": round(total_minutes * 1.5, 3),
        },
        "unsupported_files": unsupported,
        "notes": [
            "The total assumes formats are ingested sequentially with the benchmark configuration.",
            "PDF page count is approximate unless --manifest is supplied.",
            "OCR quality, tables, charts, model warm-up, and batch size can materially change latency.",
        ],
    }
    print(f"{'FORMAT':8} {'FILES':>7} {'MB':>12} {'MB/MIN':>10} {'EST. MIN':>12}")
    print("-" * 55)
    for row in rows:
        print(
            f"{row['extension']:8} {row['files']:7d} {row['megabytes']:12.2f} "
            f"{row['benchmark_mb_per_minute']:10.2f} {row['estimated_minutes_by_size']:12.2f}"
        )
    print("-" * 55)
    print(f"Estimated total: {total_minutes:.2f} minutes")
    print(
        f"Planning range: {result['estimated_range_minutes']['optimistic']:.2f}-"
        f"{result['estimated_range_minutes']['conservative']:.2f} minutes"
    )
    if unsupported:
        print(f"Unsupported/unbenchmarked files: {len(unsupported)}")
    if options.json_output:
        Path(options.json_output).write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
