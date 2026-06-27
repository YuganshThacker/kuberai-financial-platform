"""
Annual report retrieval validation — 60 questions across 5 pilot companies.

Phases:
  Phase 3A: Original 50 questions (5 categories × 10 questions)
  Phase 3B: 10 additional questions (subsidiaries, ESG, governance, auditor, capex)
  Phase 5:  25 UAT investor questions — realistic, company-specific

Usage:
    python scripts/run_annual_report_validation.py [--symbol RELIANCE] [--phase 3a|3b|uat|all]

Output: per-question result table + overall accuracy summary.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from supabase import create_client

from embeddings.embedder import embed_texts

PILOT_SYMBOLS = ["RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK"]

# ── 50 original questions ─────────────────────────────────────────────────────

_PHASE3A_QUESTIONS: list[tuple[str, str, str]] = [
    # (category, id, question)
    # GOVERNANCE
    ("GOV", "GOV-01", "Who are the independent directors on the board?"),
    ("GOV", "GOV-02", "What is the composition of the audit committee?"),
    ("GOV", "GOV-03", "How many board meetings were held during the year?"),
    ("GOV", "GOV-04", "What is the remuneration policy for key managerial personnel?"),
    ("GOV", "GOV-05", "What related party transactions occurred during the year?"),
    ("GOV", "GOV-06", "What is the shareholding pattern of the promoter group?"),
    ("GOV", "GOV-07", "Who is the company secretary and compliance officer?"),
    ("GOV", "GOV-08", "What whistleblower policy is in place?"),
    ("GOV", "GOV-09", "How are director appointments and re-appointments governed?"),
    ("GOV", "GOV-10", "What is the board's policy on corporate social responsibility?"),
    # ESG / BRSR
    ("ESG", "ESG-01", "What are the company's Scope 1 and Scope 2 greenhouse gas emissions?"),
    ("ESG", "ESG-02", "What water consumption targets has the company set?"),
    ("ESG", "ESG-03", "What percentage of renewable energy does the company use?"),
    ("ESG", "ESG-04", "What is the company's diversity and inclusion policy?"),
    ("ESG", "ESG-05", "What is the employee attrition rate?"),
    ("ESG", "ESG-06", "What safety incidents occurred and what is the LTIFR?"),
    ("ESG", "ESG-07", "What community development programs does the company run?"),
    ("ESG", "ESG-08", "What is the company's waste recycling and circular economy strategy?"),
    ("ESG", "ESG-09", "What ESG ratings or certifications has the company received?"),
    ("ESG", "ESG-10", "What supply chain sustainability standards are applied?"),
    # SUBSIDIARIES
    ("SUB", "SUB-01", "What subsidiaries does the company have?"),
    ("SUB", "SUB-02", "What is the revenue contribution of each major subsidiary?"),
    ("SUB", "SUB-03", "Were any subsidiaries incorporated or wound up during the year?"),
    ("SUB", "SUB-04", "What are the joint ventures and associate companies?"),
    ("SUB", "SUB-05", "What is the company's international presence through subsidiaries?"),
    ("SUB", "SUB-06", "What dividend was received from subsidiaries?"),
    ("SUB", "SUB-07", "Are there any step-down subsidiaries?"),
    ("SUB", "SUB-08", "What regulatory approvals govern subsidiary operations?"),
    ("SUB", "SUB-09", "What is the net worth of material subsidiaries?"),
    ("SUB", "SUB-10", "What consolidation policy is applied for subsidiaries?"),
    # AUDITOR / RISK
    ("AUD", "AUD-01", "Who are the statutory auditors and when was their appointment?"),
    ("AUD", "AUD-02", "What key audit matters did the auditors identify?"),
    ("AUD", "AUD-03", "Did the auditors issue any qualified opinion?"),
    ("AUD", "AUD-04", "What were the total audit fees paid to the auditors?"),
    ("AUD", "AUD-05", "What is the company's internal audit framework?"),
    ("AUD", "AUD-06", "What material risks does the company face?"),
    ("AUD", "AUD-07", "How does the company manage cybersecurity risks?"),
    ("AUD", "AUD-08", "What litigation risks are disclosed?"),
    ("AUD", "AUD-09", "What is the risk management committee composition?"),
    ("AUD", "AUD-10", "What regulatory compliance risks exist?"),
    # DIVIDEND / CAPITAL
    ("DIV", "DIV-01", "What dividend was declared for the year?"),
    ("DIV", "DIV-02", "What is the company's dividend payout policy?"),
    ("DIV", "DIV-03", "What share buyback programs were executed?"),
    ("DIV", "DIV-04", "How was the authorized and paid-up share capital changed?"),
    ("DIV", "DIV-05", "What are the outstanding stock options under ESOP?"),
    ("DIV", "DIV-06", "What are the capital expenditure plans for next year?"),
    ("DIV", "DIV-07", "How was free cash flow deployed during the year?"),
    ("DIV", "DIV-08", "What is the return on equity and return on capital employed?"),
    ("DIV", "DIV-09", "What debt was raised or repaid during the year?"),
    ("DIV", "DIV-10", "What is the company's investment in treasury shares?"),
]

# ── 10 additional questions (Phase 3B) ────────────────────────────────────────

_PHASE3B_QUESTIONS: list[tuple[str, str, str]] = [
    ("ADD", "ADD-01", "What are the revenue contributions from each business segment?"),
    ("ADD", "ADD-02", "What percentage of revenue comes from international operations?"),
    ("ADD", "ADD-03", "What acquisitions were made during the year and at what valuation?"),
    ("ADD", "ADD-04", "What is the company's credit rating and borrowing cost?"),
    ("ADD", "ADD-05", "What contingent liabilities are disclosed in the annual report?"),
    ("ADD", "ADD-06", "What are the significant accounting policies adopted?"),
    ("ADD", "ADD-07", "What employee benefits obligations are recognized on the balance sheet?"),
    ("ADD", "ADD-08", "What is the company's deferred tax position?"),
    ("ADD", "ADD-09", "What impairment tests were conducted on goodwill and intangibles?"),
    ("ADD", "ADD-10", "What are the details of the company's lease obligations under Ind AS 116?"),
]

# ── 25 UAT investor questions (Phase 5) ──────────────────────────────────────

_UAT_QUESTIONS: list[tuple[str, str, str, str]] = [
    # (symbol, id, question, expected_topic)
    ("RELIANCE", "UAT-01",
     "What are Reliance Industries' Scope 1 and Scope 2 greenhouse gas emissions?",
     "ESG/GHG"),
    ("RELIANCE", "UAT-02",
     "How many board meetings did Reliance Industries hold and who attended?",
     "Governance"),
    ("RELIANCE", "UAT-03",
     "What subsidiaries does Reliance Industries have and what do they contribute?",
     "Subsidiaries"),
    ("RELIANCE", "UAT-04",
     "What dividend did Reliance Industries declare and what is the payout policy?",
     "Dividend"),
    ("RELIANCE", "UAT-05",
     "What key audit matters did Reliance Industries' auditors identify?",
     "Audit/Risk"),
    ("TCS", "UAT-06",
     "What is TCS's policy on dividend and how much was paid per share?",
     "Dividend"),
    ("TCS", "UAT-07",
     "What are TCS's environmental sustainability targets and progress?",
     "ESG"),
    ("TCS", "UAT-08",
     "Who are the independent directors on the TCS board and what are their qualifications?",
     "Governance"),
    ("TCS", "UAT-09",
     "What subsidiaries does TCS operate in different countries?",
     "Subsidiaries"),
    ("TCS", "UAT-10",
     "What cyber-security and technology risks does TCS disclose?",
     "Risk"),
    ("HDFCBANK", "UAT-11",
     "What are HDFC Bank's key audit matters as identified by statutory auditors?",
     "Audit"),
    ("HDFCBANK", "UAT-12",
     "What is HDFC Bank's NPA ratio and credit risk management framework?",
     "Risk/Credit"),
    ("HDFCBANK", "UAT-13",
     "What capital adequacy ratio does HDFC Bank maintain?",
     "Capital"),
    ("HDFCBANK", "UAT-14",
     "What governance risks does HDFC Bank highlight in its annual report?",
     "Governance"),
    ("HDFCBANK", "UAT-15",
     "What are HDFC Bank's ESG commitments and sustainability disclosures?",
     "ESG"),
    ("INFY", "UAT-16",
     "What subsidiaries does Infosys own globally?",
     "Subsidiaries"),
    ("INFY", "UAT-17",
     "What is Infosys's employee attrition rate and talent retention strategy?",
     "ESG/HR"),
    ("INFY", "UAT-18",
     "What capital allocation decisions did Infosys make — buybacks, dividends, M&A?",
     "Capital Allocation"),
    ("INFY", "UAT-19",
     "Who are Infosys's statutory auditors and what were their audit fees?",
     "Audit"),
    ("INFY", "UAT-20",
     "What are Infosys's Scope 1, 2, and 3 carbon emissions?",
     "ESG/GHG"),
    ("ICICIBANK", "UAT-21",
     "What governance risks are highlighted in ICICI Bank's annual report?",
     "Governance"),
    ("ICICIBANK", "UAT-22",
     "What is ICICI Bank's dividend policy and payout for the year?",
     "Dividend"),
    ("ICICIBANK", "UAT-23",
     "What are the key audit matters for ICICI Bank?",
     "Audit"),
    ("ICICIBANK", "UAT-24",
     "What subsidiaries does ICICI Bank have and what are their financials?",
     "Subsidiaries"),
    ("ICICIBANK", "UAT-25",
     "What is ICICI Bank's approach to climate risk and ESG disclosures?",
     "ESG"),
]


# ── Retrieval ─────────────────────────────────────────────────────────────────

def _query(client, question: str, symbol: str, match_count: int = 5) -> list[dict]:
    vector = embed_texts([question])[0]
    resp = client.rpc(
        "match_annual_report_chunks",
        {"query_embedding": vector, "match_count": match_count, "symbol_filter": symbol},
    ).execute()
    return resp.data or []


def _classify(sim: float) -> str:
    if sim >= 0.45:
        return "PASS"
    if sim >= 0.35:
        return "PARTIAL"
    return "MISS"


# ── Phase 3A — 50 questions against all 5 pilot symbols ──────────────────────

def run_phase3a(client, symbols: list[str]) -> dict:
    print("\n" + "=" * 70)
    print("PHASE 3A — 50-QUESTION FRAMEWORK")
    print("=" * 70)
    print(f"\n{'CAT':<6} {'ID':<8} {'SYMBOL':<12} {'SIM':>7} {'RESULT'}")
    print("-" * 50)

    totals = {"PASS": 0, "PARTIAL": 0, "MISS": 0}
    by_cat: dict[str, dict] = {}

    for cat, qid, question in _PHASE3A_QUESTIONS:
        cat_results = []
        for symbol in symbols:
            hits = _query(client, question, symbol)
            sim = hits[0]["similarity"] if hits else 0.0
            result = _classify(sim)
            cat_results.append((symbol, sim, result))
            totals[result] += 1

        if cat not in by_cat:
            by_cat[cat] = {"PASS": 0, "PARTIAL": 0, "MISS": 0}

        # Print one row per question (best hit across symbols)
        best = max(cat_results, key=lambda x: x[1])
        by_cat[cat][_classify(best[1])] += 1
        print(
            f"{cat:<6} {qid:<8} {best[0]:<12} {best[1]:>7.3f} {_classify(best[1])}"
        )

    print("\n" + "-" * 50)
    print("CATEGORY SUMMARY")
    print(f"{'CAT':<6} {'PASS':>6} {'PARTIAL':>8} {'MISS':>6}")
    for cat in ["GOV", "ESG", "SUB", "AUD", "DIV"]:
        c = by_cat.get(cat, {})
        print(f"{cat:<6} {c.get('PASS',0):>6} {c.get('PARTIAL',0):>8} {c.get('MISS',0):>6}")

    total_q = len(_PHASE3A_QUESTIONS)
    print(f"\nOVERALL (best hit per question, {total_q} questions):")
    print(f"  PASS    : {totals['PASS']:>3}  ({totals['PASS']/total_q*100:.0f}%)")
    print(f"  PARTIAL : {totals['PARTIAL']:>3}  ({totals['PARTIAL']/total_q*100:.0f}%)")
    print(f"  MISS    : {totals['MISS']:>3}  ({totals['MISS']/total_q*100:.0f}%)")

    return totals


# ── Phase 3B — 10 additional questions ───────────────────────────────────────

def run_phase3b(client, symbols: list[str]) -> dict:
    print("\n" + "=" * 70)
    print("PHASE 3B — 10 ADDITIONAL QUESTIONS")
    print("=" * 70)
    print(f"\n{'ID':<8} {'SYMBOL':<12} {'SIM':>7} {'RESULT'}  SECTION")
    print("-" * 55)

    totals = {"PASS": 0, "PARTIAL": 0, "MISS": 0}

    for cat, qid, question in _PHASE3B_QUESTIONS:
        best_sim = 0.0
        best_sym = ""
        best_section = ""
        for symbol in symbols:
            hits = _query(client, question, symbol)
            if hits:
                sim = hits[0]["similarity"]
                if sim > best_sim:
                    best_sim = sim
                    best_sym = symbol
                    best_section = hits[0].get("section_type", "—") or "—"
        result = _classify(best_sim)
        totals[result] += 1
        print(f"{qid:<8} {best_sym:<12} {best_sim:>7.3f} {result:<8} {best_section}")

    print(f"\n10 questions: PASS={totals['PASS']} PARTIAL={totals['PARTIAL']} MISS={totals['MISS']}")
    return totals


# ── Phase 5 — UAT (company-specific questions) ────────────────────────────────

def run_uat(client) -> dict:
    print("\n" + "=" * 70)
    print("PHASE 5 — UAT: 25 REALISTIC INVESTOR QUESTIONS")
    print("=" * 70)
    print(f"\n{'ID':<8} {'SYMBOL':<12} {'TOPIC':<18} {'SIM':>7} {'RESULT'}  TOP SECTION")
    print("-" * 75)

    totals = {"PASS": 0, "PARTIAL": 0, "MISS": 0}

    for symbol, qid, question, topic in _UAT_QUESTIONS:
        hits = _query(client, question, symbol)
        sim = hits[0]["similarity"] if hits else 0.0
        section = (hits[0].get("section_type", "—") or "—") if hits else "—"
        result = _classify(sim)
        totals[result] += 1
        print(f"{qid:<8} {symbol:<12} {topic:<18} {sim:>7.3f} {result:<8} {section}")

    total_q = len(_UAT_QUESTIONS)
    print(f"\nUAT Summary ({total_q} questions):")
    print(f"  PASS    : {totals['PASS']:>3}  ({totals['PASS']/total_q*100:.0f}%)")
    print(f"  PARTIAL : {totals['PARTIAL']:>3}  ({totals['PARTIAL']/total_q*100:.0f}%)")
    print(f"  MISS    : {totals['MISS']:>3}  ({totals['MISS']/total_q*100:.0f}%)")
    return totals


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", help="Filter to a single symbol")
    parser.add_argument(
        "--phase", choices=["3a", "3b", "uat", "all"], default="all",
        help="Which validation phase to run (default: all)"
    )
    args = parser.parse_args()

    client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
    symbols = [args.symbol.upper()] if args.symbol else PILOT_SYMBOLS

    all_totals: dict[str, dict] = {}

    if args.phase in ("3a", "all"):
        all_totals["3a"] = run_phase3a(client, symbols)

    if args.phase in ("3b", "all"):
        all_totals["3b"] = run_phase3b(client, symbols)

    if args.phase in ("uat", "all"):
        all_totals["uat"] = run_uat(client)

    if args.phase == "all" and len(all_totals) == 3:
        total_pass = sum(t["PASS"] for t in all_totals.values())
        total_partial = sum(t["PARTIAL"] for t in all_totals.values())
        total_miss = sum(t["MISS"] for t in all_totals.values())
        total_q = 85  # 50 + 10 + 25
        print("\n" + "=" * 70)
        print("COMBINED ACCURACY (85 questions total)")
        print("=" * 70)
        print(f"  PASS    : {total_pass:>3}/{total_q}  ({total_pass/total_q*100:.0f}%)")
        print(f"  PARTIAL : {total_partial:>3}/{total_q}  ({total_partial/total_q*100:.0f}%)")
        print(f"  MISS    : {total_miss:>3}/{total_q}  ({total_miss/total_q*100:.0f}%)")


if __name__ == "__main__":
    main()
