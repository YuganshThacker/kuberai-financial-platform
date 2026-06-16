-- ============================================================
-- KuberAI Financial Platform — Full Migration (001 → 010)
-- Supabase SQL Editor: paste entire script, click Run once
-- ============================================================


-- --- db/migrations/001_extensions.sql ---
create extension if not exists vector;


-- --- db/migrations/002_companies.sql ---
create table companies (
  id           serial primary key,
  symbol       text unique not null,
  name         text not null,
  nse_listed   boolean default true,
  bse_code     text,
  sector       text,
  industry     text,
  created_at   timestamptz default now()
);

create index on companies (symbol);


-- --- db/migrations/003_documents.sql ---
create table documents (
  id           uuid primary key default gen_random_uuid(),
  company_id   integer references companies(id),
  symbol       text not null,
  doc_type     text not null,
  title        text not null,
  source_url   text,
  s3_key       text,
  filing_date  date,
  fiscal_year  text,
  fiscal_quarter text,
  chunk_index  integer not null,
  chunk_text   text not null,
  embedding    vector(1536),
  created_at   timestamptz default now()
);

create index on documents (symbol);
create index on documents (doc_type);
create index on documents using ivfflat (embedding vector_cosine_ops) with (lists = 100);


-- --- db/migrations/004_news_articles.sql ---
create table news_articles (
  id           uuid primary key default gen_random_uuid(),
  title        text not null,
  url          text unique not null,
  source       text not null,
  published_at timestamptz,
  symbols      text[],
  chunk_index  integer not null,
  chunk_text   text not null,
  embedding    vector(1536),
  created_at   timestamptz default now()
);

create index on news_articles (published_at desc);
create index on news_articles using gin (symbols);
create index on news_articles using ivfflat (embedding vector_cosine_ops) with (lists = 100);


-- --- db/migrations/005_market_metrics.sql ---
create table market_metrics (
  id              serial primary key,
  symbol          text not null,
  as_of_date      date not null,
  price           numeric(12,2),
  day_high        numeric(12,2),
  day_low         numeric(12,2),
  week_52_high    numeric(12,2),
  week_52_low     numeric(12,2),
  volume          bigint,
  market_cap_cr   numeric(18,2),
  pe_ratio        numeric(10,2),
  pb_ratio        numeric(10,2),
  ev_ebitda       numeric(10,2),
  revenue_cr      numeric(18,2),
  pat_cr          numeric(18,2),
  eps             numeric(10,2),
  roe             numeric(8,2),
  roce            numeric(8,2),
  promoter_holding numeric(6,2),
  fii_holding      numeric(6,2),
  dii_holding      numeric(6,2),
  debt_to_equity  numeric(8,2),
  created_at      timestamptz default now(),
  unique (symbol, as_of_date)
);

create index on market_metrics (symbol, as_of_date desc);


-- --- db/migrations/006_transcripts.sql ---
create table transcripts (
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

create index on transcripts (symbol);
create index on transcripts using ivfflat (embedding vector_cosine_ops) with (lists = 100);


-- --- db/migrations/007_search_logs.sql ---
create table search_logs (
  id          uuid primary key default gen_random_uuid(),
  query       text not null,
  symbols     text[],
  sources_hit text[],
  latency_ms  integer,
  created_at  timestamptz default now()
);


-- --- db/migrations/008_match_function.sql ---
create or replace function match_financial_chunks(
  query_embedding vector(1536),
  match_count int,
  symbol_filter text default null
)
returns table (
  chunk_text text,
  symbol text,
  source text,
  title text,
  source_url text,
  similarity float
)
language sql stable as $$
  (
    select chunk_text, symbol, 'documents' as source, title, source_url,
           1 - (embedding <=> query_embedding) as similarity
    from documents
    where (symbol_filter is null or symbol = symbol_filter)
    order by embedding <=> query_embedding
    limit match_count / 2
  )
  union all
  (
    select chunk_text, array_to_string(symbols, ',') as symbol,
           'news_articles' as source, title, url as source_url,
           1 - (embedding <=> query_embedding) as similarity
    from news_articles
    where (symbol_filter is null or symbol_filter = any(symbols))
    order by embedding <=> query_embedding
    limit match_count / 2
  )
  order by similarity desc
  limit match_count;
$$;


-- --- db/migrations/009_web_search_results.sql ---
create table if not exists web_search_results (
  id             uuid primary key default gen_random_uuid(),
  symbol         text not null,
  source_domain  text,
  url            text not null,
  title          text,
  chunk_index    int  not null default 0,
  chunk_text     text not null,
  embedding      vector(1536),
  published_at   timestamptz,
  fetched_at     timestamptz default now()
);

-- dedup: same article can be re-fetched daily; upsert on (url, chunk_index)
create unique index if not exists web_search_results_url_chunk_idx
  on web_search_results(url, chunk_index);

create index if not exists web_search_results_symbol_idx
  on web_search_results(symbol);

-- ivfflat cosine index — 100 lists suits up to ~1M rows (50 stocks × 12 articles × 30 chunks × 60 days)
create index if not exists web_search_results_embedding_idx
  on web_search_results using ivfflat (embedding vector_cosine_ops)
  with (lists = 100);


-- --- db/migrations/010_update_match_function.sql ---
-- Extends match_financial_chunks to also search web_search_results (Google News articles).
-- Each source gets match_count / 3 slots so web articles don't crowd out filings.
create or replace function match_financial_chunks(
  query_embedding vector(1536),
  match_count     int,
  symbol_filter   text default null
)
returns table (
  chunk_text  text,
  symbol      text,
  source      text,
  title       text,
  source_url  text,
  similarity  float
)
language sql stable as $$
  (
    select chunk_text, symbol, 'documents' as source, title, source_url,
           1 - (embedding <=> query_embedding) as similarity
    from documents
    where (symbol_filter is null or symbol = symbol_filter)
    order by embedding <=> query_embedding
    limit match_count / 3
  )
  union all
  (
    select chunk_text, array_to_string(symbols, ',') as symbol,
           'news_articles' as source, title, url as source_url,
           1 - (embedding <=> query_embedding) as similarity
    from news_articles
    where (symbol_filter is null or symbol_filter = any(symbols))
    order by embedding <=> query_embedding
    limit match_count / 3
  )
  union all
  (
    select chunk_text, symbol, 'web_search' as source, title, url as source_url,
           1 - (embedding <=> query_embedding) as similarity
    from web_search_results
    where (symbol_filter is null or symbol = symbol_filter)
    order by embedding <=> query_embedding
    limit match_count / 3
  )
  order by similarity desc
  limit match_count;
$$;

