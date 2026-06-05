create table market_metrics (
  id              serial primary key,
  symbol          text not null,
  as_of_date      date not null,
  price           numeric(12,2),
  day_high        numeric(12,2),
  day_low         numeric(12,2),
  week_52_high    numeric(12,2),
  week_52_low     numeric(12,2),
  volume          bigint,
  market_cap_cr   numeric(18,2),
  pe_ratio        numeric(10,2),
  pb_ratio        numeric(10,2),
  ev_ebitda       numeric(10,2),
  revenue_cr      numeric(18,2),
  pat_cr          numeric(18,2),
  eps             numeric(10,2),
  roe             numeric(8,2),
  roce            numeric(8,2),
  promoter_holding numeric(6,2),
  fii_holding      numeric(6,2),
  dii_holding      numeric(6,2),
  debt_to_equity  numeric(8,2),
  created_at      timestamptz default now(),
  unique (symbol, as_of_date)
);

create index on market_metrics (symbol, as_of_date desc);
