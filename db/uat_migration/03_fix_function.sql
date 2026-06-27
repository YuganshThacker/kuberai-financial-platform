-- ============================================================================
-- Fix: match_financial_chunks must be VOLATILE (not STABLE) because it uses
-- SET LOCAL ivfflat.probes. Postgres forbids SET inside non-volatile functions.
-- Paste & Run once.
-- ============================================================================

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
language plpgsql volatile as $$
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
