-- Extends match_financial_chunks to also search web_search_results (Google News articles).
-- Each source gets match_count / 3 slots so web articles don't crowd out filings.
create or replace function match_financial_chunks(
  query_embedding vector(1536),
  match_count     int,
  symbol_filter   text default null
)
returns table (
  chunk_text  text,
  symbol      text,
  source      text,
  title       text,
  source_url  text,
  similarity  float
)
language sql stable as $$
  (
    select chunk_text, symbol, 'documents' as source, title, source_url,
           1 - (embedding <=> query_embedding) as similarity
    from documents
    where (symbol_filter is null or symbol = symbol_filter)
    order by embedding <=> query_embedding
    limit match_count / 3
  )
  union all
  (
    select chunk_text, array_to_string(symbols, ',') as symbol,
           'news_articles' as source, title, url as source_url,
           1 - (embedding <=> query_embedding) as similarity
    from news_articles
    where (symbol_filter is null or symbol_filter = any(symbols))
    order by embedding <=> query_embedding
    limit match_count / 3
  )
  union all
  (
    select chunk_text, symbol, 'web_search' as source, title, url as source_url,
           1 - (embedding <=> query_embedding) as similarity
    from web_search_results
    where (symbol_filter is null or symbol = symbol_filter)
    order by embedding <=> query_embedding
    limit match_count / 3
  )
  order by similarity desc
  limit match_count;
$$;
