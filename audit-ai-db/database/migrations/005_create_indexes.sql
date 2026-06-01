-- 005_create_indexes.sql
-- Adds lookup indexes for common filtering and relationship joins.

CREATE INDEX IF NOT EXISTS idx_documents_internal_code
    ON documents (internal_code);

CREATE INDEX IF NOT EXISTS idx_documents_document_type
    ON documents (document_type);

CREATE INDEX IF NOT EXISTS idx_documents_status
    ON documents (status);

CREATE INDEX IF NOT EXISTS idx_documents_title
    ON documents (title);

CREATE INDEX IF NOT EXISTS idx_document_versions_document_id
    ON document_versions (document_id);

CREATE INDEX IF NOT EXISTS idx_document_versions_is_current
    ON document_versions (is_current);

CREATE INDEX IF NOT EXISTS idx_document_chunks_document_id
    ON document_chunks (document_id);

CREATE INDEX IF NOT EXISTS idx_document_chunks_version_id
    ON document_chunks (version_id);

CREATE INDEX IF NOT EXISTS idx_document_chunks_source_structure_type
    ON document_chunks (source_structure_type);

CREATE INDEX IF NOT EXISTS idx_document_chunks_section_title
    ON document_chunks (section_title);

CREATE INDEX IF NOT EXISTS idx_ingestion_logs_document_id
    ON ingestion_logs (document_id);

CREATE INDEX IF NOT EXISTS idx_ingestion_logs_status
    ON ingestion_logs (status);

