"""
distress_sources.py — the entity-centric distress engine (SERC-wide, free sources).

Solves the core problem: you can't search 1,130 projects one-by-one, and you don't
know which to search. So:

  1. Collapse projects -> a deduplicated ENTITY target list (owner / parent /
     interconnection customer / project name). ~1,130 projects become ~89 entities.
  2. Search each source ONCE per entity or per geography, never per project:
       - LARGE databases (CourtListener bankruptcy/litigation)  -> query by entity name
       - BOUNDED feeds (news, WARN, queue withdrawals, Sabin)    -> pull whole, join
  3. Match every hit back to projects on two layers:
       - DIRECT  : signal names the entity/project (high confidence)
       - AMBIENT : signal is tied to the project's county (contextual, lower weight)
  4. Store provenance for every hit (source, url, date, type, confidence) so the UI
     can drill straight into the source. Produce a per-project distress sub-score.

Free sources wired here:
  - CourtListener v4 REST API (bankruptcy + litigation) — free token, rate-limited.
  - Google News RSS (layoffs / PPA cancellations / distress) — reuses web_signals.
  - WARN layoffs (multi-state, uploaded) — ambient by county + direct by employer.
  - Duke queue withdrawals (utility-confirmed) — direct by (BA+queue id).
LIENS: true bulk lien data is the one piece not cleanly free. fetch_liens_apify()
is a ready hook for an Apify actor (cheap credits); until then liens stay a manual
diligence step (actions.py already links to SoS UCC / register of deeds).
"""
from __future__ import annotations
import re, time
import numpy as np
import pandas as pd
from difflib import SequenceMatcher

# ---------------------------------------------------------------- normalization
_LEGAL = re.compile(
    r"\b(llc|l\.l\.c|inc|inc\.|corp|corporation|co|company|lp|l\.p|llp|holdings?|"
    r"energy|solar|power|renewables?|development|ventures?|partners?|group|"
    r"project|projects?|farm|farms|generation|storage|the)\b", re.I)

def norm(name) -> str:
    if not isinstance(name, str) or not name.strip():
        return ""
    s = name.lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = _LEGAL.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()

def _sim(a, b) -> float:
    return SequenceMatcher(None, a, b).ratio()


# ---------------------------------------------------------------- 1. entity list
def build_entity_list(g, oasis=None, min_len=4):
    """
    Deduplicated entity target list. One row per distinct normalized entity, with the
    generator IDs it maps to. Pulls from Owner, Parent Company, and — where available —
    the OASIS 'interconnection_customer' (the SPV that Orennia often lacks).
    """
    rows = []
    def add(raw, gid, field):
        n = norm(raw)
        if len(n) >= min_len:
            rows.append({"entity_norm": n, "entity_raw": str(raw).strip(),
                         "generator_id": gid, "field": field})

    for _, r in g.iterrows():
        gid = r["Generator ID"]
        for col, tag in [("Owner", "owner"), ("Parent Company", "parent"),
                         ("Parent Company 2", "parent")]:
            if col in g.columns and pd.notna(r.get(col)):
                add(r[col], gid, tag)

    # OASIS interconnection customer -> owner for queue-stage projects lacking one
    if oasis is not None and "interconnection_customer" in oasis.columns and "queue_id" in oasis.columns:
        qmap = (g.dropna(subset=["Queue ID"])
                  .assign(_q=lambda d: d["Queue ID"].astype(str).str.strip())
                  .set_index("_q")["Generator ID"].to_dict())
        for _, o in oasis.iterrows():
            gid = qmap.get(str(o.get("queue_id")).strip())
            if gid is not None and pd.notna(o.get("interconnection_customer")):
                add(o["interconnection_customer"], gid, "ic_customer")

    if not rows:
        return pd.DataFrame(columns=["entity_norm", "entity_raw", "generator_ids", "n_projects", "fields"])
    df = pd.DataFrame(rows)
    ent = (df.groupby("entity_norm")
             .agg(entity_raw=("entity_raw", lambda s: s.value_counts().index[0]),
                  generator_ids=("generator_id", lambda s: sorted(set(s))),
                  fields=("field", lambda s: sorted(set(s))))
             .reset_index())
    ent["n_projects"] = ent["generator_ids"].str.len()
    return ent.sort_values("n_projects", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------- 2. free fetchers
def fetch_courtlistener(entities, token=None, filed_after_days=540, per_min=5,
                        max_entities=80):
    """
    Query CourtListener v4 /search/?type=r (RECAP dockets) by ENTITY name.
    Free API: Authorization: Token <key>. NOTE the May-2026 rate limits
    (~5/min, ~125/day for a plain free account) — this is exactly why we query
    the ~34-89 deduplicated entities, never 1,130 projects. Pass a token; a free
    Free Law Project membership raises the cap. Returns provenance rows.
    """
    import requests
    base = "https://www.courtlistener.com/api/rest/v4/search/"
    headers = {"Authorization": f"Token {token}"} if token else {}
    after = (pd.Timestamp.today() - pd.Timedelta(days=filed_after_days)).date()
    rows, sleep = [], max(60.0 / per_min, 1.0)
    for ent in entities.head(max_entities).itertuples():
        try:
            r = requests.get(base, headers=headers, timeout=30, params={
                "q": f'"{ent.entity_raw}"', "type": "r",
                "order_by": "dateFiled desc", "filed_after": str(after)})
            if r.status_code == 429:
                time.sleep(30); continue
            for it in r.json().get("results", [])[:5]:
                name = it.get("caseName", "")
                low = name.lower()
                typ = ("bankruptcy" if any(k in low for k in ("bankrupt", "chapter 11", "chapter 7"))
                       else "litigation")
                rows.append({
                    "entity_norm": ent.entity_norm, "matched_on": ent.entity_raw,
                    "signal_type": typ, "title": name,
                    "date": it.get("dateFiled", ""), "court": it.get("court", ""),
                    "url": "https://www.courtlistener.com" + (it.get("absolute_url") or ""),
                    "source": "CourtListener", "match_type": "direct", "confidence": 0.9,
                    "generator_ids": ent.generator_ids})
        except Exception:
            pass
        time.sleep(sleep)
    return pd.DataFrame(rows)


def fetch_news(entities, max_entities=40):
    """Google News RSS distress scan by entity (SERC-wide, free, no key).
    Thin wrapper over web_signals so you keep one implementation."""
    try:
        import web_signals
    except Exception:
        return pd.DataFrame()
    fake_g = pd.DataFrame({"Power Project Name": entities["entity_raw"].head(max_entities)})
    news = web_signals.scan_web_signals(fake_g, ownership=None, max_companies=max_entities)
    if news is None or news.empty:
        return pd.DataFrame()
    nmap = {norm(e): gids for e, gids in zip(entities["entity_raw"], entities["generator_ids"])}
    news = news.rename(columns={"link": "url", "published": "date"})
    news["entity_norm"] = news["company"].map(norm)
    news["generator_ids"] = news["entity_norm"].map(lambda n: nmap.get(n, []))
    news["source"] = "Google News"; news["match_type"] = "direct"; news["confidence"] = 0.55
    news["matched_on"] = news["company"]
    return news[["entity_norm", "matched_on", "signal_type", "title", "date",
                 "url", "source", "match_type", "confidence", "generator_ids"]]


def fetch_liens_free(entities, courtlistener_token=None, states=("FL",), max_entities=40):
    """
    FREE + automatic lien signal. Two layers:
      1. CourtListener lien/foreclosure/receivership actions (works today, free API)
      2. Free state UCC registries (FL open; NC/SC adapters need one-time validation)
    """
    import lien_sources
    frames = []
    try:
        frames.append(lien_sources.courtlistener_lien_terms(
            entities, token=courtlistener_token, max_entities=max_entities))
    except Exception:
        pass
    try:
        frames.append(lien_sources.fetch_state_liens(
            entities, states=states, max_entities=max_entities))
    except Exception:
        pass
    frames = [f for f in frames if f is not None and not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def fetch_liens_apify(entities, apify_token, actor="pink_comic~ucc-lien-search",
                      max_entities=30):
    """
    HOOK for lien/UCC data via an Apify actor (cheap credits, ~free tier).
    Leave apify_token None to no-op. Swap `actor` for whichever UCC / register-of-deeds
    actor you pilot. Until wired, liens remain a manual step via actions.py links.
    Returns provenance rows in the same schema as the other fetchers.
    """
    if not apify_token:
        return pd.DataFrame()
    import requests
    url = f"https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items?token={apify_token}"
    rows = []
    for ent in entities.head(max_entities).itertuples():
        try:
            r = requests.post(url, json={"debtorName": ent.entity_raw}, timeout=90)
            for it in (r.json() if r.status_code == 200 else []):
                rows.append({
                    "entity_norm": ent.entity_norm, "matched_on": ent.entity_raw,
                    "signal_type": "lien", "title": it.get("filingType", "UCC/lien filing"),
                    "date": it.get("filingDate", ""), "url": it.get("sourceUrl", ""),
                    "source": "Apify/UCC", "match_type": "direct", "confidence": 0.8,
                    "generator_ids": ent.generator_ids})
        except Exception:
            pass
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 3. ambient (county) layer
def county_ambient(g, warn=None, duke_queue=None, restrictions=None, contested=None):
    """
    Aggregate bounded feeds to COUNTY, so every project (including the ~46% with no
    owner) inherits its county's distress context. Returns (project_rows, county_index).
    project_rows are provenance rows with match_type='ambient'.
    """
    cty_col = g["County"].fillna("").str.strip().str.lower()
    events = {}   # county -> list of (type, label, url)

    def push(cty, typ, label, url=""):
        c = str(cty).strip().lower()
        if c:
            events.setdefault(c, []).append((typ, label, url))

    if warn is not None and "energy_relevant" in warn.columns:
        for _, w in warn[warn["energy_relevant"] == True].iterrows():
            push(w.get("county"), "layoff",
                 f"WARN layoff: {w.get('company','?')}", w.get("link", ""))
    if duke_queue is not None and "status" in duke_queue.columns:
        wd = duke_queue[duke_queue["status"].astype(str).str.lower() == "withdrawn"]
        cw = wd.groupby(wd["county"].astype(str).str.lower())["mw"].sum()
        for c, mw in cw[cw >= 50].items():
            push(c, "withdrawal_cluster", f"≥50 MW withdrawn from Duke queue ({mw:.0f} MW)")
    if restrictions is not None and "county_clean" in restrictions.columns:
        for _, r in restrictions.iterrows():
            push(r.get("county_clean"), "ordinance",
                 f"Solar ordinance: {str(r.get('title',''))[:60]}", "")
    if contested is not None and "county_clean" in contested.columns:
        for _, r in contested.iterrows():
            push(r.get("county_clean"), "contested",
                 f"Contested project: {str(r.get('title',''))[:60]}", "")

    W = {"layoff": 2.0, "withdrawal_cluster": 1.0, "ordinance": -1.0, "contested": 0.5}
    rows = []
    for i, gid in enumerate(g["Generator ID"].values):
        c = cty_col.iloc[i]
        for typ, label, url in events.get(c, []):
            rows.append({"entity_norm": "", "matched_on": f"{c.title()} County",
                         "signal_type": typ, "title": label, "date": "",
                         "url": url, "source": "county-feed", "match_type": "ambient",
                         "confidence": 0.4, "generator_ids": [gid], "weight": W.get(typ, 0.5)})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 4. assemble + score
_TYPE_W = {"bankruptcy": 3.0, "lien": 3.0, "ppa_cancelled": 3.0, "layoff": 2.0,
           "litigation": 1.5, "withdrawal_cluster": 1.0, "ordinance": -1.0,
           "contested": 0.5, "signal": 1.0}

def assemble(*frames, direct_w=1.0, ambient_w=0.35):
    """Concatenate provenance frames, explode to (generator_id, signal), decay by age."""
    frames = [f for f in frames if f is not None and not f.empty]
    if not frames:
        return pd.DataFrame(), pd.DataFrame()
    prov = pd.concat(frames, ignore_index=True)
    prov = prov.explode("generator_ids").rename(columns={"generator_ids": "Generator ID"})
    prov = prov.dropna(subset=["Generator ID"])
    prov["date"] = pd.to_datetime(prov["date"], errors="coerce")
    age = (pd.Timestamp.today() - prov["date"]).dt.days.fillna(270)
    prov["decay"] = np.exp(-age / 365.0)
    base_w = prov.get("weight", pd.Series(np.nan, index=prov.index))
    prov["type_w"] = np.where(base_w.notna(), base_w,
                              prov["signal_type"].map(_TYPE_W).fillna(1.0))
    layer_w = np.where(prov["match_type"] == "direct", direct_w, ambient_w)
    prov["contribution"] = prov["type_w"] * prov["confidence"] * prov["decay"] * layer_w

    per_proj = (prov.groupby("Generator ID")
                    .agg(distress_score=("contribution", "sum"),
                         n_signals=("signal_type", "count"),
                         signal_types=("signal_type", lambda s: ", ".join(sorted(set(s)))),
                         has_direct=("match_type", lambda s: (s == "direct").any()))
                    .reset_index())
    return per_proj, prov


def distress_screen(per_proj):
    """Wrap the numeric sub-score as a composite_score-compatible screen (binary fire)."""
    if per_proj is None or per_proj.empty:
        return pd.DataFrame(columns=["Generator ID", "Reason"])
    d = per_proj[per_proj["distress_score"] > 0].copy()
    tag = np.where(d["has_direct"], "DIRECT", "ambient")
    d["Reason"] = ("External distress [" + tag + "]: " + d["signal_types"]
                   + " (score " + d["distress_score"].round(2).astype(str) + ")")
    return d[["Generator ID", "Reason"]]
