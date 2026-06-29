# KuberAI UAT Database — Data Inventory & Pipeline Wiring

Snapshot of everything in the UAT Supabase (`xqutgxdwmsvabwaioszq`) and how it
connects (or doesn't yet) to the response pipeline (`query/pipeline.py`).

## A. Document / RAG layer — CONNECTED ✅ (vector retrieval)

| Table | Rows | Used by |
|---|---|---|
| corporate_documents | 535k+ (growing) | `match_financial_chunks` / `match_annual_report_chunks` → retriever |
| official_transcripts | 181,535 | pre-existing transcript store (separate from corporate_documents) |
| transcript_insights | 5,305 | `get_insights_context` (guidance/capex/risks) |
| fundamentals_embeddings | 4,150 | **NOT yet** in retrieval — embedded fundamentals, candidate to merge |

## B. Structured financials — NOT CONNECTED ❌ (the quality opportunity)

The pipeline's structured hook (`sql_lookup.get_latest_metrics`) queries
`market_metrics`, which is **empty**. The real numbers live here, unused:

| Table | Rows | Key fields |
|---|---|---|
| td_ratios | 4,138 | pe_ttm, eps_ttm, book_value, dividend_yield, roe, roce, debt_equity, price_to_book, operating_profit_margin, net_profit_margin, mcap |
| fundamentals_history | 49,161 | revenue, net_profit, eps, roe, roce, market_cap, net_margin (multi-year) |
| td_pnl | 52,810 | revenue, operating_profit, pbt, pat, eps + segment detail (raw_json) |
| balance_sheet_history / td_balance_sheet | 22k / 11.8k | net_worth, borrowings, total_assets |
| td_cash_flow | 9,650 | operating/investing/financing cash flow |
| td_shareholding | 238,187 | promoter_pct, fii_pct, dii_pct (multi-quarter trend) |
| price_history | 5,638,730 | daily OHLCV — current price + returns |
| technical_indicators | 4,788,674 | EMA/RSI/MACD signals |
| index_valuations | 2,580 | per-symbol PE/PB/div-yield |
| corporate_actions | 91 | dividends, splits, bonuses |
| nse_sector_performance | 15 | sector aggregates |

## C. App / user layer (not retrieval-relevant)

users, kuber_dashboard_users, chat_threads (1,357), chat_messages (4,730),
api_usage_log (3,164), response_feedback (27), portfolio_history.

## Wiring plan

1. **Structured financial snapshot** (this change): replace the dead
   `market_metrics` lookup with `build_financial_context()` pulling td_ratios +
   fundamentals_history (3-yr trend) + price_history (latest) + td_shareholding
   (latest + trend) + corporate_actions (recent dividends). Injected as a
   high-priority context block so the LLM answers with exact numbers.
2. **Future:** merge `fundamentals_embeddings` into vector retrieval; add a
   technicals/price-return tool for "how has X performed" queries.
