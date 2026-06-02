# Company Gemini Ingestion

This folder contains the company-laptop Gemini ingestion path. It is separate
from the default `ingestion/` package and the Claude ingestion path.

It reuses shared project helpers for file loading, metadata, PostgreSQL writes,
and ingestion logs, but all company Gemini API calls and Gemini-specific
chunking live in this folder.

Do not commit a real Gemini API key. Add the key only to `.env` on the company
laptop:

```text
GEMINI_API_KEY=
GEMINI_MODEL=gemini-1.5-pro
```

Install dependencies from `audit-ai-db/`:

```bash
pip install -r requirements.txt
```

Recommended first test without database writes:

```bash
python -m company_gemini_ingestion.run_gemini_ingestion \
  "data/raw/example.pdf" \
  --internal-code "GEMINI-TEST-001" \
  --document-type "legal_opinion" \
  --source-system "gemini_test" \
  --language "zh-TW" \
  --max-pages 2 \
  --no-db
```

Folder dry run without API calls:

```bash
python -m company_gemini_ingestion.run_gemini_folder data/raw --dry-run --limit 3
```

Folder parse test without database writes:

```bash
python -m company_gemini_ingestion.run_gemini_folder \
  data/raw \
  --no-db \
  --vision-mode minimal \
  --max-vision-pages-per-file 10
```

