# AGENTS.md

Repository guide for Codex and other coding agents working in this project.

## First Rule

Do not rely only on chat history. Before editing, inspect the current tree:

```bash
git status --short
find . -maxdepth 2 -type f | sort
find . -maxdepth 2 -type d | sort
```

This repo has been actively refactored. Some features may be present as new
untracked files during development. Work with the files that actually exist.

## Project Goal

This project is an internal audit/legal knowledge assistant.

The intended architecture is:

```text
database/   PostgreSQL schema, migrations, seed data
ingestion/  PDF/DOCX ingestion into PostgreSQL
rag/        retrieval, embeddings, context building, answer generation
agent/      LangGraph-style workflow using tools and LLM decisions
```

The core product behavior is:

```text
documents
-> ingestion writes documents/chunks into DB
-> RAG retrieves evidence chunks
-> agent coordinates search, evidence judgment, retries, answer generation
-> final answer cites source labels like [S1]
```

## Safety Boundaries

Never put secrets in the repo. `.env` may contain local keys and must not be
printed or committed.

Do not give the LLM raw write access to the database. The design is:

```text
LLM -> controlled Python tools -> RAG/search functions -> PostgreSQL
```

Avoid this pattern unless explicitly requested and heavily guarded:

```text
LLM -> arbitrary SQL -> database
```

If SQL tools are added later, they must be read-only, schema-aware, allowlisted,
and tested.

Do not run destructive database commands or `docker compose down -v` unless the
user explicitly asks for data removal.

## Current Main Commands

Set up Python:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Start DB:

```bash
docker compose up -d
docker compose ps
```

Run migrations:

```bash
for file in database/migrations/*.sql; do
  docker compose exec -T postgres psql -U audit_user -d audit_ai_db < "$file"
done
```

Run seed data:

```bash
docker compose exec -T postgres psql -U audit_user -d audit_ai_db < database/seed/001_sample_documents.sql
```

Compile check:

```bash
.venv/bin/python -m compileall ingestion rag agent
```

Focused tests, if the folders exist:

```bash
.venv/bin/python -m unittest \
  ingestion.tests.test_hybrid_ingestion \
  rag.tests.test_agentic_search \
  agent.tests.test_agent_tools \
  agent.tests.test_llm_agent_graph \
  agent.tests.test_llm_agent_prompts \
  agent.tests.test_run_eval
```

If some modules do not exist in the current tree, run only the tests that exist.

## Ingestion Layer

Prefer one ingestion folder:

```text
ingestion/
```

The intended clean structure is:

```text
ingestion/run_hybrid_ingestion.py  main single-file ingestion command
ingestion/run_folder.py            main folder ingestion command
ingestion/hybrid/                  strategy routing and shared pipeline
ingestion/gemini/                  Gemini reader/chunker provider
ingestion/legacy/                  old local/Gemini backup paths
```

Preferred commands:

```bash
python -m ingestion.run_hybrid_ingestion "data/raw/example.pdf" --strategy auto --no-db --json
python -m ingestion.run_folder data/raw --strategy auto --dry-run
```

Hybrid ingestion should:

```text
load file
-> prepare metadata
-> checksum
-> version check
-> choose strategy
-> read document
-> chunk document
-> normalize chunks into ChunkRecord
-> write DB
-> write ingestion log
```

Strategy rules:

```text
--strategy auto    DOCX/text-rich PDF -> local; image-heavy PDF -> Gemini
--strategy local   force deterministic local extraction/chunking
--strategy gemini  force Gemini reader/chunker
```

Keep Gemini provider code under `ingestion/gemini/`, not in a separate top-level
package.

## RAG Layer

If present, `rag/` owns retrieval and answer context building.

Expected search methods:

```text
keyword search   exact/full-text/trigram matches over chunks
metadata search  document title/type/keywords/topics/source fields
vector search    semantic search over chunk_embeddings
agentic search   small LLM planner that creates extra validated search queries
hybrid search    merges/ranks/dedupes all enabled methods
```

The small search agent must not write SQL or access the database directly. It
should only return validated JSON:

```json
{
  "reason": "brief reason",
  "queries": [
    {"query": "資料共享 個資應告知事項 契據文件", "purpose": "document_phrase_match"}
  ],
  "filters": {"status": "active", "language": "zh-TW"}
}
```

Then Python runs those queries through safe RAG functions.

Useful commands, if `rag/` exists:

```bash
python -m rag.run_search "資料共享是否需要告知客戶？" --limit 5
python -m rag.run_search "資料共享是否需要告知客戶？" --vector --agentic --limit 5
python -m rag.embed_chunks --dry-run --limit 10
python -m rag.embed_chunks --limit 25
```

## Agent Layer

If present, `agent/` owns orchestration. The agent should use controlled tools,
not raw SQL.

Expected flow:

```text
normalize question
-> plan search tasks
-> retrieve evidence
-> select evidence
-> judge evidence
-> retry if weak
-> generate cited answer
-> verify citations
-> write run log
```

Expected split of responsibilities:

```text
Python tools:
  normalize question
  retrieve evidence
  rank/dedupe evidence
  build answer context
  verify citations
  write logs

LLM:
  plan search queries
  judge evidence sufficiency
  generate final cited answer

LangGraph/workflow:
  order the steps
  route retry vs answer
```

Preferred command, if `agent/` exists:

```bash
python -m agent.run "資料共享是否需要告知客戶？" --vector
python -m agent.run "資料共享是否需要告知客戶？" --vector --agentic-search
python -m agent.run "資料共享是否需要告知客戶？" --dry-run --json
```

Dry-run should avoid final answer LLM calls. If agentic search calls Gemini, keep
it disabled during dry-run unless explicitly requested.

## Prompt Standards

Prompts for LLM decisions should be explicit and structured:

```text
Role
Situation
Task
Rules
Output Format
Examples
Current Input
```

For JSON decisions, use both:

```text
1. prompt-level JSON instructions
2. API-level structured output / response schema when supported
```

Always validate LLM output in Python before using it.

Do not allow LLM outputs to:

```text
execute SQL
change filters outside an allowlist
invent source labels
skip citation verification
loosen user-provided filters
```

Allowed search filters:

```text
document_type
status
source_system
language
```

## Database Notes

Core tables:

```text
documents
document_versions
document_chunks
chunk_embeddings
ingestion_logs
```

Document versioning rules:

```text
new internal_code + checksum      insert document/version/chunks
same internal_code + same checksum skip duplicate
same internal_code + new checksum  mark old versions non-current, insert new version/chunks
```

Search should normally use only current versions:

```sql
document_versions.is_current = TRUE
```

## Coding Standards

Use existing dataclasses in `ingestion/models.py` and `rag/search_models.py`
instead of introducing incompatible shapes.

Prefer adding small modules with clear responsibilities over large mixed
orchestrator files.

Keep DB writing in shared writer/helper code. Avoid duplicating version-check and
transaction logic.

When moving files, preserve compatibility wrappers if existing commands may be
used by the user.

Avoid broad refactors unrelated to the request.

## Verification

Before final response after code changes:

```bash
.venv/bin/python -m compileall ingestion rag agent
```

Run focused unit tests for changed areas. Example:

```bash
.venv/bin/python -m unittest ingestion.tests.test_hybrid_ingestion
.venv/bin/python -m unittest rag.tests.test_agentic_search
.venv/bin/python -m unittest agent.tests.test_llm_agent_prompts
```

If a command cannot run because files do not exist in the current tree, say that
clearly in the final response and run the closest available check.

After compile/tests, remove generated bytecode if it appears in the workspace:

```bash
find ingestion rag agent -type d -name __pycache__ -prune -exec rm -r {} +
```

## Communication

When explaining to the user, keep the mental model simple:

```text
DB = memory
ingestion = puts documents into memory
RAG = searches memory
agent = controls the workflow
LLM = reasoning brain
Python tools = safe hands
```

Use concrete examples, especially:

```text
資料共享是否需要告知客戶？
```

The user is learning the architecture while building it. Explain one layer at a
time when asked.

