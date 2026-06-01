-- 001_create_documents.sql
-- Stores document-level metadata for internal audit, legal, policy, and regulation knowledge.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    internal_code TEXT UNIQUE,
    title TEXT NOT NULL,
    document_type TEXT NOT NULL,
    data_type TEXT,
    short_summary TEXT,
    keywords TEXT[],
    main_topics TEXT[],
    system_category TEXT,
    responsible_unit TEXT,
    source_system TEXT,
    source_record_id TEXT,
    source_url TEXT,
    storage_path TEXT,
    original_file_name TEXT,
    file_type TEXT,
    language TEXT DEFAULT 'zh-TW',
    status TEXT DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE documents IS 'Document-level metadata for audit and regulation knowledge sources.';
COMMENT ON COLUMN documents.internal_code IS 'Stable internal reference code used by business teams.';
COMMENT ON COLUMN documents.document_type IS 'High-level document category, such as legal_opinion, policy_guideline, or user_manual.';
COMMENT ON COLUMN documents.storage_path IS 'Internal storage location for the original source file.';

