#!/usr/bin/env python3
"""Compare one OpenAI-compatible model profile with fixed prompts."""

from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROMPTS = ROOT / "benchmarks/llm-precision/prompts.jsonl"
DEFAULT_RESULTS = ROOT / "benchmarks/llm-precision/results"


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--base-url", default="http://localhost:8999/v1")
    parser.add_argument("--prompts", type=Path, default=DEFAULT_PROMPTS)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--enable-thinking", action="store_true")
    parser.add_argument("--timeout", type=float, default=300.0)
    return parser.parse_args()


def get_json(url: str, timeout: float) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.load(response)


def load_prompts(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        prompts = [json.loads(line) for line in handle if line.strip()]
    if not prompts:
        raise ValueError(f"No prompts found in {path}")
    return prompts


def stream_completion(
    endpoint: str,
    model: str,
    prompt: str,
    args: argparse.Namespace,
) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": args.max_tokens,
        "temperature": args.temperature,
        "stream": True,
        "stream_options": {"include_usage": True},
        "chat_template_kwargs": {"enable_thinking": args.enable_thinking},
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    first_token_at = None
    content: list[str] = []
    reasoning: list[str] = []
    usage: dict[str, Any] = {}

    try:
        with urllib.request.urlopen(request, timeout=args.timeout) as response:
            for raw_line in response:
                line = raw_line.decode(errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                event = json.loads(data)
                usage = event.get("usage") or usage
                choices = event.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                text = delta.get("content") or ""
                thought = delta.get("reasoning_content") or ""
                if (text or thought) and first_token_at is None:
                    first_token_at = time.perf_counter()
                content.append(text)
                reasoning.append(thought)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc

    finished = time.perf_counter()
    total = finished - started
    ttft = first_token_at - started if first_token_at else None
    tokens = int(usage.get("completion_tokens") or 0)
    generation_time = total - (ttft or 0)
    return {
        "ttft_seconds": ttft,
        "total_seconds": total,
        "completion_tokens": tokens,
        "tokens_per_second": tokens / generation_time if tokens and generation_time else None,
        "content": "".join(content),
        "reasoning": "".join(reasoning),
        "usage": usage,
    }


def median(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [row[key] for row in rows if row.get(key) is not None]
    return statistics.median(values) if values else None


def main() -> int:
    args = arguments()
    if args.runs < 1 or args.warmup < 0:
        raise ValueError("--runs must be positive and --warmup cannot be negative")

    base_url = args.base_url.rstrip("/")
    endpoint = f"{base_url}/chat/completions"
    models = get_json(f"{base_url}/models", args.timeout).get("data") or []
    if not models:
        raise RuntimeError("No model was returned by the endpoint")
    model = str(models[0]["id"])
    prompts = load_prompts(args.prompts)

    print(f"Model: {model}")
    print(f"Label: {args.label}")
    for index in range(args.warmup):
        print(f"Warmup {index + 1}/{args.warmup}")
        stream_completion(endpoint, model, prompts[index % len(prompts)]["prompt"], args)

    results = []
    all_runs = []
    for prompt in prompts:
        print(f"[{prompt['id']}]", end="", flush=True)
        runs = []
        for _ in range(args.runs):
            run = stream_completion(endpoint, model, prompt["prompt"], args)
            runs.append(run)
            all_runs.append(run)
            print(".", end="", flush=True)
        print()
        answer = runs[0]["content"] or runs[0]["reasoning"]
        expected = [str(item) for item in prompt.get("expected_keywords", [])]
        matched = [item for item in expected if item.casefold() in answer.casefold()]
        results.append({
            **prompt,
            "matched_keywords": matched,
            "keyword_score": len(matched) / len(expected) if expected else None,
            "median_ttft_seconds": median(runs, "ttft_seconds"),
            "median_total_seconds": median(runs, "total_seconds"),
            "median_tokens_per_second": median(runs, "tokens_per_second"),
            "runs": runs,
        })

    scored = [row["keyword_score"] for row in results if row["keyword_score"] is not None]
    summary = {
        "requests": len(all_runs),
        "median_ttft_seconds": median(all_runs, "ttft_seconds"),
        "median_total_seconds": median(all_runs, "total_seconds"),
        "median_tokens_per_second": median(all_runs, "tokens_per_second"),
        "mean_keyword_score": statistics.mean(scored) if scored else None,
    }
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    output_dir = DEFAULT_RESULTS / f"{timestamp}-{args.label}"
    output_dir.mkdir(parents=True)
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "label": args.label,
        "model": model,
        "endpoint": endpoint,
        "settings": vars(args) | {"prompts": str(args.prompts)},
        "summary": summary,
        "prompts": results,
    }
    report_path = output_dir / "report.json"
    report_path.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"Report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
