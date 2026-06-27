-- ============================================================================
-- KuberAI RAG Layer → UAT Migration  (PASTE #1 of 2)
-- Target: KuberAI-UAT project (xqutgxdwmsvabwaioszq)
--
-- Additive only. No DROP, no --clean. Verified zero table-name collisions
-- with the existing UAT dashboard schema (fundamentals/chat/etc.).
--
-- The heavy HNSW vector index on corporate_documents is intentionally NOT
-- created here — it is built in PASTE #2 after the 47K rows are streamed in,
-- so the bulk load stays fast. The match functions still work before the
-- index exists (sequential scan), just slower.
-- ============================================================================

create extension if not exists vector;

-- ---------------------------------------------------------------------------
-- 1. corporate_documents — the unified RAG store (all 5 document types)
--    transcript | annual_report | investor_presentation | quarterly_results | announcement
-- ---------------------------------------------------------------------------
create table if not exists corporate_documents (
  id               uuid primary key default gen_random_uuid(),
  symbol           text not null,
  document_type    text not null,
  quarter          text,
  fiscal_year      text,
  filing_date      date,
  title            text not null,
  pdf_url          text not null,
  discovery_source text,
  retrieval_method text,
  chunk_index      integer not null,
  chunk_text       text not null,
  embedding        vector(1536),
  quality_score    double precision,
  content_hash     text,
  ingested_at      timestamptz default now(),
  section_type     text,
  unique (pdf_url, chunk_index)
);
create index if not exists corp_docs_symbol_idx     on corporate_documents (symbol);
create index if not exists corp_docs_type_idx       on corporate_documents (document_type);
create index if not exists corp_docs_sym_type_idx   on corporate_documents (symbol, document_type);
create index if not exists corp_docs_fy_idx         on corporate_documents (fiscal_year desc);
-- NOTE: HNSW embedding index is created in PASTE #2 (after data load).

-- ---------------------------------------------------------------------------
-- 2. transcript_insights — structured LLM-extracted intelligence (no embeddings)
-- ---------------------------------------------------------------------------
create table if not exists transcript_insights (
  id                    uuid primary key default gen_random_uuid(),
  symbol                text not null,
  quarter               text,
  fiscal_year           text,
  filing_date           date,
  pdf_url               text unique not null,
  management_commentary text,
  guidance              text,
  capex                 text,
  demand_outlook        text,
  margins               text,
  risks                 text,
  qa_highlights         text,
  extracted_at          timestamptz default now()
);
create index if not exists ti_symbol_idx  on transcript_insights (symbol);
create index if not exists ti_sym_qtr_idx on transcript_insights (symbol, quarter);

-- ---------------------------------------------------------------------------
-- 3. official_transcripts — VIEW over corporate_documents (platform compat)
-- ---------------------------------------------------------------------------
create or replace view official_transcripts as
  select id, symbol, quarter, fiscal_year, filing_date, pdf_url, title,
         chunk_index, chunk_text, embedding, ingested_at as created_at
  from corporate_documents
  where document_type = 'transcript';

-- ---------------------------------------------------------------------------
-- 4. Ingestion state / auxiliary tables
-- ---------------------------------------------------------------------------
create table if not exists symbols (
  symbol       text primary key,
  company_name text,
  isin         text,
  universe     text[],
  sector       text,
  active       boolean default true,
  added_at     timestamptz default now()
);

create table if not exists discovery_state (
  source           text not null,
  symbol           text not null,
  last_run_at      timestamptz,
  last_filing_date text,
  status           text,
  error_message    text,
  run_count        integer default 0,
  primary key (source, symbol)
);

create table if not exists ingestion_runs (
  id                   uuid primary key default gen_random_uuid(),
  run_type             text not null,
  symbols_processed    integer default 0,
  pdfs_processed       integer default 0,
  chunks_created       integer default 0,
  embeddings_generated integer default 0,
  errors               integer default 0,
  cost_usd_estimate    numeric(10,6),
  started_at           timestamptz default now(),
  completed_at         timestamptz,
  duration_seconds     integer,
  metadata             jsonb
);

create table if not exists ir_pages (
  symbol                 text primary key,
  ir_page_url            text,
  scrape_method          text,
  last_successful_scrape timestamptz,
  consecutive_failures   integer default 0,
  updated_at             timestamptz default now()
);

create table if not exists failed_documents (
  id            uuid primary key default gen_random_uuid(),
  symbol        text,
  pdf_url       text,
  company_url   text,
  reason        text,
  text_length   integer,
  chunk_count   integer,
  notes         text,
  created_at    timestamptz default now(),
  document_type text,
  retry_count   integer default 0,
  retry_after   timestamptz,
  unrecoverable boolean default false,
  quarter       text
);

-- document_coverage: snapshot of the prod coverage aggregate (loaded as a table)
create table if not exists document_coverage (
  symbol          text,
  universe        text[],
  document_type   text,
  quarter         text,
  fiscal_year     text,
  status          text,
  best_quality    double precision,
  first_ingested  timestamptz,
  doc_count       bigint,
  failure_reasons text,
  max_retry_count integer
);

-- official_transcripts_backup: redundant historical backup (kept for completeness)
create table if not exists official_transcripts_backup (
  id          uuid primary key default gen_random_uuid(),
  symbol      text,
  quarter     text,
  fiscal_year text,
  filing_date date,
  pdf_url     text,
  title       text,
  chunk_index integer,
  chunk_text  text,
  embedding   vector(1536),
  created_at  timestamptz default now()
);

-- ---------------------------------------------------------------------------
-- 5. Legacy / currently-empty base tables (schema only, for platform compat)
-- ---------------------------------------------------------------------------
create table if not exists companies (
  id         serial primary key,
  symbol     text unique not null,
  name       text not null,
  nse_listed boolean default true,
  bse_code   text,
  sector     text,
  industry   text,
  created_at timestamptz default now()
);

create table if not exists documents (
  id             uuid primary key default gen_random_uuid(),
  company_id     integer references companies(id),
  symbol         text not null,
  doc_type       text not null,
  title          text not null,
  source_url     text,
  s3_key         text,
  filing_date    date,
  fiscal_year    text,
  fiscal_quarter text,
  chunk_index    integer not null,
  chunk_text     text not null,
  embedding      vector(1536),
  created_at     timestamptz default now()
);

create table if not exists news_articles (
  id           uuid primary key default gen_random_uuid(),
  title        text not null,
  url          text not null,
  source       text not null,
  published_at timestamptz,
  symbols      text[],
  chunk_index  integer not null,
  chunk_text   text not null,
  embedding    vector(1536),
  created_at   timestamptz default now(),
  unique (url, chunk_index)
);

create table if not exists market_metrics (
  id               serial primary key,
  symbol           text not null,
  as_of_date       date not null,
  price            numeric(12,2),
  day_high         numeric(12,2),
  day_low          numeric(12,2),
  week_52_high     numeric(12,2),
  week_52_low      numeric(12,2),
  volume           bigint,
  market_cap_cr    numeric(18,2),
  pe_ratio         numeric(10,2),
  pb_ratio         numeric(10,2),
  ev_ebitda        numeric(10,2),
  revenue_cr       numeric(18,2),
  pat_cr           numeric(18,2),
  eps              numeric(10,2),
  roe              numeric(8,2),
  roce             numeric(8,2),
  promoter_holding numeric(6,2),
  fii_holding      numeric(6,2),
  dii_holding      numeric(6,2),
  debt_to_equity   numeric(8,2),
  created_at       timestamptz default now(),
  unique (symbol, as_of_date)
);

create table if not exists transcripts (
  id             uuid primary key default gen_random_uuid(),
  symbol         text not null,
  source_type    text not null,
  video_id       text,
  title          text not null,
  channel        text,
  published_at   timestamptz,
  fiscal_quarter text,
  fiscal_year    text,
  chunk_index    integer not null,
  chunk_text     text not null,
  speaker_label  text,
  embedding      vector(1536),
  created_at     timestamptz default now()
);

create table if not exists search_logs (
  id          uuid primary key default gen_random_uuid(),
  query       text not null,
  symbols     text[],
  sources_hit text[],
  latency_ms  integer,
  created_at  timestamptz default now()
);

create table if not exists web_search_results (
  id            uuid primary key default gen_random_uuid(),
  symbol        text not null,
  source_domain text,
  url           text not null,
  title         text,
  chunk_index   int not null default 0,
  chunk_text    text not null,
  embedding     vector(1536),
  published_at  timestamptz,
  fetched_at    timestamptz default now(),
  unique (url, chunk_index)
);

-- ---------------------------------------------------------------------------
-- 6. RAG retrieval functions
-- ---------------------------------------------------------------------------

-- Primary retrieval: all document types from corporate_documents.
-- Returns match_count candidates; the Python reranker selects final top_k.
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
language sql stable as $$
  select
    chunk_text,
    symbol,
    document_type as source,
    title,
    pdf_url       as source_url,
    1 - (embedding <=> query_embedding) as similarity
  from corporate_documents
  where (symbol_filter is null or symbol = symbol_filter)
  order by embedding <=> query_embedding
  limit match_count;
$$;

-- Annual-report retrieval with boosted recall (ef_search=300) to avoid HNSW
-- candidate starvation when filtering by document_type + symbol.
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
  set local hnsw.ef_search = 300;
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

-- Done. After streaming completes, run 02_build_index.sql (PASTE #2).
