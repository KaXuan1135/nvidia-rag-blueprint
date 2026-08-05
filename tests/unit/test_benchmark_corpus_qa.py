"""Unit tests for the corpus QA benchmark adapters and deterministic metrics."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts/benchmark_corpus_qa.py"
SPEC = importlib.util.spec_from_file_location("benchmark_corpus_qa", SCRIPT)
assert SPEC and SPEC.loader
benchmark = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = benchmark
SPEC.loader.exec_module(benchmark)


def test_enterprise_adapter_expands_authored_languages() -> None:
    questions = [
        {
            "question_id": "Q-1",
            "questions": {"en": "Value?", "zh": "数值？", "ms": "Nilai?"},
            "answer": "2 hours RTO",
            "answer_variants": ["RTO 2 hours"],
            "authoritative_evidence": ["DOC-1"],
            "supporting_evidence": ["DOC-2"],
            "answerable": True,
        }
    ]
    documents = [
        {"document_id": "DOC-1", "relative_path": "a/DOC-1_en.pdf", "language": "en"},
        {"document_id": "DOC-2", "relative_path": "b/DOC-2_zh.md", "language": "zh"},
    ]

    samples = benchmark.build_enterprise_samples(
        questions, documents, ["en", "zh", "ms"]
    )

    assert [sample.id for sample in samples] == ["Q-1:en", "Q-1:zh", "Q-1:ms"]
    assert samples[0].gold_documents == ["DOC-1", "DOC-2"]
    assert samples[0].document_languages == ["en", "zh"]


def test_playbook_adapter_keeps_chinese_reference_for_english_query() -> None:
    questions = [
        {
            "question_id": "PB-1",
            "question_en": "What is the limit?",
            "question_zh": "限额是多少？",
            "answer_zh": "限额是 500 令吉。",
            "answerable": True,
            "evidence": [
                {
                    "document_id": "PLAYBOOK-1",
                    "filename": "policy.pdf",
                    "pdf_pages": [7],
                }
            ],
        }
    ]
    samples = benchmark.build_playbook_samples(questions, [], ["en"])

    assert samples[0].query_language == "en"
    assert samples[0].reference_language == "zh"
    assert samples[0].gold_pages == {"PLAYBOOK-1": [7]}


def test_retrieval_scores_match_filename_and_zero_based_page() -> None:
    sample = benchmark.Sample(
        id="PB-1:en",
        question_id="PB-1",
        query_language="en",
        question="Question",
        reference_answer="Answer",
        reference_language="en",
        answer_variants=[],
        answerable=True,
        gold_documents=["PLAYBOOK-1"],
        authoritative_documents=["PLAYBOOK-1"],
        gold_pages={"PLAYBOOK-1": [7]},
        document_languages=["en"],
        metadata={"document_filenames": {"PLAYBOOK-1": "policy.pdf"}},
    )
    results = [
        {
            "document_name": "policy.pdf",
            "metadata": {"page_number": 6, "content_metadata": {}},
        }
    ]

    scores = benchmark.retrieval_scores(sample, results, page_base=0)

    assert scores["document_recall"] == 1.0
    assert scores["page_recall"] == 1.0
    assert scores["reciprocal_rank"] == 1.0


def test_multilingual_lexical_metrics_are_unicode_aware() -> None:
    assert benchmark.sequence_f1("限额是500令吉", "限额是 500 令吉。", "zh") == 1.0
    assert benchmark.char_bigram_f1("限额是500令吉", "限额是 500 令吉。") == 1.0
    assert benchmark.answer_variant_match("The RTO is 2 HOURS.", ["2 hours"]) is True


def test_adapter_rejects_synthetic_language_generation() -> None:
    try:
        benchmark.build_playbook_samples([], [], ["ms"])
    except ValueError as exc:
        assert "no authored questions" in str(exc)
    else:
        raise AssertionError("Expected unsupported language to be rejected")
