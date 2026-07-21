#!/usr/bin/env python3
"""Ingest and benchmark RAGBench against the local NVIDIA RAG deployment."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import statistics
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

import requests


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = ROOT / "benchmarks/ragbench/data"
DEFAULT_RESULTS = ROOT / "benchmarks/ragbench/results"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["ingest", "run", "all"])
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--datasets", nargs="*")
    parser.add_argument("--ingestor-url", default="http://localhost:8082/v1")
    parser.add_argument("--rag-url", default="http://localhost:8081/v1")
    parser.add_argument("--llm-url", default="http://localhost:8999/v1")
    parser.add_argument("--collection-prefix", default="ragbench-nvfp4")
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--poll-interval", type=float, default=2.0)
    parser.add_argument("--ingestion-timeout", type=float, default=7200.0)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--vdb-top-k", type=int, default=40)
    parser.add_argument("--reranker-top-k", type=int, default=10)
    parser.add_argument("--max-tokens", type=int, default=2048)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--request-timeout", type=float, default=600.0)
    parser.add_argument("--oracle", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--end-to-end", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--judge", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--oracle-context-chars", type=int, default=90000)
    parser.add_argument("--resume-dir", type=Path)
    return parser.parse_args()


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-")


def chunks(items: list[Any], size: int) -> Iterable[list[Any]]:
    for index in range(0, len(items), size):
        yield items[index : index + size]


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=True) + "\n")


def post_json(session: requests.Session, url: str, payload: dict[str, Any], timeout: float) -> Any:
    response = session.post(url, json=payload, timeout=timeout)
    if response.status_code >= 400:
        raise RuntimeError(f"POST {url} returned {response.status_code}: {response.text[:2000]}")
    return response.json()


def collection_name(prefix: str, dataset: str) -> str:
    return slug(f"{prefix}-{dataset}")


class Ingestor:
    def __init__(self, base_url: str, timeout: float):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()

    def collections(self) -> set[str]:
        response = self.session.get(f"{self.base_url}/collections", timeout=60)
        response.raise_for_status()
        return {item["collection_name"] for item in response.json().get("collections", [])}

    def create(self, name: str) -> None:
        post_json(
            self.session,
            f"{self.base_url}/collection",
            {"collection_name": name, "embedding_dimension": 2048, "metadata_schema": []},
            60,
        )

    def documents(self, name: str) -> set[str]:
        response = self.session.get(
            f"{self.base_url}/documents",
            params={"collection_name": name},
            timeout=120,
        )
        response.raise_for_status()
        names = set()
        for item in response.json().get("documents", []):
            metadata = item.get("metadata") or {}
            filename = metadata.get("filename") or item.get("document_name")
            if filename:
                names.add(str(filename))
        return names

    def delete(self, name: str) -> None:
        response = self.session.delete(f"{self.base_url}/collections", json=[name], timeout=120)
        response.raise_for_status()

    def upload(self, name: str, paths: list[Path]) -> str:
        handles = []
        files = []
        payload = {
            "collection_name": name,
            "blocking": False,
            "split_options": {"chunk_size": 512, "chunk_overlap": 150},
            "custom_metadata": [],
            "generate_summary": False,
        }
        try:
            for path in paths:
                handle = path.open("rb")
                handles.append(handle)
                files.append(("documents", (path.name, handle, "text/plain")))
            files.append(("data", (None, json.dumps(payload), "application/json")))
            response = self.session.post(f"{self.base_url}/documents", files=files, timeout=300)
            response.raise_for_status()
            data = response.json()
            task_id = data.get("task_id") or data.get("task") or data.get("id")
            if not task_id:
                raise RuntimeError(f"No task ID in upload response: {data}")
            return str(task_id)
        finally:
            for handle in handles:
                handle.close()

    def wait(self, task_id: str, interval: float) -> dict[str, Any]:
        started = time.monotonic()
        while True:
            response = self.session.get(
                f"{self.base_url}/status", params={"task_id": task_id}, timeout=60
            )
            response.raise_for_status()
            status = response.json()
            if status.get("state") in {"FINISHED", "FAILED", "UNKNOWN"}:
                return status
            if time.monotonic() - started > self.timeout:
                raise TimeoutError(f"Ingestion task {task_id} exceeded {self.timeout}s")
            time.sleep(interval)


def failed_documents(status: dict[str, Any]) -> list[str]:
    failures = []
    document_status = (status.get("nv_ingest_status") or {}).get("document_wise_status") or {}
    for name, detail in document_status.items():
        state = detail.get("status", "") if isinstance(detail, dict) else detail
        if str(state).upper() in {"FAILED", "ERROR"}:
            failures.append(name)
    return failures


def ingest(args: argparse.Namespace, manifest: dict[str, Any], datasets: set[str]) -> dict[str, Any]:
    grouped: dict[str, list[Path]] = defaultdict(list)
    data_dir = args.data_dir.resolve()
    for item in manifest["documents"]:
        if item["dataset"] in datasets:
            grouped[item["dataset"]].append(data_dir / item["relative_path"])
    client = Ingestor(args.ingestor_url, args.ingestion_timeout)
    existing = client.collections()
    report: dict[str, Any] = {"collections": {}, "started_at": datetime.now(UTC).isoformat()}
    for dataset in sorted(grouped):
        name = collection_name(args.collection_prefix, dataset)
        if name in existing:
            if not args.replace:
                uploaded = client.documents(name)
                original_count = len(grouped[dataset])
                grouped[dataset] = [
                    path for path in grouped[dataset] if path.name not in uploaded
                ]
                print(
                    f"Resuming {name}: {len(uploaded)} existing, "
                    f"{len(grouped[dataset])}/{original_count} remaining"
                )
                if not grouped[dataset]:
                    report["collections"][dataset] = {
                        "name": name,
                        "reused": True,
                        "existing_documents": len(uploaded),
                    }
                    continue
            else:
                print(f"Deleting {name}")
                client.delete(name)
                print(f"Creating {name}")
                client.create(name)
        else:
            print(f"Creating {name}")
            client.create(name)
        batches = []
        for index, paths in enumerate(chunks(sorted(grouped[dataset]), args.batch_size), 1):
            print(f"[{dataset}] ingest batch {index}: {len(paths)} document(s)", flush=True)
            started = time.perf_counter()
            task_id = client.upload(name, paths)
            status = client.wait(task_id, args.poll_interval)
            failures = failed_documents(status)
            batch = {
                "index": index,
                "task_id": task_id,
                "documents": len(paths),
                "seconds": round(time.perf_counter() - started, 3),
                "state": status.get("state"),
                "failed_documents": failures,
            }
            batches.append(batch)
            print(f"  {batch['state']} in {batch['seconds']}s; failures={len(failures)}")
            if batch["state"] != "FINISHED" or failures:
                raise RuntimeError(f"Ingestion failed: {batch}")
        report["collections"][dataset] = {"name": name, "reused": False, "batches": batches}
    report["finished_at"] = datetime.now(UTC).isoformat()
    return report


def stream_sse(
    session: requests.Session,
    url: str,
    payload: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    started = time.perf_counter()
    first_chunk_at = None
    content: list[str] = []
    reasoning: list[str] = []
    citations: list[dict[str, Any]] = []
    metrics: dict[str, Any] = {}
    usage: dict[str, Any] = {}
    finish_reason: str | None = None
    with session.post(url, json=payload, stream=True, timeout=timeout) as response:
        if response.status_code >= 400:
            raise RuntimeError(f"POST {url} returned {response.status_code}: {response.text[:2000]}")
        for raw_line in response.iter_lines(decode_unicode=True):
            if not raw_line or not raw_line.startswith("data:"):
                continue
            raw_data = raw_line[5:].strip()
            if raw_data == "[DONE]":
                break
            event = json.loads(raw_data)
            choices = event.get("choices") or []
            if choices:
                finish_reason = choices[0].get("finish_reason") or finish_reason
                delta = choices[0].get("delta") or choices[0].get("message") or {}
                text = delta.get("content") or ""
                thought = delta.get("reasoning_content") or ""
                if first_chunk_at is None and (text or thought):
                    first_chunk_at = time.perf_counter()
                content.append(text)
                reasoning.append(thought)
            citation_payload = event.get("citations") or event.get("sources") or {}
            if citation_payload.get("results"):
                citations = citation_payload["results"]
            metrics.update(event.get("metrics") or {})
            usage.update(event.get("usage") or {})
    finished = time.perf_counter()
    raw_answer = "".join(content)
    return {
        "answer": visible_answer(raw_answer),
        "raw_answer": raw_answer,
        "reasoning": "".join(reasoning),
        "citations": citations,
        "metrics": metrics,
        "usage": usage,
        "finish_reason": finish_reason,
        "truncated": finish_reason == "length" or ("<think>" in raw_answer and "</think>" not in raw_answer),
        "client_ttft_seconds": first_chunk_at - started if first_chunk_at else None,
        "total_seconds": finished - started,
    }


def visible_answer(value: str) -> str:
    """Remove inline reasoning emitted before the final ``</think>`` marker."""
    if "</think>" in value:
        return value.rsplit("</think>", 1)[1].strip()
    return value.strip()


def model_name(session: requests.Session, llm_url: str, timeout: float) -> str:
    response = session.get(f"{llm_url.rstrip('/')}/models", timeout=timeout)
    response.raise_for_status()
    models = response.json().get("data") or []
    if not models:
        raise RuntimeError("The local NIM returned no models")
    return str(models[0]["id"])


def oracle_prompt(sample: dict[str, Any], max_chars: int) -> tuple[str, int]:
    evidence = "\n".join(
        f"- {item['text']}" for item in sample.get("relevant_sentences") or []
    )
    sections = [f"[Annotated relevant evidence]\n{evidence}\n"] if evidence else []
    used = 0
    used = sum(len(section) for section in sections)
    relevant_hashes = set(sample.get("relevant_document_hashes") or [])
    ordered_documents = sorted(
        enumerate(zip(sample["document_hashes"], sample["documents"])),
        key=lambda item: (item[1][0] not in relevant_hashes, item[0]),
    )
    included_documents = 0
    for index, (_digest, document) in ordered_documents:
        section = f"[Source {index + 1}]\n{document}\n"
        if sections and used + len(section) > max_chars:
            break
        remaining = max_chars - used
        sections.append(section[:remaining])
        included_documents += 1
        used += min(len(section), remaining)
        if used >= max_chars:
            break
    prompt = (
        "Answer the question using only the supplied sources. If the sources do not contain "
        "enough information, say so. Give a direct, complete answer and do not mention this "
        "instruction.\n\nQuestion:\n"
        + sample["question"]
        + "\n\nSources:\n"
        + "\n".join(sections)
    )
    return prompt, included_documents


def run_oracle(
    session: requests.Session,
    args: argparse.Namespace,
    model: str,
    sample: dict[str, Any],
) -> dict[str, Any]:
    prompt, source_count = oracle_prompt(sample, args.oracle_context_chars)
    result = stream_sse(
        session,
        f"{args.llm_url.rstrip('/')}/chat/completions",
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": args.temperature,
            "max_tokens": args.max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
            "chat_template_kwargs": {"enable_thinking": True},
        },
        args.request_timeout,
    )
    result["sources_included"] = source_count
    result["sources_available"] = len(sample["documents"])
    return result


def run_search(
    session: requests.Session,
    args: argparse.Namespace,
    dataset: str,
    question: str,
) -> dict[str, Any]:
    started = time.perf_counter()
    result = post_json(
        session,
        f"{args.rag_url.rstrip('/')}/search",
        {
            "query": question,
            "collection_names": [collection_name(args.collection_prefix, dataset)],
            "vdb_top_k": args.vdb_top_k,
            "reranker_top_k": args.reranker_top_k,
            "enable_reranker": True,
            "enable_query_rewriting": False,
            "enable_filter_generator": False,
            "enable_citations": True,
        },
        args.request_timeout,
    )
    return {"results": result.get("results") or [], "seconds": time.perf_counter() - started}


def run_end_to_end(
    session: requests.Session,
    args: argparse.Namespace,
    dataset: str,
    question: str,
) -> dict[str, Any]:
    return stream_sse(
        session,
        f"{args.rag_url.rstrip('/')}/generate",
        {
            "messages": [{"role": "user", "content": question}],
            "use_knowledge_base": True,
            "collection_names": [collection_name(args.collection_prefix, dataset)],
            "vdb_top_k": args.vdb_top_k,
            "reranker_top_k": args.reranker_top_k,
            "enable_reranker": True,
            "enable_query_rewriting": False,
            "enable_filter_generator": False,
            "enable_citations": True,
            "agentic": False,
            "temperature": args.temperature,
            "max_tokens": args.max_tokens,
        },
        args.request_timeout,
    )


def normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def retrieval_scores(sample: dict[str, Any], results: list[dict[str, Any]]) -> dict[str, Any]:
    retrieved_text = normalize(" ".join(str(item.get("content") or "") for item in results))
    retrieved_names = {str(item.get("document_name") or "") for item in results}
    relevant_sentences = sample.get("relevant_sentences") or []
    matched_keys = []
    for sentence in relevant_sentences:
        needle = normalize(sentence["text"])
        if needle and needle in retrieved_text:
            matched_keys.append(sentence["key"])
    relevant_hashes = set(sample.get("relevant_document_hashes") or [])
    matched_hashes = {
        digest
        for digest in relevant_hashes
        if any(digest[:20] in name for name in retrieved_names)
    }
    return {
        "retrieved_chunks": len(results),
        "gold_relevant_sentences": len(relevant_sentences),
        "matched_relevant_sentence_keys": matched_keys,
        "sentence_recall": len(matched_keys) / len(relevant_sentences)
        if relevant_sentences
        else None,
        "gold_relevant_documents": len(relevant_hashes),
        "matched_relevant_document_hashes": sorted(matched_hashes),
        "document_recall": len(matched_hashes) / len(relevant_hashes)
        if relevant_hashes
        else None,
        "reciprocal_rank": reciprocal_rank(sample, results),
    }


def reciprocal_rank(sample: dict[str, Any], results: list[dict[str, Any]]) -> float:
    relevant_hashes = set(sample.get("relevant_document_hashes") or [])
    relevant_texts = [normalize(item["text"]) for item in sample.get("relevant_sentences") or []]
    for rank, result in enumerate(results, 1):
        name = str(result.get("document_name") or "")
        text = normalize(str(result.get("content") or ""))
        hash_match = any(digest[:20] in name for digest in relevant_hashes)
        sentence_match = any(value and value in text for value in relevant_texts)
        if hash_match or sentence_match:
            return 1.0 / rank
    return 0.0


def token_f1(candidate: str, reference: str) -> float | None:
    candidate_tokens = normalize(candidate).split()
    reference_tokens = normalize(reference).split()
    if not candidate_tokens or not reference_tokens:
        return None
    candidate_counts: dict[str, int] = defaultdict(int)
    reference_counts: dict[str, int] = defaultdict(int)
    for token in candidate_tokens:
        candidate_counts[token] += 1
    for token in reference_tokens:
        reference_counts[token] += 1
    overlap = sum(min(count, reference_counts[token]) for token, count in candidate_counts.items())
    precision = overlap / len(candidate_tokens)
    recall = overlap / len(reference_tokens)
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def looks_like_exposed_reasoning(value: str) -> bool:
    return bool(
        re.match(
            r"(?i)^(we need|we must|we have|the question|we should|we are asked)",
            value.strip(),
        )
    )


def parse_json_object(value: str) -> dict[str, Any]:
    value = re.sub(r"^```(?:json)?\s*|\s*```$", "", value.strip(), flags=re.I | re.S)
    match = re.search(r"\{.*\}", value, flags=re.S)
    if not match:
        raise ValueError(f"Judge returned no JSON object: {value[:500]}")
    return json.loads(match.group(0))


def judge_answer(
    session: requests.Session,
    args: argparse.Namespace,
    model: str,
    sample: dict[str, Any],
    answer: str,
    contexts: list[str],
) -> dict[str, Any]:
    evidence = "\n".join(
        f"- {item['text']}" for item in sample.get("relevant_sentences") or []
    )
    context = "\n\n".join(contexts)[: args.oracle_context_chars]
    prompt = f"""You are evaluating a retrieval-augmented answer. Score only from the supplied evidence and context.

Question:
{sample['question']}

Gold relevant evidence:
{evidence or '[none annotated]'}

Reference answer (secondary target; prefer supplied evidence if it conflicts):
{sample['response']}

Retrieved or oracle context:
{context}

Candidate answer:
{answer}

Use integer grades only: 0=wrong/absent, 1=mostly wrong, 2=mixed, 3=mostly correct, 4=fully correct.
Return one JSON object and nothing else:
{{
  "correctness_grade": <integer 0 through 4>,
  "faithfulness_grade": <integer 0 through 4>,
  "completeness_grade": <integer 0 through 4>,
  "answer_relevance_grade": <integer 0 through 4>,
  "pass": <true only if every grade is at least 3>,
  "explanation": "<brief reason>"
}}
"""
    result = stream_sse(
        session,
        f"{args.llm_url.rstrip('/')}/chat/completions",
        {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "Be a strict RAG evaluator. Output valid JSON only.",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.0,
            "max_tokens": 384,
            "stream": True,
            "chat_template_kwargs": {"enable_thinking": False},
        },
        args.request_timeout,
    )
    parsed = parse_json_object(result["answer"] or result["reasoning"])
    scored: dict[str, Any] = {
        "pass": bool(parsed.get("pass")),
        "explanation": str(parsed.get("explanation") or ""),
        "judge_seconds": result["total_seconds"],
    }
    for name in ("correctness", "faithfulness", "completeness", "answer_relevance"):
        grade = int(parsed[f"{name}_grade"])
        if not 0 <= grade <= 4:
            raise ValueError(f"Judge returned invalid {name} grade: {grade}")
        scored[f"{name}_grade"] = grade
        scored[name] = grade / 4
    return scored


def mean(rows: list[dict[str, Any]], path: tuple[str, ...]) -> float | None:
    values = []
    for row in rows:
        current: Any = row
        for key in path:
            current = current.get(key) if isinstance(current, dict) else None
        if isinstance(current, (int, float)) and not isinstance(current, bool):
            values.append(float(current))
    return statistics.mean(values) if values else None


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["dataset"]].append(row)
    for dataset, items in sorted(grouped.items()):
        summary[dataset] = summarize_group(items)
    summary["overall"] = summarize_group(rows)
    return summary


def summarize_group(rows: list[dict[str, Any]]) -> dict[str, Any]:
    retrieval_scorable = [
        row
        for row in rows
        if row.get("retrieval", {}).get("scores", {}).get("sentence_recall") is not None
    ]
    oracle_passes = [
        bool(row["oracle"]["judge"].get("pass"))
        for row in rows
        if isinstance(row.get("oracle"), dict) and isinstance(row["oracle"].get("judge"), dict)
    ]
    end_to_end_passes = [
        bool(row["end_to_end"]["judge"].get("pass"))
        for row in rows
        if isinstance(row.get("end_to_end"), dict)
        and isinstance(row["end_to_end"].get("judge"), dict)
    ]
    return {
        "samples": len(rows),
        "successful_samples": sum("error" not in row for row in rows),
        "retrieval_scorable_samples": len(retrieval_scorable),
        "retrieval_unannotated_samples": len(rows) - len(retrieval_scorable),
        "mean_sentence_recall": mean(rows, ("retrieval", "scores", "sentence_recall")),
        "mean_document_recall": mean(rows, ("retrieval", "scores", "document_recall")),
        "mean_reciprocal_rank": mean(rows, ("retrieval", "scores", "reciprocal_rank")),
        "mean_oracle_token_f1": mean(rows, ("oracle", "token_f1")),
        "mean_end_to_end_token_f1": mean(rows, ("end_to_end", "token_f1")),
        "mean_oracle_correctness": mean(rows, ("oracle", "judge", "correctness")),
        "mean_end_to_end_correctness": mean(rows, ("end_to_end", "judge", "correctness")),
        "mean_end_to_end_faithfulness": mean(rows, ("end_to_end", "judge", "faithfulness")),
        "oracle_judge_pass_rate": sum(oracle_passes) / len(oracle_passes)
        if oracle_passes
        else None,
        "end_to_end_judge_pass_rate": sum(end_to_end_passes) / len(end_to_end_passes)
        if end_to_end_passes
        else None,
        "end_to_end_truncation_rate": sum(
            bool(row.get("end_to_end", {}).get("truncated")) for row in rows
        )
        / len(rows)
        if rows
        else None,
        "end_to_end_reasoning_leak_rate": sum(
            looks_like_exposed_reasoning(row.get("end_to_end", {}).get("answer", ""))
            for row in rows
        )
        / len(rows)
        if rows
        else None,
        "mean_end_to_end_ttft_seconds": mean(rows, ("end_to_end", "client_ttft_seconds")),
        "mean_end_to_end_total_seconds": mean(rows, ("end_to_end", "total_seconds")),
    }


def write_summary_csv(path: Path, summary: dict[str, Any]) -> None:
    rows = [{"dataset": dataset, **values} for dataset, values in summary.items()]
    fields = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def run(args: argparse.Namespace, samples: list[dict[str, Any]], datasets: set[str]) -> Path:
    selected = [item for item in samples if item["dataset_name"].split("_")[0] in datasets]
    if args.limit is not None:
        by_dataset: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in selected:
            by_dataset[item["dataset_name"].split("_")[0]].append(item)
        selected = [item for dataset in sorted(by_dataset) for item in by_dataset[dataset][: args.limit]]
    run_dir = args.resume_dir.resolve() if args.resume_dir else (
        args.results_dir.resolve() / datetime.now(UTC).strftime("%Y%m%d-%H%M%S-nvfp4")
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    responses_path = run_dir / "responses.jsonl"
    completed = set()
    rows = []
    if responses_path.exists():
        rows = load_jsonl(responses_path)
        completed = {row["id"] for row in rows if "error" not in row}
        print(f"Resuming with {len(completed)} completed sample(s)")

    session = requests.Session()
    model = model_name(session, args.llm_url, args.request_timeout)
    config = {
        "created_at": datetime.now(UTC).isoformat(),
        "precision": "nvfp4",
        "model": model,
        "settings": {key: str(value) if isinstance(value, Path) else value for key, value in vars(args).items()},
        "samples": len(selected),
    }
    (run_dir / "config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

    for index, sample in enumerate(selected, 1):
        if sample["id"] in completed:
            continue
        dataset = sample["dataset_name"].split("_")[0]
        print(f"[{index}/{len(selected)}] {dataset}/{sample['id']}", flush=True)
        row: dict[str, Any] = {
            "id": sample["id"],
            "dataset": dataset,
            "question": sample["question"],
            "reference_response": sample["response"],
        }
        try:
            search = run_search(session, args, dataset, sample["question"])
            search["scores"] = retrieval_scores(sample, search["results"])
            row["retrieval"] = search
            if args.oracle:
                oracle = run_oracle(session, args, model, sample)
                oracle["token_f1"] = token_f1(oracle["answer"], sample["response"])
                if args.judge:
                    oracle["judge"] = judge_answer(
                        session, args, model, sample, oracle["answer"], sample["documents"]
                    )
                row["oracle"] = oracle
            if args.end_to_end:
                end_to_end = run_end_to_end(session, args, dataset, sample["question"])
                end_to_end["token_f1"] = token_f1(end_to_end["answer"], sample["response"])
                if args.judge:
                    contexts = [str(item.get("content") or "") for item in search["results"]]
                    end_to_end["judge"] = judge_answer(
                        session, args, model, sample, end_to_end["answer"], contexts
                    )
                row["end_to_end"] = end_to_end
        except Exception as exc:
            row["error"] = f"{type(exc).__name__}: {exc}"
            print(f"  ERROR: {row['error']}")
        append_jsonl(responses_path, row)
        rows.append(row)

    summary = summarize(rows)
    report = {"config": config, "summary": summary}
    (run_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    write_summary_csv(run_dir / "summary.csv", summary)
    print(json.dumps(summary, indent=2))
    print(f"Results: {run_dir}")
    return run_dir


def main() -> int:
    args = parse_args()
    if args.batch_size < 1 or args.reranker_top_k < 1 or args.vdb_top_k < 1:
        raise SystemExit("Batch size and top-k values must be positive")
    data_dir = args.data_dir.resolve()
    manifest = json.loads((data_dir / "manifest.json").read_text(encoding="utf-8"))
    samples = load_jsonl(data_dir / "samples.jsonl")
    available = set(manifest["datasets"])
    datasets = set(args.datasets or sorted(available))
    unknown = datasets - available
    if unknown:
        raise SystemExit(f"Unknown datasets: {sorted(unknown)}")

    if args.action in {"ingest", "all"}:
        ingestion_report = ingest(args, manifest, datasets)
        report_path = args.results_dir.resolve() / "last-ingestion.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(ingestion_report, indent=2) + "\n", encoding="utf-8")
        print(f"Ingestion report: {report_path}")
    if args.action in {"run", "all"}:
        run(args, samples, datasets)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
