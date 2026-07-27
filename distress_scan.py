"""distress_scan.py — company-level distress signals + ownership scaffold + actions."""
import pandas as pd, numpy as np, os
from difflib import SequenceMatcher

def _sim(a, b): return SequenceMatcher(None, str(a).lower(), str(b).lower()).ratio()

def build_ownership(g, eia):
    rows = []
    if eia is not None and "Entity Name" in eia.columns:
        eia_ops = eia.dropna(subset=["Entity Name"]).copy()
        by_pid = eia_ops.dropna(subset=["EIA Plant ID"]).set_index("EIA Plant ID")["Entity Name"].to_dict()
        names = eia_ops[["Plant Name", "Entity Name"]].dropna().values.tolist() if "Plant Name" in eia_ops else []
        for _, r in g.iterrows():
            owner, conf, src = None, 0.0, ""
            pid = r.get("EIA Plant ID")
            if pd.notna(pid) and pid in by_pid:
                owner, conf, src = by_pid[pid], 1.0, "EIA plant_id"
            else:
                best = max(names, key=lambda x: _sim(r["Power Project Name"], x[0]), default=None)
                if best and _sim(r["Power Project Name"], best[0]) >= 0.86:
                    owner, conf, src = best[1], round(_sim(r["Power Project Name"], best[0]), 2), "EIA name-fuzzy"
            rows.append({"project_id": r["Generator ID"], "project": r["Power Project Name"],
                         "current_owner": owner, "owner_match_confidence": conf, "ownership_source": src,
                         "sold_last_5yr": np.nan, "prior_owner": None, "acquired_date": None})
    own = pd.DataFrame(rows)
    if own.empty:
        return own
    exp = g.set_index("Generator ID")["Yrs to Contract End"]
    own["never_resold_ppa_expiring"] = own["project_id"].map(
        lambda i: bool(pd.notna(exp.get(i)) and exp.get(i) <= 5))
    return own

SIG_W = {"bankruptcy": 3, "queue_withdrawal": 2, "layoff": 2, "ppa_cancelled": 3, "underperformance": 1}

def build_distress(g, scr, dq, warn, media=None, courtlistener=None):
    sig = []
    if dq is not None:
        wd = dq[(dq["status"].str.lower() == "withdrawn") & (dq["mw"] > 30)]
        for _, r in wd.iterrows():
            sig.append({"company": r.get("queue_id"), "signal_type": "queue_withdrawal",
                        "signal_date": r.get("queue_date"), "source": "Duke queue",
                        "severity": 2, "county": r.get("county"), "mw": r.get("mw"), "url": ""})
    for _, r in scr.get("underperf", pd.DataFrame()).iterrows():
        sig.append({"company": r["Power Project Name"], "signal_type": "underperformance",
                    "signal_date": None, "source": "Orennia CF", "severity": 1,
                    "county": r.get("County"), "mw": r.get("Capacity (MW)"), "url": ""})
    if warn is not None and "energy_relevant" in warn.columns:
        for _, r in warn[warn["energy_relevant"] == True].iterrows():
            sig.append({"company": r.get("company"), "signal_type": "layoff",
                        "signal_date": r.get("notice_date"), "source": f"WARN {r.get('state')}",
                        "severity": 2, "county": r.get("county"), "mw": np.nan, "url": r.get("link", "")})
    KW = {"ppa_cancelled": ["cancel", "terminat", "write-off", "write off", "scrapp"],
          "bankruptcy": ["bankrupt", "chapter 11", "chapter 7", "receivership"]}
    for feed, fsrc in [(media, "media"), (courtlistener, "courtlistener")]:
        if feed is None: continue
        for _, r in feed.iterrows():
            txt = f"{r.get('title','')} {r.get('case','')}".lower()
            for st_, kws in KW.items():
                if any(k in txt for k in kws):
                    sig.append({"company": r.get("title", r.get("case", ""))[:80], "signal_type": st_,
                                "signal_date": r.get("published", r.get("filed")), "source": fsrc,
                                "severity": 3, "county": "", "mw": np.nan, "url": r.get("link", "")})
    df = pd.DataFrame(sig)
    if df.empty: return df, pd.DataFrame()
    df["signal_date"] = pd.to_datetime(df["signal_date"], errors="coerce")
    df = df.drop_duplicates(subset=["company", "signal_type"])
    today = pd.Timestamp.today()
    df["age_days"] = (today - df["signal_date"]).dt.days.fillna(180)
    df["decay"] = np.exp(-df["age_days"] / 365.0)
    df["wscore"] = df["signal_type"].map(SIG_W).fillna(1) * df["severity"] * df["decay"]
    comp = (df.groupby("company").agg(distress_score=("wscore", "sum"),
            signals=("signal_type", lambda s: ", ".join(sorted(set(s)))),
            n=("signal_type", "count")).sort_values("distress_score", ascending=False).reset_index())
    return df, comp

def recommend_action(fired, own_row, distress_types):
    dt = set(distress_types or [])
    if "bankruptcy" in dt: return "Portfolio acquisition opportunity"
    if own_row is not None and own_row.get("never_resold_ppa_expiring"): return "Buy-and-repower target (new QF/PPA)"
    if dt & {"layoff", "ppa_cancelled"}: return "Bilateral approach — capital / development-services agreement"
    if "withdrawal_cluster" in fired: return "Risk flag — investigate why peers withdrew"
    if "duke_withdrawn_match" in fired: return "Distressed position — approach owner directly"
    return "Monitor"
