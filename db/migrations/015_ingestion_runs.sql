-- Cost dashboard and monitoring for all ingestion Lambda runs.
-- Written at the end of each run to track PDFs processed, embeddings generated,
-- estimated cost, and error rates. Used for cost/company/day breakdowns.

create table ingestion_runs (
  id                   uuid primary key default gen_random_uuid(),
  run_type             text not null,        -- 'transcripts', 'presentations', 'annual_reports', 'quarterly_results', 'web_search', 'news'
  symbols_processed    integer default 0,
  pdfs_processed       integer default 0,
  chunks_created       integer default 0,
  embeddings_generated integer default 0,
  errors               integer default 0,
  cost_usd_estimate    numeric(10, 6),       -- based on token counts × current pricing
  started_at           timestamptz default now(),
  completed_at         timestamptz,
  duration_seconds     integer,              -- completed_at - started_at
  metadata             jsonb                 -- arbitrary run-specific details
);

create index on ingestion_runs (run_type);
create index on ingestion_runs (started_at desc);
