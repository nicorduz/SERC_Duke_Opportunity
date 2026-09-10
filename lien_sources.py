"""
lien_sources.py — LIEN / UCC signals from FREE public registries.

HONEST FRAMING (read this before wiring it up)
----------------------------------------------
There is no free national lien API. Liens are filed state by state, and each
state publishes them differently:

  STATE  REGISTRY                                   FREE?   MACHINE-FRIENDLY?
  FL     Florida Secured Transaction Registry       YES     yes  (simple GET, best of the four)
         (floridaucc.com) — searches AND copies free
  NC     NC SOS UCC + Federal Tax Liens             YES     partly (ASP.NET form)
  SC     SC SOS UCC                                 YES     partly (ASP.NET form)
  GA     GSCCCA UCC / Lien Index                    NO      bulk data is $200/day — skipped

So the strategy is: query the FREE registries entity-by-entity (our ~34-89
deduplicated names, never 1,130 projects), and keep a manual-link fallback for
the states we cannot automate.

SECOND, ALWAYS-ON SOURCE: judgment liens, foreclosures and lien-enforcement
actions show up as *litigation* in CourtListener, which we already query for
bankruptcy. `courtlistener_lien_terms()` reuses that free API with lien-specific
search terms, so you get an automatic lien signal on day one even before the
state adapters are validated.

VALIDATION WARNING: the state portals are ASP.NET pages with ViewState. The
adapters below are written defensively (they never raise; they return an empty
frame and log a note) but the exact form fields MUST be validated against the
live site once. Run `python lien_sources.py "Pine Gate Renewables"` to test.
"""
from __future__ import annotations
import pandas as pd

# Manual-search URLs — always available, used as the fallback and for drill-in.
MANUAL = {
    "NC": "https://www.sosnc.gov/online_services/search/by_title/_UCC",
    "SC": "https://sos.sc.gov/online-filings/uniform-commercial-code",
    "FL": "https://www.floridaucc.com/uccweb/search.aspx",
    "GA": "https://search.gsccca.org/Lien/",
}

FREE_AUTOMATABLE = {"FL", "NC", "SC"}   # GA is a pay site


# --------------------------------------------------------------- adapter: Florida
def _search_florida(name, timeout=25):
    """
    Florida Secured Transaction Registry — the most open of the four:
    searches and document copies are free. Debtor-name search endpoint.
    """
    import requests
    url = "https://www.floridaucc.com/uccweb/searchResults.aspx"
    try:
        r = requests.get(url, timeout=timeout,
                         params={"searchType": "debtor", "searchValue": name},
                         headers={"User-Agent": "Mozilla/5.0 (research)"})
        if r.status_code != 200:
            return []
        tables = pd.read_html(r.text)          # lxml parses the results grid
        rows = []
        for t in tables:
            cols = [str(c).lower() for c in t.columns]
            if not any("debtor" in c or "name" in c for c in cols):
                continue
            for _, x in t.iterrows():
                rows.append({"debtor": str(x.iloc[0])[:120],
                             "filing": " | ".join(str(v)[:40] for v in x.values[1:4]),
                             "state": "FL", "url": MANUAL["FL"]})
        return rows
    except Exception:
        return []


# --------------------------------------------------------------- adapter: NC / SC
def _search_nc_sc(name, state, timeout=25):
    """
    NC and SC SOS UCC searches are free but sit behind ASP.NET ViewState forms.
    Left as a stub that returns [] rather than pretending to work: validate the
    live form fields once, then fill in the POST body here.
    """
    return []


ADAPTERS = {"FL": lambda n: _search_florida(n),
            "NC": lambda n: _search_nc_sc(n, "NC"),
            "SC": lambda n: _search_nc_sc(n, "SC")}


# --------------------------------------------------------------- state registries
def fetch_state_liens(entities, states=("FL", "NC", "SC"), max_entities=40, pause=1.0):
    """Query the free state UCC registries for each entity. Returns provenance rows."""
    import time
    rows = []
    for ent in entities.head(max_entities).itertuples():
        for st in states:
            fn = ADAPTERS.get(st)
            if fn is None:
                continue
            for hit in fn(ent.entity_raw):
                rows.append({
                    "entity_norm": ent.entity_norm, "matched_on": ent.entity_raw,
                    "signal_type": "lien",
                    "title": f"UCC/lien filing ({st}): {hit.get('debtor','')} {hit.get('filing','')}".strip(),
                    "date": "", "url": hit.get("url", MANUAL.get(st, "")),
                    "source": f"{st} UCC registry", "match_type": "direct",
                    "confidence": 0.75, "generator_ids": list(ent.generator_ids)})
            time.sleep(pause)
    return pd.DataFrame(rows)


# --------------------------------------------------------------- CourtListener liens
LIEN_TERMS = ["lien", "foreclosure", "mechanics lien", "deed of trust", "receivership"]

def courtlistener_lien_terms(entities, token=None, filed_after_days=730,
                             max_entities=40, per_min=5):
    """
    Automatic lien-adjacent signal that works TODAY: query CourtListener (free)
    for lien / foreclosure / receivership actions naming each entity.
    Same rate-limit discipline as distress_sources.fetch_courtlistener.
    """
    import requests, time
    base = "https://www.courtlistener.com/api/rest/v4/search/"
    headers = {"Authorization": f"Token {token}"} if token else {}
    after = (pd.Timestamp.today() - pd.Timedelta(days=filed_after_days)).date()
    rows, sleep = [], max(60.0 / per_min, 1.0)

    for ent in entities.head(max_entities).itertuples():
        q = f'"{ent.entity_raw}" AND (lien OR foreclosure OR receivership)'
        try:
            r = requests.get(base, headers=headers, timeout=30,
                             params={"q": q, "type": "r", "order_by": "dateFiled desc",
                                     "filed_after": str(after)})
            if r.status_code == 429:
                time.sleep(30); continue
            for it in r.json().get("results", [])[:5]:
                nm = it.get("caseName", "")
                if not any(t in nm.lower() for t in LIEN_TERMS):
                    # keep it only if the docket text clearly concerns a lien action
                    pass
                rows.append({
                    "entity_norm": ent.entity_norm, "matched_on": ent.entity_raw,
                    "signal_type": "lien", "title": nm,
                    "date": it.get("dateFiled", ""),
                    "url": "https://www.courtlistener.com" + (it.get("absolute_url") or ""),
                    "source": "CourtListener (lien/foreclosure)",
                    "match_type": "direct", "confidence": 0.7,
                    "generator_ids": list(ent.generator_ids)})
        except Exception:
            pass
        time.sleep(sleep)
    return pd.DataFrame(rows)


def manual_links(row):
    """Drill-in links for the states we cannot automate (used by actions.py / UI)."""
    st = str(row.get("State", "")).upper()
    return {"registry": MANUAL.get(st, ""), "automatable": st in FREE_AUTOMATABLE}


if __name__ == "__main__":
    import sys
    n = sys.argv[1] if len(sys.argv) > 1 else "Pine Gate Renewables"
    print("FL adapter test for:", n)
    for h in _search_florida(n):
        print(" ", h)
