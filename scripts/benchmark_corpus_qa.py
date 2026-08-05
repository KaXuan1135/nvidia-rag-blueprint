#!/usr/bin/env python3
"""Benchmark retrieval and answer accuracy through the NVIDIA RAG Server API."""

from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import time
import unicodedata
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

import requests


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RESULTS = ROOT / "benchmarks/corpus-qa/results"
DEFAULT_ENTERPRISE_QUESTIONS = Path(
    "/home/ka_xuan/.Workspace/enterprise-corpus/artifacts/full/benchmark/questions.jsonl"
)
DEFAULT_ENTERPRISE_DOCUMENTS = Path(
    "/home/ka_xuan/.Workspace/enterprise-corpus/artifacts/full/documents.jsonl"
)
DEFAULT_PLAYBOOK_QUESTIONS = Path(
    "/home/ka_xuan/.Workspace/rag-playbook-pdfs/reference_questions.jsonl"
)
DEFAULT_PLAYBOOK_MANIFEST = Path(
    "/home/ka_xuan/.Workspace/rag-playbook-pdfs/manifest.jsonl"
)


@dataclass(frozen=True)
class Sample:
    id: str
    question_id: str
    query_language: str
    question: str
    reference_answer: str
    reference_language: str
    answer_variants: list[str]
    answerable: bool
    gold_documents: list[str]
    authoritative_documents: list[str]
    gold_pages: dict[str, list[int]]
    document_languages: list[str]
    metadata: dict[str, Any]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=["enterprise_v2", "rag_playbook"], required=True)
    parser.add_argument("--collection", required=True)
    parser.add_argument("--questions", type=Path)
    parser.add_argument("--documents-manifest", type=Path)
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--resume-dir", type=Path)
    parser.add_argument("--query-languages", nargs="+", default=["en"])
    parser.add_argument("--limit", type=int, help="Maximum base questions before language expansion")
    parser.add_argument("--question-ids", nargs="*")
    parser.add_argument("--rag-url", default="http://localhost:8081/v1")
    parser.add_argument("--llm-url", default="http://localhost:8999/v1")
    parser.add_argument("--modes", nargs="+", choices=["retrieval", "end_to_end"], default=["retrieval", "end_to_end"])
    parser.add_argument("--vdb-top-k", type=int, default=40)
    parser.add_argument("--reranker-top-k", type=int, default=10)
    parser.add_argument("--reranker", choices=["on", "off"], default="on")
    parser.add_argument("--query-rewriting", choices=["on", "off"], default="off")
    parser.add_argument("--pipeline", choices=["standard", "agentic"], default="standard")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-tokens", type=int, default=2048)
    parser.add_argument("--judge", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--judge-max-tokens", type=int, default=768)
    parser.add_argument("--request-timeout", type=float, default=600.0)
    parser.add_argument("--retrieved-page-base", choices=[0, 1], type=int, default=0)
    parser.add_argument("--continue-on-error", action=argparse.BooleanOptionalAction, default=True)
    return parser.parse_args()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def default_paths(dataset: str) -> tuple[Path, Path]:
    if dataset == "enterprise_v2":
        return DEFAULT_ENTERPRISE_QUESTIONS, DEFAULT_ENTERPRISE_DOCUMENTS
    return DEFAULT_PLAYBOOK_QUESTIONS, DEFAULT_PLAYBOOK_MANIFEST


def document_id_from_name(name: str, known_ids: Iterable[str]) -> str | None:
    folded = Path(name).name.casefold()
    for document_id in known_ids:
        if document_id.casefold() in folded:
            return document_id
    return None


def build_enterprise_samples(
    questions: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    languages: list[str],
) -> list[Sample]:
    by_id = {item["document_id"]: item for item in documents}
    supported = {language for row in questions for language in row.get("questions", {})}
    reject_unsupported_languages(languages, supported, "enterprise_v2")
    samples = []
    for row in questions:
        gold = list(row.get("authoritative_evidence", [])) + list(
            row.get("supporting_evidence", [])
        )
        doc_languages = sorted(
            {str(by_id[doc].get("language", "unknown")) for doc in gold if doc in by_id}
        )
        filenames = {
            doc: Path(by_id[doc]["relative_path"]).name for doc in gold if doc in by_id
        }
        for language in languages:
            samples.append(
                Sample(
                    id=f"{row['question_id']}:{language}",
                    question_id=row["question_id"],
                    query_language=language,
                    question=row["questions"][language],
                    reference_answer=str(row["answer"]),
                    reference_language="language_neutral",
                    answer_variants=[str(value) for value in row.get("answer_variants", [])],
                    answerable=bool(row.get("answerable", True)),
                    gold_documents=gold,
                    authoritative_documents=list(row.get("authoritative_evidence", [])),
                    gold_pages={},
                    document_languages=doc_languages,
                    metadata={
                        "case_id": row.get("case_id"),
                        "fact_id": row.get("fact_id"),
                        "reasoning_type": row.get("reasoning_type"),
                        "authority_rule": row.get("authority_rule"),
                        "document_filenames": filenames,
                        "stale_or_conflicting_evidence": row.get(
                            "stale_or_conflicting_evidence", []
                        ),
                    },
                )
            )
    return samples


def build_playbook_samples(
    questions: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    languages: list[str],
) -> list[Sample]:
    supported = {"en", "zh"}
    reject_unsupported_languages(languages, supported, "rag_playbook")
    manifest_by_id = {item["document_id"]: item for item in documents}
    samples = []
    for row in questions:
        evidence = row.get("evidence") or []
        gold = list(dict.fromkeys(str(item["document_id"]) for item in evidence))
        pages: dict[str, list[int]] = defaultdict(list)
        filenames: dict[str, str] = {}
        for item in evidence:
            document_id = str(item["document_id"])
            pages[document_id].extend(int(page) for page in item.get("pdf_pages", []))
            filenames[document_id] = str(item.get("filename") or "")
        for document_id in gold:
            manifest = manifest_by_id.get(document_id, {})
            filenames[document_id] = filenames.get(document_id) or str(
                manifest.get("filename") or ""
            )
        for language in languages:
            samples.append(
                Sample(
                    id=f"{row['question_id']}:{language}",
                    question_id=row["question_id"],
                    query_language=language,
                    question=str(row[f"question_{language}"]),
                    reference_answer=str(row["answer_zh"]),
                    reference_language="zh",
                    answer_variants=[str(row["answer_zh"])],
                    answerable=bool(row.get("answerable", True)),
                    gold_documents=gold,
                    authoritative_documents=gold,
                    gold_pages={key: sorted(set(value)) for key, value in pages.items()},
                    document_languages=["en"],
                    metadata={
                        "type": row.get("type"),
                        "document_filenames": filenames,
                        "sections": [item.get("section") for item in evidence],
                    },
                )
            )
    return samples


def reject_unsupported_languages(
    requested: list[str], supported: set[str], dataset: str
) -> None:
    unsupported = sorted(set(requested) - supported)
    if unsupported:
        raise ValueError(
            f"{dataset} has no authored questions for {unsupported}; "
            f"available languages: {sorted(supported)}"
        )


def load_samples(args: argparse.Namespace) -> list[Sample]:
    default_questions, default_documents = default_paths(args.dataset)
    questions_path = (args.questions or default_questions).resolve()
    documents_path = (args.documents_manifest or default_documents).resolve()
    for path in (questions_path, documents_path):
        if not path.is_file():
            raise FileNotFoundError(path)
    questions = load_jsonl(questions_path)
    documents = load_jsonl(documents_path)
    if args.question_ids:
        wanted = set(args.question_ids)
        questions = [row for row in questions if row.get("question_id") in wanted]
        missing = wanted - {str(row.get("question_id")) for row in questions}
        if missing:
            raise ValueError(f"Unknown question IDs: {sorted(missing)}")
    if args.limit is not None:
        questions = questions[: args.limit]
    if args.dataset == "enterprise_v2":
        return build_enterprise_samples(questions, documents, args.query_languages)
    return build_playbook_samples(questions, documents, args.query_languages)


def post_json(
    session: requests.Session, url: str, payload: dict[str, Any], timeout: float
) -> Any:
    response = session.post(url, json=payload, timeout=timeout)
    if response.status_code >= 400:
        raise RuntimeError(f"POST {url} returned {response.status_code}: {response.text[:2000]}")
    return response.json()


def visible_answer(value: str) -> str:
    if "</think>" in value:
        return value.rsplit("</think>", 1)[1].strip()
    return value.strip()


def looks_like_exposed_reasoning(value: str) -> bool:
    return bool(
        re.match(
            r"(?i)^(we need|we must|we have|the question|we should|we are asked)",
            value.strip(),
        )
        or "<think>" in value
        or "</think>" in value
    )


def stream_sse(
    session: requests.Session, url: str, payload: dict[str, Any], timeout: float
) -> dict[str, Any]:
    started = time.perf_counter()
    first_token_at: float | None = None
    content: list[str] = []
    reasoning: list[str] = []
    citations: list[dict[str, Any]] = []
    metrics: dict[str, Any] = {}
    usage: dict[str, Any] = {}
    finish_reason: str | None = None
    with session.post(url, json=payload, stream=True, timeout=timeout) as response:
        if response.status_code >= 400:
            raise RuntimeError(
                f"POST {url} returned {response.status_code}: {response.text[:2000]}"
            )
        for raw_line in response.iter_lines(decode_unicode=True):
            if not raw_line or not raw_line.startswith("data:"):
                continue
            raw_data = raw_line[5:].strip()
            if raw_data == "[DONE]":
                break
            event = json.loads(raw_data)
            choices = event.get("choices") or []
            if choices:
                choice = choices[0]
                finish_reason = choice.get("finish_reason") or finish_reason
                delta = choice.get("delta") or choice.get("message") or {}
                answer_part = str(delta.get("content") or "")
                reasoning_part = str(
                    delta.get("reasoning_content") or delta.get("reasoning") or ""
                )
                if first_token_at is None and (answer_part or reasoning_part):
                    first_token_at = time.perf_counter()
                content.append(answer_part)
                reasoning.append(reasoning_part)
            citation_payload = event.get("citations") or event.get("sources")
            if isinstance(citation_payload, dict) and citation_payload.get("results"):
                citations = citation_payload["results"]
            elif isinstance(citation_payload, list) and citation_payload:
                citations = citation_payload
            metrics.update(event.get("metrics") or {})
            usage.update(event.get("usage") or {})
    raw_answer = "".join(content)
    answer = visible_answer(raw_answer)
    inline_reasoning = "<think>" in raw_answer or "</think>" in raw_answer
    return {
        "answer": answer,
        "raw_answer": raw_answer,
        "reasoning": "".join(reasoning),
        "citations": citations,
        "metrics": metrics,
        "usage": usage,
        "finish_reason": finish_reason,
        "truncated": finish_reason == "length"
        or ("<think>" in raw_answer and "</think>" not in raw_answer),
        "reasoning_in_content": inline_reasoning,
        "reasoning_leaked": looks_like_exposed_reasoning(answer)
        or (inline_reasoning and "</think>" not in raw_answer),
        "client_ttft_seconds": first_token_at - started if first_token_at else None,
        "total_seconds": time.perf_counter() - started,
    }


def model_name(session: requests.Session, llm_url: str, timeout: float) -> str:
    response = session.get(f"{llm_url.rstrip('/')}/models", timeout=timeout)
    response.raise_for_status()
    models = response.json().get("data") or []
    if not models:
        raise RuntimeError("The local LLM endpoint returned no models")
    return str(models[0]["id"])


def common_payload(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "collection_names": [args.collection],
        "vdb_top_k": args.vdb_top_k,
        "reranker_top_k": args.reranker_top_k,
        "enable_reranker": args.reranker == "on",
        "enable_query_rewriting": args.query_rewriting == "on",
        "enable_filter_generator": False,
        "enable_citations": True,
    }


def run_search(
    session: requests.Session, args: argparse.Namespace, question: str
) -> dict[str, Any]:
    started = time.perf_counter()
    payload = {"query": question, **common_payload(args)}
    response = post_json(
        session, f"{args.rag_url.rstrip('/')}/search", payload, args.request_timeout
    )
    return {
        "results": response.get("results") or [],
        "total_results": response.get("total_results"),
        "seconds": time.perf_counter() - started,
    }


def run_generation(
    session: requests.Session, args: argparse.Namespace, question: str
) -> dict[str, Any]:
    payload = {
        "messages": [{"role": "user", "content": question}],
        "use_knowledge_base": True,
        "agentic": args.pipeline == "agentic",
        "temperature": args.temperature,
        "max_tokens": args.max_tokens,
        **common_payload(args),
    }
    return stream_sse(
        session,
        f"{args.rag_url.rstrip('/')}/generate",
        payload,
        args.request_timeout,
    )


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def lexical_tokens(value: str, language: str) -> list[str]:
    value = normalize_text(value)
    if language == "zh":
        compact = re.sub(r"[^\w\u3400-\u9fff]+", "", value)
        return list(compact)
    return re.findall(r"\w+(?:[./%-]\w+)*", value, flags=re.UNICODE)


def sequence_f1(candidate: str, reference: str, language: str) -> float | None:
    candidate_tokens = lexical_tokens(candidate, language)
    reference_tokens = lexical_tokens(reference, language)
    if not candidate_tokens or not reference_tokens:
        return None
    candidate_counts = Counter(candidate_tokens)
    reference_counts = Counter(reference_tokens)
    overlap = sum((candidate_counts & reference_counts).values())
    precision = overlap / len(candidate_tokens)
    recall = overlap / len(reference_tokens)
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def char_bigram_f1(candidate: str, reference: str) -> float | None:
    def bigrams(value: str) -> list[str]:
        chars = lexical_tokens(value, "zh")
        return ["".join(chars[index : index + 2]) for index in range(len(chars) - 1)]

    left, right = bigrams(candidate), bigrams(reference)
    if not left or not right:
        return None
    overlap = sum((Counter(left) & Counter(right)).values())
    precision, recall = overlap / len(left), overlap / len(right)
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def answer_variant_match(candidate: str, variants: list[str]) -> bool | None:
    candidate_normalized = normalize_text(candidate)
    normalized = [normalize_text(value) for value in variants if normalize_text(value)]
    if not normalized:
        return None
    return any(value in candidate_normalized for value in normalized)


def citation_document_id(result: dict[str, Any], sample: Sample) -> str | None:
    name = str(result.get("document_name") or "")
    filenames = sample.metadata.get("document_filenames") or {}
    name_folded = Path(name).name.casefold()
    for document_id, filename in filenames.items():
        if filename and Path(filename).name.casefold() == name_folded:
            return str(document_id)
    return document_id_from_name(name, sample.gold_documents)


def citation_page(result: dict[str, Any], page_base: int) -> int | None:
    metadata = result.get("metadata") or {}
    content_metadata = metadata.get("content_metadata") or {}
    raw = metadata.get("page_number", content_metadata.get("page_number"))
    if raw is None:
        return None
    try:
        page = int(raw)
    except (TypeError, ValueError):
        return None
    return page + 1 if page_base == 0 else page


def retrieval_scores(
    sample: Sample, results: list[dict[str, Any]], page_base: int
) -> dict[str, Any]:
    ranked_ids = [citation_document_id(result, sample) for result in results]
    retrieved = {value for value in ranked_ids if value}
    gold = set(sample.gold_documents)
    authoritative = set(sample.authoritative_documents)
    first_rank = next(
        (rank for rank, value in enumerate(ranked_ids, 1) if value in gold), None
    )
    page_hits = 0
    gold_page_count = sum(len(value) for value in sample.gold_pages.values())
    matched_pages: dict[str, list[int]] = defaultdict(list)
    for result, document_id in zip(results, ranked_ids, strict=False):
        page = citation_page(result, page_base)
        if document_id and page is not None and page in sample.gold_pages.get(document_id, []):
            matched_pages[document_id].append(page)
    page_hits = sum(len(set(value)) for value in matched_pages.values())
    return {
        "retrieved_chunks": len(results),
        "retrieved_gold_documents": sorted(retrieved & gold),
        "document_recall": len(retrieved & gold) / len(gold) if gold else None,
        "authoritative_document_recall": len(retrieved & authoritative) / len(authoritative)
        if authoritative
        else None,
        "reciprocal_rank": 1.0 / first_rank if first_rank else 0.0,
        "matched_gold_pages": dict(matched_pages),
        "page_recall": page_hits / gold_page_count if gold_page_count else None,
    }


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
    sample: Sample,
    answer: str,
    contexts: list[str],
) -> dict[str, Any]:
    context = "\n\n".join(contexts)[:90000]
    prompt = f"""Evaluate a multilingual retrieval-augmented answer using the reference and retrieved context.

Question language: {sample.query_language}
Required answer language: {sample.query_language}
Question: {sample.question}
Reference answer (it may be in another language): {sample.reference_answer}
Answerable from the collection: {sample.answerable}

Retrieved context:
{context or '[no context returned]'}

Candidate answer:
{answer}

Judge meaning, facts, numbers, conditions and exceptions rather than wording. A correct translation or paraphrase must receive the same correctness grade as the reference. Do not reward claims unsupported by the context. The candidate should answer in the question language; common product names and technical terms are allowed in English.

Use integer grades only: 0=wrong/absent, 1=mostly wrong, 2=mixed, 3=mostly correct, 4=fully correct. Return one JSON object and nothing else:
{{
  "correctness_grade": <0-4>,
  "faithfulness_grade": <0-4>,
  "completeness_grade": <0-4>,
  "answer_relevance_grade": <0-4>,
  "language_adherence_grade": <0-4>,
  "pass": <true only if correctness, faithfulness, completeness and relevance are at least 3>,
  "explanation": "<brief reason>"
}}
"""
    result = stream_sse(
        session,
        f"{args.llm_url.rstrip('/')}/chat/completions",
        {
            "model": model,
            "messages": [
                {"role": "system", "content": "Be a strict multilingual RAG evaluator. Output valid JSON only."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.0,
            "max_tokens": args.judge_max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
            "chat_template_kwargs": {"enable_thinking": True},
        },
        args.request_timeout,
    )
    parsed = parse_json_object(result["answer"] or result["reasoning"])
    scored: dict[str, Any] = {
        "pass": bool(parsed.get("pass")),
        "explanation": str(parsed.get("explanation") or ""),
        "judge_seconds": result["total_seconds"],
        "judge_reasoning_tokens_visible": bool(result["reasoning"]),
    }
    dimensions = (
        "correctness",
        "faithfulness",
        "completeness",
        "answer_relevance",
        "language_adherence",
    )
    for dimension in dimensions:
        grade = int(parsed[f"{dimension}_grade"])
        if not 0 <= grade <= 4:
            raise ValueError(f"Judge returned invalid {dimension} grade: {grade}")
        scored[f"{dimension}_grade"] = grade
        scored[dimension] = grade / 4
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


def bool_rate(rows: list[dict[str, Any]], path: tuple[str, ...]) -> float | None:
    values = []
    for row in rows:
        current: Any = row
        for key in path:
            current = current.get(key) if isinstance(current, dict) else None
        if isinstance(current, bool):
            values.append(current)
    return sum(values) / len(values) if values else None


def summarize_group(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "samples": len(rows),
        "successful_samples": sum("error" not in row for row in rows),
        "document_recall": mean(rows, ("retrieval", "scores", "document_recall")),
        "authoritative_document_recall": mean(
            rows, ("retrieval", "scores", "authoritative_document_recall")
        ),
        "page_recall": mean(rows, ("retrieval", "scores", "page_recall")),
        "mrr": mean(rows, ("retrieval", "scores", "reciprocal_rank")),
        "answer_sequence_f1": mean(rows, ("end_to_end", "sequence_f1")),
        "answer_char_bigram_f1": mean(rows, ("end_to_end", "char_bigram_f1")),
        "answer_variant_match_rate": bool_rate(
            rows, ("end_to_end", "answer_variant_match")
        ),
        "judge_pass_rate": bool_rate(rows, ("end_to_end", "judge", "pass")),
        "judge_correctness": mean(rows, ("end_to_end", "judge", "correctness")),
        "judge_faithfulness": mean(rows, ("end_to_end", "judge", "faithfulness")),
        "judge_language_adherence": mean(
            rows, ("end_to_end", "judge", "language_adherence")
        ),
        "truncation_rate": bool_rate(rows, ("end_to_end", "truncated")),
        "reasoning_leak_rate": bool_rate(rows, ("end_to_end", "reasoning_leaked")),
        "mean_ttft_seconds": mean(rows, ("end_to_end", "client_ttft_seconds")),
        "mean_total_seconds": mean(rows, ("end_to_end", "total_seconds")),
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {"overall": rows}
    for row in rows:
        query_language = row["query_language"]
        document_language = row["document_language_group"]
        groups.setdefault(f"query_language={query_language}", []).append(row)
        groups.setdefault(f"document_language={document_language}", []).append(row)
        groups.setdefault(
            f"language_pair={document_language}->{query_language}", []
        ).append(row)
    return {name: summarize_group(items) for name, items in sorted(groups.items())}


def write_summary_csv(path: Path, summary: dict[str, dict[str, Any]]) -> None:
    rows = [{"group": group, **values} for group, values in summary.items()]
    fields = ["group"] + sorted({key for row in rows for key in row} - {"group"})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def select_contexts(results: list[dict[str, Any]]) -> list[str]:
    contexts = []
    for item in results:
        metadata = item.get("metadata") or {}
        contexts.append(
            str(item.get("content") or metadata.get("description") or "")
        )
    return contexts


def run(args: argparse.Namespace, samples: list[Sample]) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    run_dir = (
        args.resume_dir.resolve()
        if args.resume_dir
        else args.results_dir.resolve() / f"{timestamp}-{args.dataset}"
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    responses_path = run_dir / "responses.jsonl"
    rows = load_jsonl(responses_path) if responses_path.exists() else []
    completed = {row["id"] for row in rows if "error" not in row}
    session = requests.Session()
    judge_active = args.judge and "end_to_end" in args.modes
    model = (
        model_name(session, args.llm_url, args.request_timeout) if judge_active else None
    )
    config = {
        "created_at": datetime.now(UTC).isoformat(),
        "dataset": args.dataset,
        "collection": args.collection,
        "model": model,
        "judge_warning": (
            "The generator and judge use the same local model; judge scores are not independent."
            if judge_active
            else None
        ),
        "settings": {
            key: str(value) if isinstance(value, Path) else value
            for key, value in vars(args).items()
        },
        "samples": len(samples),
    }
    (run_dir / "config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if completed:
        print(f"Resuming with {len(completed)} completed sample(s)")
    for index, sample in enumerate(samples, 1):
        if sample.id in completed:
            continue
        print(
            f"[{index}/{len(samples)}] {sample.id} "
            f"({','.join(sample.document_languages) or 'unknown'}->{sample.query_language})",
            flush=True,
        )
        row: dict[str, Any] = {
            **asdict(sample),
            "document_language_group": "+".join(sample.document_languages) or "unknown",
        }
        try:
            search: dict[str, Any] | None = None
            if "retrieval" in args.modes or "end_to_end" in args.modes:
                search = run_search(session, args, sample.question)
                search["scores"] = retrieval_scores(
                    sample, search["results"], args.retrieved_page_base
                )
                row["retrieval"] = search
            if "end_to_end" in args.modes:
                generation = run_generation(session, args, sample.question)
                scoring_language = (
                    sample.reference_language
                    if sample.reference_language != "language_neutral"
                    else sample.query_language
                )
                generation["sequence_f1"] = sequence_f1(
                    generation["answer"], sample.reference_answer, scoring_language
                )
                generation["char_bigram_f1"] = (
                    char_bigram_f1(generation["answer"], sample.reference_answer)
                    if scoring_language == "zh"
                    else None
                )
                generation["answer_variant_match"] = answer_variant_match(
                    generation["answer"],
                    [sample.reference_answer, *sample.answer_variants],
                )
                if args.judge:
                    assert model is not None
                    generation["judge"] = judge_answer(
                        session,
                        args,
                        model,
                        sample,
                        generation["answer"],
                        select_contexts((search or {}).get("results", [])),
                    )
                row["end_to_end"] = generation
        except Exception as exc:
            row["error"] = f"{type(exc).__name__}: {exc}"
            print(f"  ERROR: {row['error']}", flush=True)
            if not args.continue_on_error:
                append_jsonl(responses_path, row)
                raise
        append_jsonl(responses_path, row)
        rows.append(row)
    latest_rows: dict[str, dict[str, Any]] = {}
    for row in rows:
        latest_rows[row["id"]] = row
    rows = list(latest_rows.values())
    summary = summarize(rows)
    report = {"config": config, "summary": summary}
    (run_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_summary_csv(run_dir / "summary.csv", summary)
    failures = [row for row in rows if "error" in row]
    failures_path = run_dir / "failures.jsonl"
    failures_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in failures),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Results: {run_dir}")
    return run_dir


def validate_args(args: argparse.Namespace) -> None:
    if args.limit is not None and args.limit < 1:
        raise ValueError("--limit must be positive")
    if args.vdb_top_k < 1 or args.reranker_top_k < 1:
        raise ValueError("top-k values must be positive")
    if args.reranker_top_k > args.vdb_top_k:
        raise ValueError("--reranker-top-k cannot exceed --vdb-top-k")
    if args.reranker == "off" and args.reranker_top_k != 10:
        print("Note: --reranker-top-k is ignored because reranking is disabled")


def main() -> int:
    args = parse_args()
    validate_args(args)
    samples = load_samples(args)
    print(
        f"Loaded {len(samples)} query instances from {args.dataset}; "
        f"languages={','.join(args.query_languages)}; collection={args.collection}"
    )
    run(args, samples)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
