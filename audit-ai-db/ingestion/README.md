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

## Run One Hybrid Ingestion

Start PostgreSQL and run the database migrations first. Then:

```bash
python -m ingestion.run_hybrid_ingestion \
  "data/raw/example.pdf" \
  --internal-code "HYBRID-DOC-001" \
  --document-type "internal_rule" \
  --source-system "hybrid_ingestion" \
  --language "zh-TW" \
  --strategy auto
```

The hybrid entrypoint is the preferred ingestion path. It combines the local
deterministic path and the Gemini path behind one shared pipeline:

```text
load file
-> prepare metadata
-> checksum + version check
-> choose local or Gemini strategy
-> read + chunk into common ChunkRecord objects
-> write documents/document_versions/document_chunks
-> write ingestion_logs
```

Use `--strategy auto` for normal work. It keeps text-rich DOCX/PDF files on the
local path and routes image-heavy or low-text PDFs to Gemini.

Preview without writing PostgreSQL:

```bash
python -m ingestion.run_hybrid_ingestion \
  "data/raw/example.pdf" \
  --internal-code "HYBRID-TEST-001" \
  --document-type "legal_opinion" \
  --source-system "hybrid_test" \
  --strategy auto \
  --no-db \
  --json
```

Write to PostgreSQL after the preview looks good:

```bash
python -m ingestion.run_hybrid_ingestion \
  "data/raw/example.pdf" \
  --internal-code "HYBRID-DOC-001" \
  --document-type "legal_opinion" \
  --source-system "hybrid_ingestion" \
  --strategy auto
```

Force one path when debugging:

```bash
python -m ingestion.run_hybrid_ingestion "data/raw/example.docx" --strategy local --no-db
python -m ingestion.run_hybrid_ingestion "data/raw/example.pdf" --strategy gemini --no-db
```

Gemini artifacts from the hybrid path are written to:

```text
data/processed/hybrid_pipeline/
├── markdown/
├── page_analysis/
├── page_images/
├── chunks/
├── chunk_raw/
└── token_usage/
```

This path is graph-ready but does not build the knowledge graph yet. It preserves
the metadata needed later for graph nodes and edges, including `chunk_level`,
`source_structure_type`, `heading_path`, `section_title`, `clause_number`, and
page ranges.

## Run Hybrid Folder Ingestion

Put real `.docx` and `.pdf` files into:

```text
data/raw/
```

Then run:

```bash
python -m ingestion.run_folder data/raw --strategy auto
```

The folder runner now uses the hybrid pipeline for supported files and prints
one result per file, including the selected strategy.
It skips unsupported files such as `.xlsx`.
It also writes a CSV report to:

```text
data/processed/ingestion_report.csv
```

To preview what it will do without writing to PostgreSQL:

```bash
python -m ingestion.run_folder data/raw --dry-run
```

To parse/chunk files without writing PostgreSQL:

```bash
python -m ingestion.run_folder data/raw --strategy auto --no-db
```

To choose another report path:

```bash
python -m ingestion.run_folder data/raw --report-path data/processed/my_report.csv
```

The MVP infers document type from the filename:

- names containing `適法性`, `個資法`, `法務`, `疑義`, `法之虞`, or `意見` -> `legal_opinion`
- names containing `使用說明`, `操作`, `平台`, `系統`, `工具`, `申請`, `Hadoop`, or `R語言` -> `system_manual`
- all others -> `internal_rule`

## Legacy Claude Ingestion Path

The Claude path is kept as a legacy/debug route. The preferred path is now
`ingestion.run_hybrid_ingestion`. Use Claude only when you intentionally want to
compare providers or debug Claude-specific parsing.

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

## Gemini Provider

Do not commit the real key. On the company laptop, add it only to `.env`:

```text
GEMINI_API_KEY=
GEMINI_MODEL=gemini-1.5-pro
```

Gemini reader/chunker code lives under `ingestion/gemini/` and is called through
the hybrid pipeline. Force Gemini when debugging image-heavy PDFs:

```bash
python -m ingestion.run_hybrid_ingestion \
  "data/raw/example.pdf" \
  --internal-code "GEMINI-TEST-001" \
  --document-type "legal_opinion" \
  --source-system "gemini_test" \
  --language "zh-TW" \
  --max-pages 2 \
  --no-db
```

If the Markdown and chunks JSON look good, run through hybrid without
`--max-pages` and without `--no-db` to write into PostgreSQL:

```bash
python -m ingestion.run_hybrid_ingestion \
  "data/raw/example.pdf" \
  --internal-code "GEMINI-DOC-001" \
  --document-type "legal_opinion" \
  --source-system "gemini_ingestion" \
  --language "zh-TW" \
  --strategy gemini
```

Hybrid Gemini artifacts are written to:

```text
data/processed/hybrid_pipeline/
├── markdown/
├── page_analysis/
├── page_images/
├── chunks/
├── chunk_raw/
└── token_usage/
```

Supported document types for structure detection:

- `internal_rule`
- `legal_opinion`
- `system_manual`

`policy_guideline` maps to internal rule chunking, and `user_manual` maps to system manual chunking.

## Duplicate and Version Rules

- New `internal_code`: insert one document row, one version row, chunks, summary fields, and one log row.
- Same `internal_code` and same current checksum: skip extraction and write one `skipped_duplicate` log row.
- Same `internal_code` and different checksum: mark old versions non-current, insert a new version and chunks, update document metadata and summary fields, and write one log row.
