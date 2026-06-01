# Audit AI Database

This folder contains the PostgreSQL database foundation and MVP document ingestion pipeline for an internal AI audit and regulation knowledge assistant.

It currently includes:

- Docker-based PostgreSQL with pgvector support
- SQL migrations
- sample document metadata
- Python ingestion for local PDF and DOCX files

It does not include embedding generation, RAG orchestration, agents, chatbot workflows, OCR, internal database crawling, or frontend code.

## Requirements

- Docker
- Docker Compose
- A PostgreSQL client such as DBeaver, psql, or DataGrip
- Python 3.11+

## Start PostgreSQL

Create a local environment file from the example:

```bash
cp .env.example .env
```

Start PostgreSQL:

```bash
docker compose up -d
```

Check the container:

```bash
docker compose ps
```

## Stop PostgreSQL

Stop the database container while keeping the named Docker volume:

```bash
docker compose down
```

To also delete the persisted database volume:

```bash
docker compose down -v
```

Use `down -v` only when you intentionally want to remove all local database data.

## Connection Details

Default values from `.env.example`:

- Host: `localhost`
- Port: `5432`
- Database: `audit_ai_db`
- Username: `audit_user`
- Password: `audit_password`

## Connect with DBeaver

1. Create a new PostgreSQL connection.
2. Set Host to `localhost`.
3. Set Port to `5432`.
4. Set Database to `audit_ai_db`.
5. Set Username to `audit_user`.
6. Set Password to `audit_password`.
7. Test the connection, then save it.

If you changed `.env`, use those values instead.

## Run Migrations

Run migrations in numeric order after PostgreSQL is running:

```bash
for file in database/migrations/*.sql; do
  docker compose exec -T postgres psql -U audit_user -d audit_ai_db < "$file"
done
```

You can also run a single migration manually:

```bash
docker compose exec -T postgres psql -U audit_user -d audit_ai_db < database/migrations/001_create_documents.sql
```

## Run Seed Data

After the migrations are complete, insert the sample documents:

```bash
docker compose exec -T postgres psql -U audit_user -d audit_ai_db < database/seed/001_sample_documents.sql
```

The seed file is idempotent by `internal_code`, so it can be run more than once.

## Run Document Ingestion

Install the Python dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Ingest one local DOCX or PDF:

```bash
python -m ingestion.run_ingestion \
  "data/raw/example.docx" \
  --internal-code "POLICY-AI-SERVICE-001" \
  --document-type "internal_rule" \
  --source-system "internal_regulation_db" \
  --language "zh-TW"
```

See `ingestion/README.md` for the pipeline stages, duplicate/version behavior, and supported document types.

## Tables

### documents

Stores document-level metadata such as title, document type, source location, responsible unit, keywords, topics, and status.

### document_versions

Stores version history for each document, including file name, checksum, source URL, storage path, and whether the version is current.

### document_chunks

Stores searchable text chunks derived from document versions. It includes section and structure metadata such as heading path, section title, clause number, page range, and text content.

### chunk_embeddings

Stores vector embeddings for `document_chunks`, including the embedding model, vector dimension, optional source text checksum, and vector index support for semantic retrieval.

### ingestion_logs

Tracks document import attempts, including source details, processing status, stage, chunk count, summary generation flag, errors, and timing.

## Migration Files

- `001_create_documents.sql`: enables UUID support and creates the `documents` table.
- `002_create_document_versions.sql`: creates document version history.
- `003_create_document_chunks.sql`: creates searchable document chunks.
- `004_create_ingestion_logs.sql`: creates import attempt logs.
- `005_create_indexes.sql`: creates lookup and join indexes.
- `006_add_pgvector_chunk_embeddings.sql`: enables pgvector and creates chunk embedding storage.
- `007_add_full_text_search_indexes.sql`: adds full-text and trigram indexes for keyword retrieval.
