create table search_logs (
  id          uuid primary key default gen_random_uuid(),
  query       text not null,
  symbols     text[],
  sources_hit text[],
  latency_ms  integer,
  created_at  timestamptz default now()
);
