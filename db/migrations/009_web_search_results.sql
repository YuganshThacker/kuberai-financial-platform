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
