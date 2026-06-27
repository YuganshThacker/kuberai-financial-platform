-- Dedicated table for NSE earnings call transcripts — separate from official_filings
-- because transcripts drive structured insight extraction (guidance, capex, risks)
-- and are queried at much higher priority than other filings.
--
-- One row per chunk; one PDF typically produces 100-200 chunks (400-word chunks).
-- Insights extracted from each transcript are stored in transcript_insights (014).

create table official_transcripts (
  id           uuid primary key default gen_random_uuid(),
  symbol       text not null,
  quarter      text,            -- e.g. 'Q4FY26'
  fiscal_year  text,            -- e.g. '2026'
  filing_date  date,
  pdf_url      text not null,
  title        text not null,
  chunk_index  integer not null,
  chunk_text   text not null,
  embedding    vector(1536),
  created_at   timestamptz default now(),
  unique(pdf_url, chunk_index)
);

create index on official_transcripts (symbol);
create index on official_transcripts (symbol, quarter);
create index on official_transcripts (fiscal_year, quarter);
create index on official_transcripts using ivfflat (embedding vector_cosine_ops) with (lists = 100);
