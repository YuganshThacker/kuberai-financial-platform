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
