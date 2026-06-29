from dataclasses import dataclass
from typing import Optional
from supabase import Client

@dataclass
class MetricSnapshot:
    symbol: str
    as_of_date: str
    price: Optional[float] = None
    day_high: Optional[float] = None
    day_low: Optional[float] = None
    week_52_high: Optional[float] = None
    week_52_low: Optional[float] = None
    market_cap_cr: Optional[float] = None
    pe_ratio: Optional[float] = None
    pb_ratio: Optional[float] = None
    roe: Optional[float] = None
    roce: Optional[float] = None
    debt_to_equity: Optional[float] = None
    promoter_holding: Optional[float] = None
    fii_holding: Optional[float] = None

def get_latest_metrics(client: Client, symbol: str) -> Optional[MetricSnapshot]:
    resp = (
        client.table("market_metrics")
        .select("*")
        .eq("symbol", symbol)
        .order("as_of_date", desc=True)
        .limit(1)
        .execute()
    )
    if not resp.data:
        return None
    row = resp.data[0]
    return MetricSnapshot(
        symbol=row["symbol"],
        as_of_date=row["as_of_date"],
        price=row.get("price"),
        day_high=row.get("day_high"),
        day_low=row.get("day_low"),
        week_52_high=row.get("week_52_high"),
        week_52_low=row.get("week_52_low"),
        market_cap_cr=row.get("market_cap_cr"),
        pe_ratio=row.get("pe_ratio"),
        pb_ratio=row.get("pb_ratio"),
        roe=row.get("roe"),
        roce=row.get("roce"),
        debt_to_equity=row.get("debt_to_equity"),
        promoter_holding=row.get("promoter_holding"),
        fii_holding=row.get("fii_holding"),
    )

def format_metrics_as_context(m: MetricSnapshot) -> str:
    lines = [f"## {m.symbol} — Market Metrics (as of {m.as_of_date})"]
    if m.price:        lines.append(f"- Current Price: ₹{m.price:,.2f}")
    if m.week_52_high: lines.append(f"- 52W High: ₹{m.week_52_high:,.2f}")
    if m.week_52_low:  lines.append(f"- 52W Low: ₹{m.week_52_low:,.2f}")
    if m.market_cap_cr: lines.append(f"- Market Cap: ₹{m.market_cap_cr:,.0f} Cr")
    if m.pe_ratio:     lines.append(f"- P/E: {m.pe_ratio}")
    if m.pb_ratio:     lines.append(f"- P/B: {m.pb_ratio}")
    if m.roe:          lines.append(f"- ROE: {m.roe}%")
    if m.roce:         lines.append(f"- ROCE: {m.roce}%")
    if m.debt_to_equity is not None: lines.append(f"- Debt/Equity: {m.debt_to_equity}")
    if m.promoter_holding: lines.append(f"- Promoter Holding: {m.promoter_holding}%")
    return "\n".join(lines)


# ── Rich structured financial snapshot ───────────────────────────────────────
# Assembles a high-signal quantitative context block from the populated
# financial tables (td_ratios, fundamentals_history, price_history,
# td_shareholding, corporate_actions). This is the structured counterpart to the
# qualitative document RAG — it gives the LLM exact numbers to cite.

def _one(client: Client, table: str, symbol: str, order: str | None = None,
         desc: bool = True, limit: int = 1, extra: dict | None = None):
    try:
        q = client.table(table).select("*").eq("symbol", symbol)
        if extra:
            for k, v in extra.items():
                q = q.eq(k, v)
        if order:
            q = q.order(order, desc=desc)
        rows = q.limit(limit).execute().data or []
        return rows if limit > 1 else (rows[0] if rows else None)
    except Exception:
        return [] if limit > 1 else None


def _pct_change(curr, prev):
    try:
        if curr is None or prev in (None, 0):
            return None
        return (curr - prev) / abs(prev) * 100
    except Exception:
        return None


def build_financial_context(client: Client, symbol: str) -> Optional[str]:
    """Comprehensive structured-financials context block for *symbol*.

    Pulls valuation/ratios, multi-year fundamentals trend, latest price,
    shareholding (with QoQ trend), and recent dividends. Returns None if no
    structured data exists for the symbol.
    """
    out: list[str] = []

    # 1. Valuation & profitability ratios (latest)
    r = _one(client, "td_ratios", symbol, order="data_date")
    if r:
        v = [f"## {symbol} — Valuation & Ratios (as of {r.get('data_date','')})"]
        mcap = r.get("mcap")
        if mcap:               v.append(f"- Market Cap: ₹{mcap/1e7:,.0f} Cr")
        if r.get("pe_ttm") is not None:    v.append(f"- P/E (TTM): {r['pe_ttm']}")
        if r.get("price_to_book") is not None: v.append(f"- P/B: {r['price_to_book']}")
        if r.get("eps_ttm") is not None:   v.append(f"- EPS (TTM): ₹{r['eps_ttm']}")
        if r.get("book_value") is not None: v.append(f"- Book Value: ₹{r['book_value']}")
        if r.get("roe") is not None:       v.append(f"- ROE: {r['roe']}%")
        if r.get("roce") is not None:      v.append(f"- ROCE: {r['roce']}%")
        if r.get("operating_profit_margin") is not None: v.append(f"- Operating Margin: {r['operating_profit_margin']}%")
        if r.get("net_profit_margin") is not None: v.append(f"- Net Margin: {r['net_profit_margin']}%")
        if r.get("debt_equity") is not None: v.append(f"- Debt/Equity: {r['debt_equity']}")
        if r.get("dividend_yield") is not None: v.append(f"- Dividend Yield: {r['dividend_yield']}%")
        out.append("\n".join(v))

    # 2. Multi-year fundamentals trend (revenue / profit / eps)
    hist = _one(client, "fundamentals_history", symbol, order="fiscal_year", limit=4)
    if hist:
        hist = sorted(hist, key=lambda x: x.get("fiscal_year", 0))
        v = [f"## {symbol} — Financial Trend (₹ Cr)"]
        for i, h in enumerate(hist):
            fy = h.get("fiscal_year")
            rev, npf, eps = h.get("revenue"), h.get("net_profit"), h.get("eps")
            growth = ""
            if i > 0:
                g = _pct_change(rev, hist[i - 1].get("revenue"))
                if g is not None:
                    growth = f" (rev {'+' if g>=0 else ''}{g:.1f}% YoY)"
            parts = [f"FY{fy}:"]
            if rev is not None: parts.append(f"Revenue ₹{rev:,.0f} Cr")
            if npf is not None: parts.append(f"Net Profit ₹{npf:,.0f} Cr")
            if eps is not None: parts.append(f"EPS ₹{eps}")
            v.append(f"- {' | '.join(parts)}{growth}")
        out.append("\n".join(v))

    # 3. Latest price
    p = _one(client, "price_history", symbol, order="as_of_date")
    if p and p.get("close"):
        out.append(f"## {symbol} — Latest Price (as of {p.get('as_of_date','')})\n"
                   f"- Close: ₹{p['close']:,.2f}"
                   + (f" | Volume: {p['volume']:,}" if p.get("volume") else ""))

    # 4. Shareholding pattern (latest + QoQ trend)
    sh = _one(client, "td_shareholding", symbol, order="report_date", limit=2)
    if sh:
        latest = sh[0]
        v = [f"## {symbol} — Shareholding (as of {latest.get('report_date','')})"]
        def _trend(key):
            if len(sh) > 1:
                d = _pct_change_abs(latest.get(key), sh[1].get(key))
                return d
            return None
        for label, key in [("Promoter", "promoter_pct"), ("FII", "fii_pct"),
                           ("DII", "dii_pct"), ("Public", "non_institutions_pct")]:
            val = latest.get(key)
            if val is not None:
                delta = None
                if len(sh) > 1 and sh[1].get(key) is not None:
                    delta = val - sh[1][key]
                trend = f" ({'+' if delta and delta>=0 else ''}{delta:.2f} QoQ)" if delta else ""
                v.append(f"- {label}: {val}%{trend}")
        out.append("\n".join(v))

    # 5. Recent corporate actions (dividends)
    acts = _one(client, "corporate_actions", symbol, order="ex_date", limit=3)
    if acts:
        v = [f"## {symbol} — Recent Corporate Actions"]
        for a in acts:
            amt = f"₹{a['dividend_amount']}/sh" if a.get("dividend_amount") else ""
            v.append(f"- {a.get('ex_date','')}: {a.get('action_type','')} {a.get('dividend_type','') or ''} {amt}".rstrip())
        out.append("\n".join(v))

    return "\n\n".join(out) if out else None


def _pct_change_abs(curr, prev):
    try:
        return curr - prev
    except Exception:
        return None
