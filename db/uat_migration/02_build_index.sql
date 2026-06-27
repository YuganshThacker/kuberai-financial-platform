-- ============================================================================
-- KuberAI RAG Layer → UAT Migration  (PASTE #2 of 2)
-- Run ONLY after the data streaming step reports complete.
--
-- Builds the HNSW vector index on corporate_documents in one shot (faster and
-- gentler than maintaining it during the 47K-row bulk insert). Matches prod's
-- HNSW config used with ef_search tuning.
-- ============================================================================

create index if not exists corp_docs_embed_hnsw_idx
  on corporate_documents
  using hnsw (embedding vector_cosine_ops)
  with (m = 16, ef_construction = 64);

-- Optional: refresh planner stats after bulk load
analyze corporate_documents;
