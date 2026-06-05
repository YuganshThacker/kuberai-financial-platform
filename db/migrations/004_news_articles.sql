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
