-- Central table for official NSE filings: investor presentations, quarterly results,
-- annual reports, and press releases. Transcripts have their own table (013) because
-- they drive structured insight extraction.
--
-- filing_type values: 'investor_presentation', 'quarterly_results', 'annual_report',
--                     'press_release'

create table official_filings (
  id           uuid primary key default gen_random_uuid(),
  symbol       text not null,
  filing_type  text not null,
  quarter      text,            -- e.g. 'Q4FY26' (inferred from filing date)
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

create index on official_filings (symbol);
create index on official_filings (filing_type);
create index on official_filings (symbol, filing_type);
create index on official_filings (filing_date desc);
create index on official_filings using ivfflat (embedding vector_cosine_ops) with (lists = 100);
