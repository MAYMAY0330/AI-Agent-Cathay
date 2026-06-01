-- 006_add_pgvector_chunk_embeddings.sql
-- Adds vector embedding storage for document chunk semantic retrieval.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS chunk_embeddings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chunk_id UUID NOT NULL REFERENCES document_chunks(id) ON DELETE CASCADE,
    embedding_model TEXT NOT NULL,
    embedding_dimension INTEGER NOT NULL DEFAULT 1536,
    embedding vector(1536) NOT NULL,
    content_checksum TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chunk_embeddings_dimension_check
        CHECK (embedding_dimension = 1536),
    CONSTRAINT chunk_embeddings_chunk_model_unique
        UNIQUE (chunk_id, embedding_model)
);

CREATE INDEX IF NOT EXISTS idx_chunk_embeddings_chunk_id
    ON chunk_embeddings (chunk_id);

CREATE INDEX IF NOT EXISTS idx_chunk_embeddings_model
    ON chunk_embeddings (embedding_model);

CREATE INDEX IF NOT EXISTS idx_chunk_embeddings_vector_hnsw
    ON chunk_embeddings
    USING hnsw (embedding vector_cosine_ops);

COMMENT ON TABLE chunk_embeddings IS 'Vector embeddings for document chunks used by semantic retrieval.';
COMMENT ON COLUMN chunk_embeddings.chunk_id IS 'Source document chunk represented by this embedding.';
COMMENT ON COLUMN chunk_embeddings.embedding_model IS 'Embedding model name, used for re-embedding and retrieval compatibility.';
COMMENT ON COLUMN chunk_embeddings.embedding_dimension IS 'Embedding vector dimension. The initial RAG layer expects 1536 dimensions.';
COMMENT ON COLUMN chunk_embeddings.content_checksum IS 'Optional checksum of the source chunk text at embedding time.';
