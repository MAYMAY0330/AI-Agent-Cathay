-- 004_create_ingestion_logs.sql
-- Records document import attempts and their processing status.

CREATE TABLE IF NOT EXISTS ingestion_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id TEXT,
    document_id UUID REFERENCES documents(id),
    version_id UUID REFERENCES document_versions(id),
    source_system TEXT,
    source_url TEXT,
    storage_path TEXT,
    file_name TEXT,
    file_type TEXT,
    file_checksum TEXT,
    status TEXT NOT NULL,
    stage TEXT,
    total_chunks INTEGER DEFAULT 0,
    summary_generated BOOLEAN DEFAULT FALSE,
    error_message TEXT,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP
);

COMMENT ON TABLE ingestion_logs IS 'Operational log for document import attempts.';
COMMENT ON COLUMN ingestion_logs.status IS 'Import result, such as pending, running, succeeded, failed, or skipped.';
COMMENT ON COLUMN ingestion_logs.stage IS 'Last known processing stage for troubleshooting import failures.';

