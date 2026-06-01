-- 003_create_document_chunks.sql
-- Stores searchable chunks derived from document versions.
-- No embedding/vector columns are included yet; this is the MVP relational foundation only.

CREATE TABLE IF NOT EXISTS document_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    version_id UUID NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
    parent_chunk_id UUID REFERENCES document_chunks(id),
    chunk_index INTEGER NOT NULL,
    chunk_level TEXT,
    source_structure_type TEXT,
    heading_path TEXT,
    section_title TEXT,
    clause_number TEXT,
    page_start INTEGER,
    page_end INTEGER,
    chunk_text TEXT NOT NULL,
    token_count INTEGER,
    char_count INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE document_chunks IS 'Searchable text chunks prepared from imported document versions.';
COMMENT ON COLUMN document_chunks.parent_chunk_id IS 'Optional parent chunk for hierarchical document structures.';
COMMENT ON COLUMN document_chunks.source_structure_type IS 'Source structure label, such as heading, section, clause, paragraph, or table.';

