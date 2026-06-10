-- 008_add_document_version_metadata.sql
-- Adds document lifecycle metadata for version-aware retrieval.

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS issuing_unit TEXT,
    ADD COLUMN IF NOT EXISTS effective_date DATE,
    ADD COLUMN IF NOT EXISTS effective_year INTEGER,
    ADD COLUMN IF NOT EXISTS revision_date DATE,
    ADD COLUMN IF NOT EXISTS document_family TEXT,
    ADD COLUMN IF NOT EXISTS normalized_version_label TEXT,
    ADD COLUMN IF NOT EXISTS is_latest BOOLEAN DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS supersedes_document_id UUID REFERENCES documents(id);

CREATE INDEX IF NOT EXISTS idx_documents_issuing_unit
    ON documents (issuing_unit);

CREATE INDEX IF NOT EXISTS idx_documents_effective_year
    ON documents (effective_year);

CREATE INDEX IF NOT EXISTS idx_documents_effective_date
    ON documents (effective_date);

CREATE INDEX IF NOT EXISTS idx_documents_document_family
    ON documents (document_family);

CREATE INDEX IF NOT EXISTS idx_documents_is_latest
    ON documents (is_latest);

CREATE INDEX IF NOT EXISTS idx_documents_family_latest
    ON documents (document_family, is_latest, effective_date);

COMMENT ON COLUMN documents.issuing_unit IS 'Unit or department responsible for issuing or owning the document.';
COMMENT ON COLUMN documents.effective_date IS 'Date when the document became effective, if extractable.';
COMMENT ON COLUMN documents.effective_year IS 'Effective year derived from effective_date or source text.';
COMMENT ON COLUMN documents.revision_date IS 'Latest revision or amendment date, if extractable.';
COMMENT ON COLUMN documents.document_family IS 'Normalized family key used to group old/new versions of the same logical document.';
COMMENT ON COLUMN documents.normalized_version_label IS 'Human-readable normalized version label such as 2026 or 2026-03-01.';
COMMENT ON COLUMN documents.is_latest IS 'Marks the latest active document in a document family.';
COMMENT ON COLUMN documents.supersedes_document_id IS 'Previous document superseded by this document, when known.';
