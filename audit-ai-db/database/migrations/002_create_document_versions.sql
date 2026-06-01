-- 002_create_document_versions.sql
-- Tracks imported file versions for each document.

CREATE TABLE IF NOT EXISTS document_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    version_label TEXT,
    file_name TEXT NOT NULL,
    file_type TEXT,
    file_checksum TEXT,
    source_url TEXT,
    storage_path TEXT,
    is_current BOOLEAN DEFAULT TRUE,
    imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE document_versions IS 'Version history for source documents.';
COMMENT ON COLUMN document_versions.is_current IS 'Marks the version currently preferred for retrieval and review.';
COMMENT ON COLUMN document_versions.file_checksum IS 'Checksum for detecting duplicate or changed source files.';

