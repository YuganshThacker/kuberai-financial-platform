-- Migration 011: add unique constraints required for idempotent upserts.
--
-- news_articles: url was unique alone, but we store multiple chunks per URL.
--   Drop the single-column unique and add (url, chunk_index) composite unique.
-- documents: add (source_url, chunk_index) unique for PDF-sourced filings.
-- transcripts: add (symbol, title, chunk_index) unique for concall PDFs.

-- news_articles ---------------------------------------------------------------

-- Drop the old single-column unique (url) which blocks multi-chunk storage.
alter table news_articles drop constraint if exists news_articles_url_key;
-- url still needs an index for fast lookups — keep the btree index.
create index if not exists news_articles_url_idx on news_articles (url);
-- Composite unique enables idempotent upsert(on_conflict="url,chunk_index").
alter table news_articles
  add constraint news_articles_url_chunk_key unique (url, chunk_index);

-- documents -------------------------------------------------------------------

-- Allows idempotent upsert for NSE filing PDFs via (source_url, chunk_index).
-- source_url may be NULL for manually imported docs; NULL rows skip on_conflict
-- (Postgres treats NULLs as distinct in unique indexes — acceptable for now).
alter table documents
  add constraint documents_source_url_chunk_key unique (source_url, chunk_index);

-- transcripts -----------------------------------------------------------------

-- Allows idempotent upsert via (symbol, title, chunk_index).
-- Title contains date+type (e.g. "TCS - Earnings Call Transcript (2026-04-14)")
-- so collisions only occur on genuine re-ingestion of the same PDF.
alter table transcripts
  add constraint transcripts_symbol_title_chunk_key unique (symbol, title, chunk_index);
