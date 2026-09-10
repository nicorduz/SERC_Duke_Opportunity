"""
warn_live.py — AUTOMATIC daily layoff signal for the whole SERC footprint.

Source: WARN Firehose (https://warnfirehose.com) — aggregates WARN Act notices
scraped daily from all 50 state workforce agencies into one REST API.
  · Base URL : https://warnfirehose.com/api
  · Auth     : header  X-API-Key: <key>   (free key at /account)
  · Free tier: 25 calls/day, 25 records/call, WARN dataset only.
    -> That is why we make ONE call per state (7 states = 7 calls/day),
       never one call per company. Cache to parquet and refresh once a day.
  · /api/stats needs no key at all (useful as a connectivity check).

Fallback: if no key is configured, we call the state endpoint anonymously; if
that fails we return whatever the previous cached parquet had, so the app never
breaks because of a layoff feed.

Output schema (one row per notice), aligned with distress_sources provenance:
    company, state, city, county, employees_affected, notice_date, layoff_date,
    source, url, energy_relevant
"""
from __future__ import annotations
import pandas as pd

API = "https://warnfirehose.com/api"

# Keep in sync with scope.SERC_STATES (kept local to avoid a hard import cycle).
SERC_STATES = ["NC", "SC", "GA", "FL", "AL", "MS", "TN", "VA", "KY"]

# Employer-name keywords that make a layoff relevant to our sector.
ENERGY_KWS = ["solar", "energy", "power", "renewab", "electric", "epc", "utilit",
              "battery", "storage", "grid", "wind", "photovolt", "invert", "panel",
              "turbine", "transformer", "substation", "construction", "engineering"]


def _relevant(name) -> bool:
    s = str(name or "").lower()
    return any(k in s for k in ENERGY_KWS)


def fetch_warn_live(states=None, api_key=None, days=365, per_state=25, timeout=30):
    """
    Pull recent WARN notices for each SERC state. One HTTP call per state.
    Returns a normalized DataFrame (empty on total failure — caller keeps cache).
    """
    import requests
    states = states or SERC_STATES
    headers = {"X-API-Key": api_key} if api_key else {}
    date_from = (pd.Timestamp.today() - pd.Timedelta(days=days)).date().isoformat()

    rows = []
    for st in states:
        try:
            r = requests.get(f"{API}/records", headers=headers, timeout=timeout,
                             params={"state": st, "date_from": date_from,
                                     "limit": per_state})
            if r.status_code != 200:
                continue
            payload = r.json()
            # the API returns either a list or {"records": [...]} depending on route
            recs = payload if isinstance(payload, list) else (
                payload.get("records") or payload.get("data") or [])
            for it in recs:
                rows.append({
                    "company": it.get("company") or it.get("company_name"),
                    "state": it.get("state") or st,
                    "city": it.get("city"),
                    "county": (it.get("county") or "").replace(" County", "").strip(),
                    "employees_affected": it.get("employees_affected") or it.get("layoff_count"),
                    "notice_date": it.get("notice_date") or it.get("received_date"),
                    "layoff_date": it.get("layoff_date") or it.get("effective_date"),
                    "source": "WARN Firehose",
                    "url": it.get("source_url") or "https://www.warnfirehose.com/layoffs",
                })
        except Exception:
            continue

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["notice_date"] = pd.to_datetime(df["notice_date"], errors="coerce")
    df["energy_relevant"] = df["company"].map(_relevant)
    return df.drop_duplicates(subset=["company", "state", "notice_date"]).reset_index(drop=True)


def to_provenance(warn_df, entities, g):
    """
    Convert WARN notices into distress_sources-style provenance rows, on BOTH layers:
      · DIRECT : the employer name fuzzy-matches one of our entities (owner/parent/EPC)
      · AMBIENT: the notice is in a county where we hold projects (sector stress nearby)
    `entities` is the output of distress_sources.build_entity_list(...).
    """
    from distress_sources import norm, _sim
    if warn_df is None or warn_df.empty:
        return pd.DataFrame()

    ent_pairs = list(zip(entities["entity_norm"], entities["generator_ids"])) \
        if entities is not None and len(entities) else []
    cty_map = {}
    for gid, cty, stt in zip(g["Generator ID"], g["County"].fillna(""), g["State"].fillna("")):
        cty_map.setdefault((str(cty).strip().lower(), str(stt).strip().upper()), []).append(gid)

    out = []
    for _, w in warn_df.iterrows():
        title = f"WARN layoff: {w['company']} ({w.get('employees_affected') or '?'} empleados)"
        base = {"signal_type": "layoff", "title": title,
                "date": w["notice_date"], "url": w.get("url", ""),
                "source": "WARN Firehose"}

        # --- DIRECT: employer matches one of our entities
        wn = norm(w["company"])
        if wn:
            for en, gids in ent_pairs:
                if en and (en in wn or wn in en or _sim(en, wn) >= 0.90):
                    out.append({**base, "entity_norm": en, "matched_on": w["company"],
                                "match_type": "direct", "confidence": 0.85,
                                "generator_ids": list(gids)})
                    break

        # --- AMBIENT: energy-relevant layoff in a county where we hold projects
        if w.get("energy_relevant"):
            gids = cty_map.get((str(w.get("county", "")).strip().lower(),
                                str(w.get("state", "")).strip().upper()), [])
            if gids:
                out.append({**base, "entity_norm": "", "matched_on": f"{w.get('county')} County",
                            "match_type": "ambient", "confidence": 0.4,
                            "generator_ids": gids})
    return pd.DataFrame(out)
