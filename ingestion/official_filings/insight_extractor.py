"""
Structured intelligence extraction from earnings call transcripts.

For each transcript, extracts 7 structured fields using GPT-4o-mini:
  - management_commentary: key strategic statements
  - guidance: revenue/volume/margin guidance with specific numbers
  - capex: capital expenditure plans and amounts
  - demand_outlook: sector/macro demand environment
  - margins: margin trends, drivers, and expectations
  - risks: key risks flagged by management
  - qa_highlights: notable analyst questions and management answers

Results are stored in transcript_insights (one row per transcript PDF).
This enables direct structured queries: "What is TCS's FY27 revenue guidance?"
without going through chunked RAG.

Cost: ~1500 tokens per transcript × $0.60/1M (gpt-4o-mini input) = $0.0009/transcript
For 500 stocks × 8 quarters = $3.60 total — trivial.
"""

from __future__ import annotations

import json
import os

from openai import OpenAI
from supabase import Client

_client: OpenAI | None = None


def _get_openai() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))
    return _client


_SYSTEM_PROMPT = """\
You are a financial analyst extracting structured intelligence from an Indian company
earnings call transcript. Extract only what is explicitly stated — do not infer or
hallucinate. If a field is not mentioned, return null.

Respond with a valid JSON object with exactly these keys:
  management_commentary: string | null  (key strategic statements, 2-4 sentences)
  guidance: string | null               (explicit revenue/volume/margin guidance with numbers)
  capex: string | null                  (capex plans, amounts, and timeline)
  demand_outlook: string | null         (demand environment for their key markets)
  margins: string | null                (margin trend, drivers, and management expectation)
  risks: string | null                  (key risks explicitly flagged by management)
  qa_highlights: string | null          (3-5 most insightful analyst Q&A exchanges, summarized)
"""

_MAX_TRANSCRIPT_CHARS = 60_000   # ~15k tokens — enough for full transcript


def _extract_insights(transcript_text: str) -> dict:
    """Call GPT-4o-mini to extract structured insights from transcript text."""
    # Truncate to avoid token limits; prioritize first 60k chars (management section)
    text = transcript_text[:_MAX_TRANSCRIPT_CHARS]

    response = _get_openai().chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": f"Transcript:\n\n{text}"},
        ],
        temperature=0.0,
        max_tokens=1500,
        response_format={"type": "json_object"},
    )
    return json.loads(response.choices[0].message.content)


def extract_and_store_insights(
    client: Client,
    symbol: str,
    entry: dict,
    transcript_text: str,
) -> bool:
    """Extract structured insights from a transcript and upsert to transcript_insights.

    Returns True on success, False on failure.
    """
    try:
        insights = _extract_insights(transcript_text)
    except Exception as exc:
        print(f"[insight_extractor] {symbol} LLM extraction failed: {exc}")
        return False

    row = {
        "symbol": symbol,
        "quarter": entry.get("quarter"),
        "fiscal_year": entry.get("fiscal_year"),
        "filing_date": entry.get("filing_date") or None,
        "pdf_url": entry["url"],
        "management_commentary": insights.get("management_commentary"),
        "guidance": insights.get("guidance"),
        "capex": insights.get("capex"),
        "demand_outlook": insights.get("demand_outlook"),
        "margins": insights.get("margins"),
        "risks": insights.get("risks"),
        "qa_highlights": insights.get("qa_highlights"),
    }

    try:
        client.table("transcript_insights").upsert(row, on_conflict="pdf_url").execute()
        return True
    except Exception as exc:
        print(f"[insight_extractor] {symbol} upsert failed: {exc}")
        return False


def get_insights_context(client: Client, symbol: str, max_quarters: int = 4) -> str:
    """Fetch structured insights for the last N quarters and format as context string.

    Used by the query pipeline to directly answer structured questions
    (guidance, capex) without RAG chunking.
    """
    try:
        rows = (
            client.table("transcript_insights")
            .select("quarter,fiscal_year,guidance,capex,demand_outlook,margins,risks,management_commentary")
            .eq("symbol", symbol)
            .order("filing_date", desc=True)
            .limit(max_quarters)
            .execute()
            .data
        ) or []
    except Exception:
        return ""

    if not rows:
        return ""

    parts = [f"[Structured Transcript Intelligence for {symbol}]"]
    for row in rows:
        quarter = row.get("quarter") or row.get("fiscal_year") or "Unknown"
        parts.append(f"\n--- {quarter} ---")
        for field in ("management_commentary", "guidance", "capex", "demand_outlook", "margins", "risks"):
            value = row.get(field)
            if value:
                label = field.replace("_", " ").title()
                parts.append(f"{label}: {value}")

    return "\n".join(parts)
