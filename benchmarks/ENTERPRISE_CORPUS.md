# Enterprise Corpus Generator

The generator creates deterministic English, Bahasa Melayu, and mixed-language
enterprise documents for ingestion, OCR, retrieval, and answer evaluation.

```bash
.venv-corpus/bin/python scripts/generate_enterprise_corpus.py \
  --profile smoke \
  --output-dir benchmarks/enterprise-corpus-smoke

.venv-corpus/bin/python scripts/validate_enterprise_corpus.py \
  --corpus-dir benchmarks/enterprise-corpus-smoke
```

The scale profile targets approximately 3 GiB:

```bash
.venv-corpus/bin/python scripts/generate_enterprise_corpus.py \
  --profile scale \
  --target-size-gb 3 \
  --output-dir benchmarks/enterprise-corpus
```

Generated corpora and the project-local `.venv-corpus` environment are not
intended for Git.
