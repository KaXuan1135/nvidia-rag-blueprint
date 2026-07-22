#!/usr/bin/env python3
"""List collections exposed by the NVIDIA RAG ingestion API."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="List collections in the NVIDIA RAG ingestion service."
    )
    parser.add_argument(
        "--api-url",
        default=os.getenv("INGESTION_API_URL", "http://localhost:8082/v1"),
        help=(
            "Ingestion API base URL "
            "(default: INGESTION_API_URL or http://localhost:8082/v1)"
        ),
    )
    output = parser.add_mutually_exclusive_group()
    output.add_argument(
        "--names-only",
        action="store_true",
        help="Print one collection name per line.",
    )
    output.add_argument(
        "--json",
        action="store_true",
        help="Print the complete API response as formatted JSON.",
    )
    return parser.parse_args()


def fetch_collections(api_url: str) -> dict[str, Any]:
    endpoint = urllib.parse.urljoin(api_url.rstrip("/") + "/", "collections")
    request = urllib.request.Request(
        endpoint,
        headers={"Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Ingestion API returned HTTP {error.code}: {detail}"
        ) from error
    except urllib.error.URLError as error:
        raise RuntimeError(
            f"Unable to reach ingestion API at {endpoint}: {error}"
        ) from error

    if not isinstance(payload, dict) or not isinstance(payload.get("collections"), list):
        raise RuntimeError("Ingestion API returned an unexpected response.")
    return payload


def value(collection: dict[str, Any], key: str, default: Any = "-") -> Any:
    info = collection.get("collection_info")
    if isinstance(info, dict):
        return info.get(key, default)
    return default


def print_table(collections: list[dict[str, Any]]) -> None:
    if not collections:
        print("No collections found.")
        return

    rows = [
        (
            str(collection.get("collection_name", "-")),
            str(value(collection, "number_of_files")),
            str(collection.get("num_entities", "-")),
            str(value(collection, "ingestion_status")),
        )
        for collection in collections
    ]
    headers = ("COLLECTION", "FILES", "ENTITIES", "STATUS")
    widths = [
        max(len(headers[index]), *(len(row[index]) for row in rows))
        for index in range(len(headers))
    ]

    print(
        "  ".join(
            header.ljust(widths[index]) for index, header in enumerate(headers)
        )
    )
    print("  ".join("-" * width for width in widths))
    for row in rows:
        print("  ".join(cell.ljust(widths[index]) for index, cell in enumerate(row)))


def main() -> int:
    args = parse_args()
    try:
        payload = fetch_collections(args.api_url)
    except RuntimeError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    collections = payload["collections"]
    if args.json:
        json.dump(payload, sys.stdout, indent=2)
        print()
    elif args.names_only:
        for collection in collections:
            print(collection.get("collection_name", ""))
    else:
        print_table(collections)
        print(f"\nTotal: {len(collections)} collection(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
