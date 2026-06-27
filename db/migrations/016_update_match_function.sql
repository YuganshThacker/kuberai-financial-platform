-- Extended match_financial_chunks to include official_transcripts and official_filings.
--
-- Priority order (highest → lowest quality signal):
--   1. official_transcripts — direct earnings call text (highest alpha)
--   2. official_filings     — investor presentations, annual reports, quarterly results
--   3. documents            — legacy filing store
--   4. news_articles        — published news
--   5. web_search_results   — scraped financial pages
--
-- The function returns match_count * 4 candidates. The Python reranker
-- (query/reranker.py) selects the final top_k using Cohere or vector scores.
-- Fixed the previous hardcoded match_count/3 split that siloed sources.

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
  -- 1. Official transcripts: earnings calls → highest quality, full budget
  (
    select chunk_text, symbol,
           'official_transcript' as source,
           title, pdf_url as source_url,
           1 - (embedding <=> query_embedding) as similarity
    from official_transcripts
    where (symbol_filter is null or symbol = symbol_filter)
    order by embedding <=> query_embedding
    limit match_count
  )
  union all
  -- 2. Official filings: presentations, annual reports, quarterly results
  (
    select chunk_text, symbol,
           filing_type as source,
           title, pdf_url as source_url,
           1 - (embedding <=> query_embedding) as similarity
    from official_filings
    where (symbol_filter is null or symbol = symbol_filter)
    order by embedding <=> query_embedding
    limit match_count
  )
  union all
  -- 3. Documents (legacy filing store)
  (
    select chunk_text, symbol,
           'documents' as source,
           title, source_url,
           1 - (embedding <=> query_embedding) as similarity
    from documents
    where (symbol_filter is null or symbol = symbol_filter)
    order by embedding <=> query_embedding
    limit match_count / 2
  )
  union all
  -- 4. News articles
  (
    select chunk_text,
           array_to_string(symbols, ',') as symbol,
           'news_articles' as source,
           title, url as source_url,
           1 - (embedding <=> query_embedding) as similarity
    from news_articles
    where (symbol_filter is null or symbol_filter = any(symbols))
    order by embedding <=> query_embedding
    limit match_count / 2
  )
  union all
  -- 5. Web search results (financial pages, Screener, AlphaSpread, etc.)
  (
    select chunk_text, symbol,
           'web_search' as source,
           title, url as source_url,
           1 - (embedding <=> query_embedding) as similarity
    from web_search_results
    where (symbol_filter is null or symbol = symbol_filter)
    order by embedding <=> query_embedding
    limit match_count / 2
  )
  order by similarity desc
  -- Over-fetch for Python reranker; retriever calls with match_count = top_k * 4
  limit match_count;
$$;
