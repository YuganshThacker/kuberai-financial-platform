-- ============================================================================
-- KuberAI RAG Layer → UAT  (PASTE #2 — REVISED for micro instance)
--
-- HNSW build exceeds the SQL Editor's ~2-min gateway timeout on a micro
-- instance. IVFFlat builds in seconds (k-means clustering) and is plenty
-- accurate at 47K rows once probes are tuned.
--
-- Run this whole block once. Safe to re-run.
-- ============================================================================

set maintenance_work_mem = '256MB';

-- IVFFlat index: lists≈100 suits ~50K rows. Builds in seconds.
create index if not exists corp_docs_embed_ivf_idx
  on corporate_documents
  using ivfflat (embedding vector_cosine_ops)
  with (lists = 100);

analyze corporate_documents;

-- ---------------------------------------------------------------------------
-- Retune retrieval functions for IVFFlat. probes controls recall:
--   probes=1 (default) under-fetches → set higher per call via plpgsql.
--   general retrieval: probes=10  (~95-98% recall, fast)
--   annual reports:    probes=40  (high recall on the filtered subset)
-- ---------------------------------------------------------------------------

create or replace function match_financial_chunks(
  query_embedding vector(1536),
  match_count     int,
  symbol_filter   text default null
)
returns table (
  chunk_text text,
  symbol     text,
  source     text,
  title      text,
  source_url text,
  similarity float
)
language plpgsql stable as $$
begin
  set local ivfflat.probes = 10;
  return query
    select
      cd.chunk_text,
      cd.symbol,
      cd.document_type as source,
      cd.title,
      cd.pdf_url       as source_url,
      1 - (cd.embedding <=> query_embedding) as similarity
    from corporate_documents cd
    where (symbol_filter is null or cd.symbol = symbol_filter)
    order by cd.embedding <=> query_embedding
    limit match_count;
end;
$$;

create or replace function match_annual_report_chunks(
  query_embedding vector(1536),
  match_count     int,
  symbol_filter   text default null
)
returns table (
  chunk_text text,
  symbol     text,
  source     text,
  title      text,
  source_url text,
  similarity float
)
language plpgsql volatile as $$
begin
  set local ivfflat.probes = 40;
  return query
    select
      cd.chunk_text,
      cd.symbol,
      cd.document_type as source,
      cd.title,
      cd.pdf_url       as source_url,
      1 - (cd.embedding <=> query_embedding) as similarity
    from corporate_documents cd
    where cd.document_type = 'annual_report'
      and (symbol_filter is null or cd.symbol = symbol_filter)
    order by cd.embedding <=> query_embedding
    limit match_count;
end;
$$;
