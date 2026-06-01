-- 007_add_full_text_search_indexes.sql
-- Adds keyword and full-text search support for hybrid retrieval.

CREATE EXTENSION IF NOT EXISTS pg_trgm;

ALTER TABLE document_chunks
    ADD COLUMN IF NOT EXISTS search_vector tsvector
    GENERATED ALWAYS AS (
        to_tsvector(
            'simple',
            coalesce(heading_path, '') || ' ' ||
            coalesce(section_title, '') || ' ' ||
            coalesce(clause_number, '') || ' ' ||
            coalesce(chunk_text, '')
        )
    ) STORED;

CREATE INDEX IF NOT EXISTS idx_document_chunks_search_vector
    ON document_chunks
    USING gin (search_vector);

CREATE INDEX IF NOT EXISTS idx_document_chunks_chunk_text_trgm
    ON document_chunks
    USING gin (chunk_text gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_document_chunks_heading_path_trgm
    ON document_chunks
    USING gin (heading_path gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_document_chunks_clause_number
    ON document_chunks (clause_number);

CREATE INDEX IF NOT EXISTS idx_documents_keywords_gin
    ON documents
    USING gin (keywords);

CREATE INDEX IF NOT EXISTS idx_documents_main_topics_gin
    ON documents
    USING gin (main_topics);

COMMENT ON COLUMN document_chunks.search_vector IS 'Generated full-text vector over chunk text and structural labels for keyword retrieval.';
