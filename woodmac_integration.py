"""
woodmac_integration.py
----------------------
Drop-in module for the SERC Deal Intelligence tool.

What it does
============
1. Loads the Wood Mackenzie project files (solar + BESS) and the global
   unit->owner->parent ownership map (the .xlsx).
2. Enriches your existing Orennia dataframe: where a WoodMac project matches an
   Orennia project, it fills in missing owner / developer / financier / module /
   cost fields (a JOIN that widens Orennia).
3. Adds WoodMac-only projects (not present in Orennia) as standalone records.
4. Builds an OWNER-LEVEL M&A feature set from the M&A + VC files and exposes a
   0-10 `mna_opportunity_score()` — a buyer's view (Nofar is an acquirer), with a
   per-project provenance breakdown for the expandable UI.

It is pure pandas (no mandatory extra installs). If `rapidfuzz` is available it is
used for faster/better fuzzy matching; otherwise it falls back to difflib.

HOW TO WIRE IT
==============
Edit ONLY the ORENNIA_COLS mapping below to match your Orennia dataframe's column
names, then from your app:

    from woodmac_integration import load_woodmac, enrich_and_union, build_mna_index, mna_opportunity_score

    wm = load_woodmac(DATA_DIR)                     # loads the 5 files once (cache it)
    df = enrich_and_union(orennia_df, wm)           # widened master table
    mna = build_mna_index(wm)                        # owner -> M&A features
    score, breakdown = mna_opportunity_score(owner_name, mna)   # per project/owner
"""

from __future__ import annotations
import os
import re
import pandas as pd

# ---------------------------------------------------------------------------
# 1. CONFIG — edit these to match YOUR Orennia dataframe columns
# ---------------------------------------------------------------------------
ORENNIA_COLS = {                     # matched to SERC_Duke_Opportunity column_dictionary
    "project_name": "Power Project Name",
    "state":        "State",
    "county":       "County",
    "owner":        "Owner",
    "capacity_mw":  "Capacity (MW)",
    "generator_id": "Generator ID",
}

# File names as uploaded. Keep them in one folder and pass that folder to load_woodmac().
FILES = {
    "solar":   "Projectdetails_Solar_SERC.csv",
    "bess":    "ProjectDetails_BESS_SERC.csv",
    "mna":     "M_ADetails.csv",
    "vc":      "GranularVCData.csv",
    "company": "power-generating_unit_company_summary.xlsx",
}

US_STATE_ABBR = {
    "alabama":"AL","arkansas":"AR","florida":"FL","georgia":"GA","louisiana":"LA",
    "missouri":"MO","north carolina":"NC","south carolina":"SC","tennessee":"TN",
    "virginia":"VA","mississippi":"MS","kentucky":"KY","texas":"TX",
}

# ---------------------------------------------------------------------------
# 2. Normalization helpers
# ---------------------------------------------------------------------------
_CORP_SUFFIXES = [
    " llc"," inc"," l p"," lp"," ltd"," co"," corp"," corporation"," company",
    " energy"," solar"," power"," resources"," renewables"," renewable",
    " holdings"," group"," partners"," development"," ventures"," generation",
]

def norm_name(s) -> str:
    """Normalize a company/owner/plant name for matching."""
    s = str(s).lower().strip()
    if not s or s in ("nan", "none"):
        return ""
    s = re.sub(r"\(.*?\)", " ", s)          # drop "(FL)", "(100.00%)"
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    for suf in _CORP_SUFFIXES:
        s = s.replace(suf, " ")
    return re.sub(r"\s+", " ", s).strip()

def norm_state(s) -> str:
    s = str(s).strip().lower()
    return US_STATE_ABBR.get(s, s.upper()[:2] if len(s) <= 2 else s.title())

def _to_float(x):
    try:
        return float(str(x).replace(",", "").strip())
    except Exception:
        return None

# fuzzy backend ----------------------------------------------------------------
try:
    from rapidfuzz import fuzz as _rf
    def _ratio(a, b): return _rf.token_sort_ratio(a, b) / 100.0
except Exception:
    from difflib import SequenceMatcher
    def _ratio(a, b): return SequenceMatcher(None, a, b).ratio()


# ---------------------------------------------------------------------------
# 3. Loaders
# ---------------------------------------------------------------------------
def load_woodmac(data_dir: str) -> dict:
    """Load all WoodMac files once. Wrap with st.cache_data in your app."""
    def _csv(key):
        return pd.read_csv(os.path.join(data_dir, FILES[key]),
                           dtype=str, keep_default_na=False)

    solar = _csv("solar")
    bess  = _csv("bess")
    mna   = _csv("mna")
    vc    = _csv("vc")
    company = pd.read_excel(os.path.join(data_dir, FILES["company"]), dtype=str)

    # tidy trailing spaces that appear in WoodMac status columns
    for df in (solar, bess, mna, vc):
        df.columns = [c.strip() for c in df.columns]
        for c in df.columns:
            df[c] = df[c].astype(str).str.strip()

    # normalized solar projects (the main join target)
    solar["_name_norm"]  = solar["Power plant name"].map(norm_name)
    solar["_state"]      = solar["State"].map(norm_state)
    solar["_county"]     = solar["County"].astype(str).str.strip().str.lower()
    solar["_owner_norm"] = solar["Direct owners"].map(norm_name)
    solar["_mwac"]       = solar["Capacity (MWac)"].map(_to_float)

    bess["_name_norm"]   = bess["Power plant"].map(norm_name)
    bess["_state"]       = bess["Province/State"].map(norm_state)
    bess["_owner_norm"]  = bess["Owner"].map(norm_name)

    return {"solar": solar, "bess": bess, "mna": mna, "vc": vc, "company": company}


# ---------------------------------------------------------------------------
# 4. JOIN: enrich Orennia with WoodMac, then union WoodMac-only projects
# ---------------------------------------------------------------------------
# WoodMac solar fields we want to pull into the master table
_WM_SOLAR_FIELDS = {
    "Direct owners":               "wm_owner",
    "Developers":                  "wm_developer",
    "Financiers":                  "wm_financier",
    "EPC":                         "wm_epc",
    "Primary module manufacturer": "wm_module",
    "Tracker manufacturer":        "wm_tracker",
    "Capacity (MWac)":             "wm_mwac",
    "Capacity (MWdc)":             "wm_mwdc",
    "Capital cost ($M)":           "wm_capex_musd",
    "Cost ($/kW)":                 "wm_cost_per_kw",
    "Annual energy (MWh)":         "wm_annual_mwh",
    "Year of operation":           "wm_cod_year",
    "Status":                      "wm_status",
    "Ownership Model":             "wm_ownership_model",
    "Power plant ID":              "wm_plant_id",
}

def _match_one(o_name, o_state, o_county, o_mw, solar, name_thr=0.86):
    """Return the index of the best WoodMac solar match, or None."""
    cand = solar
    if o_state:
        cand = cand[cand["_state"] == o_state]
    if cand.empty:
        return None
    # 1) strong name match
    best_i, best_r = None, 0.0
    for i, nm in cand["_name_norm"].items():
        if not nm or not o_name:
            continue
        r = _ratio(o_name, nm)
        if r > best_r:
            best_i, best_r = i, r
    if best_r >= name_thr:
        return best_i
    # 2) fallback: same county + capacity within 10%
    if o_county and o_mw:
        c2 = cand[cand["_county"] == o_county]
        for i, row in c2.iterrows():
            mw = row["_mwac"]
            if mw and abs(mw - o_mw) <= max(5.0, 0.10 * o_mw):
                return i
    return None

def enrich_and_union(orennia_df: pd.DataFrame, wm: dict, name_thr: float = 0.86) -> pd.DataFrame:
    """
    Returns a widened master dataframe:
      - every Orennia row, with wm_* columns filled where a WoodMac match exists
      - plus WoodMac-only solar projects appended (source = 'woodmac_only')
    """
    C = ORENNIA_COLS
    solar = wm["solar"]
    df = orennia_df.copy()
    for new in _WM_SOLAR_FIELDS.values():
        df[new] = None
    df["wm_matched"] = False
    df["source"] = "orennia"

    matched_wm_idx = set()
    for idx, row in df.iterrows():
        o_name   = norm_name(row.get(C["project_name"], ""))
        o_state  = norm_state(row.get(C["state"], ""))
        o_county = str(row.get(C["county"], "")).strip().lower()
        o_mw     = _to_float(row.get(C["capacity_mw"], ""))
        j = _match_one(o_name, o_state, o_county, o_mw, solar, name_thr)
        if j is not None:
            matched_wm_idx.add(j)
            wmrow = solar.loc[j]
            for src, dst in _WM_SOLAR_FIELDS.items():
                val = wmrow.get(src, "")
                # only FILL when Orennia is missing it; never overwrite Orennia
                if (df.at[idx, dst] in (None, "", "nan")) and str(val).strip():
                    df.at[idx, dst] = val
            df.at[idx, "wm_matched"] = True

    # WoodMac-only projects -> standalone rows
    only = solar.loc[~solar.index.isin(matched_wm_idx)].copy()
    extra = pd.DataFrame(index=only.index)
    extra[C["project_name"]] = only["Power plant name"]
    extra[C["state"]]        = only["State"]
    extra[C["county"]]       = only["County"]
    extra[C["owner"]]        = only["Direct owners"]
    extra[C["capacity_mw"]]  = only["Capacity (MWac)"]
    for src, dst in _WM_SOLAR_FIELDS.items():
        extra[dst] = only[src].values
    extra["wm_matched"] = True
    extra["source"] = "woodmac_only"

    master = pd.concat([df, extra], ignore_index=True)
    return master


# ---------------------------------------------------------------------------
# 5. OWNER-LEVEL M&A FEATURES  (Nofar is a BUYER)
# ---------------------------------------------------------------------------
def build_mna_index(wm: dict) -> dict:
    """
    Returns {normalized_owner: {features...}} combining M&A, VC and the company map.
    Search is owner/company-centric, exactly as required ('primero por empresa').
    """
    mna, vc, comp = wm["mna"], wm["vc"], wm["company"]

    acquired = {}   # owner -> list of (acquirer, status, date, value, market)
    for _, r in mna.iterrows():
        k = norm_name(r["Acquired Company"])
        if k:
            acquired.setdefault(k, []).append(dict(
                acquirer=r["Acquiring Firm"], status=r["Status"],
                date=r["Date"], value=r["Disclosed Value"],
                market=r["Acquired Company Market"], activity=r["Activity"]))
    acquirer_count = {}
    for _, r in mna.iterrows():
        k = norm_name(r["Acquiring Firm"])
        if k:
            acquirer_count[k] = acquirer_count.get(k, 0) + 1
    raised_vc = {}
    for _, r in vc.iterrows():
        k = norm_name(r["Recipient"])
        if k:
            raised_vc.setdefault(k, []).append(dict(
                investor=r["Lead Investor"], date=r["Round Date"],
                value=r["Disclosed Value of Round"]))

    # defunct / parent resolution from the big ownership map
    comp_cols = {c.lower(): c for c in comp.columns}
    defunct, parent = {}, {}
    if "company_name" in comp_cols:
        cn = comp_cols["company_name"]
        df_flag = comp_cols.get("company_is_defunct")
        for _, r in comp.iterrows():
            k = norm_name(r[cn])
            if not k:
                continue
            if df_flag and str(r[df_flag]).strip().upper() == "Y":
                defunct[k] = True
            parent.setdefault(k, r[cn])

    owners = set(acquired) | set(acquirer_count) | set(raised_vc) | set(defunct)
    index = {}
    for k in owners:
        index[k] = dict(
            was_acquired=k in acquired,
            acquired_events=acquired.get(k, []),
            in_announced_deal=any(e["status"].lower().startswith("announc")
                                  for e in acquired.get(k, [])),
            is_active_acquirer=acquirer_count.get(k, 0) >= 3,
            acquirer_deal_count=acquirer_count.get(k, 0),
            raised_vc=k in raised_vc,
            vc_events=raised_vc.get(k, []),
            is_defunct=defunct.get(k, False),
            parent_name=parent.get(k),
        )
    return index


def mna_opportunity_score(owner_name: str, mna_index: dict):
    """
    0-10 buyer's-eye score + human-readable breakdown (for the expandable UI).
    Higher = asset more likely to be acquirable on good terms.
    """
    k = norm_name(owner_name)
    f = mna_index.get(k)
    reasons = []
    if not f:
        return 0, ["no M&A/VC footprint found for this owner (per WoodMac M&A)"]

    score = 0
    if f["is_defunct"]:
        score += 10; reasons.append("owner flagged defunct — asset likely in play (per WoodMac company map)")
    if f["in_announced_deal"]:
        score += 6;  reasons.append("owner in an ANNOUNCED (pending) deal — ownership in transition (per WoodMac M&A)")
    elif f["was_acquired"]:
        score += 4
        ev = f["acquired_events"][-1]
        reasons.append(f"owner was acquired by {ev['acquirer']} ({ev['date']}) — post-deal portfolio churn (per WoodMac M&A)")
    if f["raised_vc"]:
        score -= 3;  reasons.append("owner recently raised venture capital — well-capitalized, harder to pry loose (per WoodMac VC)")
    if f["is_active_acquirer"]:
        score -= 2;  reasons.append(f"owner is an active acquirer ({f['acquirer_deal_count']} deals) — a consolidator/competitor (per WoodMac M&A)")

    score = max(0, min(10, score))
    if not reasons:
        reasons = ["owner present in M&A data but no directional signal"]
    return score, reasons


# ---------------------------------------------------------------------------
# 6. M&A SCREEN  — produces an engine-style screen DataFrame (Generator ID + Reason)
#    so it drops straight into engine.composite_score as a weighted signal.
# ---------------------------------------------------------------------------
def mna_screen(g, mna_index, owner_col="Owner", gid_col="Generator ID", min_score=4):
    """
    Build a screen df (one row per project whose owner shows an M&A opportunity).
    g : your generators dataframe (must have owner_col + gid_col).
    Returns a dataframe with [gid_col, 'Generator ID', 'Reason', 'MnA Score'].
    """
    rows = []
    for _, r in g.iterrows():
        owner = r.get(owner_col)
        if not owner:
            continue
        score, reasons = mna_opportunity_score(owner, mna_index)
        if score >= min_score:
            rows.append({
                "Generator ID": r[gid_col],
                "Reason": f"M&A signal (score {score}/10): " + reasons[0],
                "MnA Score": score,
            })
    import pandas as pd
    return pd.DataFrame(rows, columns=["Generator ID", "Reason", "MnA Score"])
