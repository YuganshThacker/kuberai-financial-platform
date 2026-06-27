# Curated investor relations URLs for Nifty 50 companies.
# These are the official IR pages companies maintain for institutional investors.
# Source: company websites + NSE listing information.
# Used by the web_search pipeline as a direct data source (fetched via Jina).

COMPANY_IR_URLS: dict[str, str] = {
    # IT / Technology
    "TCS":        "https://www.tcs.com/investor-relations",
    "INFY":       "https://www.infosys.com/investors.html",
    "WIPRO":      "https://www.wipro.com/investors/",
    "HCLTECH":    "https://www.hcltech.com/investors",
    "TECHM":      "https://www.techmahindra.com/en-in/investor-relations/",
    "LTIM":       "https://www.ltimindtree.com/investors",
    "PERSISTENT": "https://www.persistent.com/investors/",

    # Banking / Financial Services
    "HDFCBANK":   "https://www.hdfcbank.com/investor-relations",
    "ICICIBANK":  "https://www.icicibank.com/investor-relations",
    "KOTAKBANK":  "https://www.kotak.com/en/investor-relations.html",
    "AXISBANK":   "https://www.axisbank.com/shareholders-corner",
    "SBIN":       "https://sbi.co.in/web/investor-relations",
    "INDUSINDBK": "https://www.indusind.com/in/en/investor-relations.html",
    "FEDERALBNK": "https://www.federalbank.co.in/investor-relations",
    "BANDHANBNK": "https://www.bandhanbank.com/investor-relations",

    # Insurance
    "SBILIFE":    "https://www.sbilife.co.in/sbilife/investor-relations",
    "HDFCLIFE":   "https://www.hdfclife.com/investor-relations",
    "ICICIGI":    "https://www.icicilombard.com/investor-relations",
    "BAJFINANCE": "https://www.bajajfinserv.in/investor-relations-bajaj-finance",
    "BAJAJFINSV": "https://www.bajajfinserv.in/investor-relations",

    # Energy / Oil & Gas
    "RELIANCE":   "https://www.ril.com/investor-relations",
    "ONGC":       "https://www.ongcindia.com/en/investors",
    "BPCL":       "https://www.bpclindia.com/investors.php",
    "IOC":        "https://www.iocl.com/investor",
    "NTPC":       "https://www.ntpc.co.in/en/investors",
    "POWERGRID":  "https://www.powergrid.in/investor-relations",
    "COALINDIA":  "https://www.coalindia.in/en-us/company/pages/investorrelations.aspx",

    # Industrials / Engineering
    "LT":         "https://www.larsentoubro.com/corporate/investors/",
    "BAJAJ-AUTO": "https://www.bajajauto.com/investors",
    "MARUTI":     "https://www.marutisuzuki.com/corporate/investors",
    "TATAMOTORS": "https://www.tatamotors.com/investors/",
    "M&M":        "https://www.mahindra.com/investor-relations",
    "EICHERMOT":  "https://www.eicherworld.com/investors.aspx",
    "HEROMOTOCO": "https://www.heromotocorp.com/en-in/investors.html",

    # Metals / Materials
    "TATASTEEL":  "https://www.tatasteel.com/investors/",
    "JSWSTEEL":   "https://www.jsw.in/investors/jsw-steel",
    "HINDALCO":   "https://www.hindalco.com/investors",
    "ADANIENT":   "https://www.adanienterprises.com/investors",
    "ADANIPORTS": "https://www.adaniports.com/investors",
    "ULTRACEMCO": "https://www.ultratechcement.com/investors",
    "GRASIM":     "https://www.grasim.com/investor-relations",

    # FMCG / Consumer
    "HINDUNILVR": "https://www.hul.co.in/investor-relations/",
    "ITC":        "https://www.itcportal.com/investor-zone/index.aspx",
    "NESTLEIND":  "https://www.nestle.in/investors",
    "TATACONSUM": "https://www.tataconsumer.com/investors",
    "ASIANPAINT": "https://www.asianpaints.com/about-us/investor-relations.html",
    "TITAN":      "https://www.titancompany.in/investors",

    # Pharma / Healthcare
    "SUNPHARMA":  "https://www.sunpharma.com/investors",
    "DRREDDY":    "https://www.drreddys.com/investors",
    "CIPLA":      "https://www.cipla.com/investor-relations",
    "DIVISLAB":   "https://www.divislab.com/investors/",
    "APOLLOHOSP": "https://www.apollohospitals.com/investors/",

    # Telecom / Infrastructure
    "BHARTIARTL": "https://www.airtel.in/investor-relations",
}
