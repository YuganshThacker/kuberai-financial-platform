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
