# RAG Retrieval

This package contains the retrieval layer for the audit AI knowledge base.

V1 combines:

- chunk keyword/full-text search over `document_chunks`
- trigram fuzzy matching for Chinese text without spaces
- document metadata search over title, type, keywords, topics, summary, and source fields
- optional agentic search expansion through a small Gemini search planner

Run from `audit-ai-db/` after PostgreSQL is running and migrations are applied:

```bash
python -m rag.run_search "客戶資料共享是否需要客戶同意？" --limit 5
```

Useful filters:

```bash
python -m rag.run_search "AI服務管理" --document-type internal_rule --limit 5
python -m rag.run_search "個資法" --metadata-only
python -m rag.run_search "客戶資料" --keyword-only --json
```

V2 adds vector search using `chunk_embeddings`.

On the company laptop, add the company Gemini key and embedding settings to
`.env`:

```text
GEMINI_API_KEY=
GEMINI_EMBEDDING_MODEL=gemini-embedding-001
GEMINI_EMBEDDING_DIMENSION=1536
```

Smoke-test embeddings without printing the vector:

```bash
python -m rag.test_embedding
```

Embed stored chunks into PostgreSQL:

```bash
python -m rag.embed_chunks --limit 25
```

Preview which chunks would be embedded without API calls:

```bash
python -m rag.embed_chunks --dry-run --limit 10
```

Run vector-only or true hybrid search:

```bash
python -m rag.run_search "客戶資料共享是否需要客戶同意？" --vector-only --limit 5
python -m rag.run_search "客戶資料共享是否需要客戶同意？" --vector --limit 5
```

Add the small search agent when exact terms may miss formal document wording:

```bash
python -m rag.run_search "資料共享是否需要告知客戶？" --agentic --limit 5
python -m rag.run_search "資料共享是否需要告知客戶？" --vector --agentic --limit 5
```

The search agent does not write SQL and does not read the database directly. It
only returns validated JSON:

```text
queries
filters
reason
```

Python then runs the approved queries through keyword, metadata, and optional
vector search.

V3 adds grounded answer generation:

```bash
python -m rag.run_answer "客戶資料共享是否需要客戶同意？" --limit 6
```

Preview retrieved context without calling Gemini:

```bash
python -m rag.run_answer "客戶資料共享是否需要客戶同意？" --limit 6 --no-llm
```

Use vector retrieval in the answer flow after embeddings exist:

```bash
python -m rag.run_answer "客戶資料共享是否需要客戶同意？" --vector --limit 6
```

The answer prompt requires Traditional Chinese output, inline source labels such
as `[S1]`, and no unsupported claims outside the retrieved sources.
