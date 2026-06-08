# Legacy Ingestion Paths

These files are kept for backup and debugging.

Use the hybrid ingestion path for normal work:

```bash
python -m ingestion.run_hybrid_ingestion "data/raw/example.pdf" --strategy auto
```

Legacy files:

```text
local_ingestion.py   old local deterministic single-file ingestion
gemini_ingestion.py  old standalone Gemini single-file ingestion
```

The old local public module still exists as a compatibility wrapper:

```text
ingestion.run_ingestion
```
