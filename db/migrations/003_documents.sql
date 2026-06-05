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
