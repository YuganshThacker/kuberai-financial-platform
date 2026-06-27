-- Structured intelligence extracted from earnings call transcripts via LLM.
-- One row per transcript (not per chunk).
--
-- This is the "alpha source" — structured guidance/capex/risk data that no
-- generic RAG pipeline produces. Enables queries like:
--   "What is TCS's FY27 guidance?" → direct answer from structured field
--   "Show me capex trends for RELIANCE over last 4 quarters"

create table transcript_insights (
  id                    uuid primary key default gen_random_uuid(),
  symbol                text not null,
  quarter               text,            -- e.g. 'Q4FY26'
  fiscal_year           text,            -- e.g. '2026'
  filing_date           date,
  pdf_url               text unique not null,
  management_commentary text,            -- key strategic statements from management
  guidance              text,            -- revenue/growth/margin guidance
  capex                 text,            -- capital expenditure plans
  demand_outlook        text,            -- demand environment assessment
  margins               text,            -- margin trends and drivers
  risks                 text,            -- key risks mentioned
  qa_highlights         text,            -- notable analyst Q&A exchanges
  extracted_at          timestamptz default now()
);

create index on transcript_insights (symbol);
create index on transcript_insights (symbol, quarter);
create index on transcript_insights (fiscal_year desc, quarter);
