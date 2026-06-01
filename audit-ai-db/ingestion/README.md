# Document Ingestion Pipeline

This package ingests one local PDF or DOCX into the existing PostgreSQL schema:

- `documents`
- `document_versions`
- `document_chunks`
- `ingestion_logs`

It intentionally does not include RAG, embeddings, frontend code, OCR, LangChain, LlamaIndex, or chatbot logic.

## Install Dependencies

From `audit-ai-db/`:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run One Ingestion

Start PostgreSQL and run the database migrations first. Then:

```bash
python -m ingestion.run_ingestion \
  "data/raw/example.docx" \
  --internal-code "POLICY-AI-SERVICE-001" \
  --document-type "internal_rule" \
  --source-system "internal_regulation_db" \
  --language "zh-TW"
```

## Run Folder Test

Put real `.docx` and `.pdf` files into:

```text
data/raw/
```

Then run:

```bash
python -m ingestion.run_folder data/raw
```

The folder runner ingests supported files one by one and prints one result per file.
It skips unsupported files such as `.xlsx`.
It also writes a CSV report to:

```text
data/processed/ingestion_report.csv
```

To preview what it will do without writing to PostgreSQL:

```bash
python -m ingestion.run_folder data/raw --dry-run
```

To choose another report path:

```bash
python -m ingestion.run_folder data/raw --report-path data/processed/my_report.csv
```

The MVP infers document type from the filename:

- names containing `適法性`, `個資法`, `法務`, `疑義`, `法之虞`, or `意見` -> `legal_opinion`
- names containing `使用說明`, `操作`, `平台`, `系統`, `工具`, `申請`, `Hadoop`, or `R語言` -> `system_manual`
- all others -> `internal_rule`

## Run Claude Ingestion Path

The Claude path is a second ingestion route for harder files, especially PDFs
that the rule-based path cannot extract. It uses the official Anthropic API for
page reading and chunk JSON generation, then writes through the same PostgreSQL
tables as the rule-based path.

Add your API key to `.env`:

```text
ANTHROPIC_API_KEY=your_anthropic_api_key_here
ANTHROPIC_MODEL=claude-sonnet-4-5-20250929
```

Recommended first test: parse only a couple of pages and do not write to DB:

```bash
python -m ingestion.run_claude_ingestion \
  "data/raw/CathayBox新功能有無違反個資法之虞 copy/CathayBox新功能有無違反個資法之虞.pdf" \
  --internal-code "CLAUDE-TEST-CATHAYBOX-001" \
  --document-type "legal_opinion" \
  --source-system "claude_test" \
  --language "zh-TW" \
  --max-pages 2 \
  --no-db
```

If the Markdown and chunks JSON look good, run without `--max-pages` and
without `--no-db` to write into PostgreSQL:

```bash
python -m ingestion.run_claude_ingestion \
  "data/raw/CathayBox新功能有無違反個資法之虞 copy/CathayBox新功能有無違反個資法之虞.pdf" \
  --internal-code "CLAUDE-CATHAYBOX-001" \
  --document-type "legal_opinion" \
  --source-system "claude_ingestion" \
  --language "zh-TW"
```

Claude path outputs are written to:

```text
data/processed/claude_pipeline/
├── markdown/
├── page_analysis/
├── page_images/
├── chunks/
├── chunk_raw/
└── token_usage/
```

The Claude runner prints total input/output tokens and writes per-call usage to
`token_usage/*.usage.json`.
Raw Claude chunking responses are saved under `chunk_raw/`. If Claude returns
malformed JSON, the runner retries once with a JSON repair prompt and saves both
the raw and repaired responses for inspection.

For a folder-level Claude dry run:

```bash
python -m ingestion.run_claude_folder \
  "data/raw/CathayBox新功能有無違反個資法之虞 copy" \
  --dry-run \
  --limit 3
```

For a small folder-level Claude parse test without database writes:

```bash
python -m ingestion.run_claude_folder \
  "data/raw/CathayBox新功能有無違反個資法之虞 copy" \
  --no-db \
  --vision-mode minimal \
  --max-vision-pages-per-file 10
```

The Claude folder runner is cost-safe by default:

- `--vision-mode minimal` sends only image-only/scanned PDF pages to Claude Vision.
- Mixed text+image PDF pages use local text extraction instead of Claude Vision.
- PDFs are skipped when a DOCX with the same filename stem exists.
- `--max-vision-pages-per-file 10` skips very large scanned PDFs instead of letting one file consume a large number of calls.
- Use `--include-pdf-duplicates` only when you intentionally want to process both DOCX and PDF copies.
- Use `--vision-mode full` only when image-heavy mixed pages must be read by Claude Vision.

Supported document types for structure detection:

- `internal_rule`
- `legal_opinion`
- `system_manual`

`policy_guideline` maps to internal rule chunking, and `user_manual` maps to system manual chunking.

## Duplicate and Version Rules

- New `internal_code`: insert one document row, one version row, chunks, summary fields, and one log row.
- Same `internal_code` and same current checksum: skip extraction and write one `skipped_duplicate` log row.
- Same `internal_code` and different checksum: mark old versions non-current, insert a new version and chunks, update document metadata and summary fields, and write one log row.
