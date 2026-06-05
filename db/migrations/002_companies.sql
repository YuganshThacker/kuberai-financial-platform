create table companies (
  id           serial primary key,
  symbol       text unique not null,
  name         text not null,
  nse_listed   boolean default true,
  bse_code     text,
  sector       text,
  industry     text,
  created_at   timestamptz default now()
);

create index on companies (symbol);
