"""
engine.py — opportunity screens, cross-source joins, composite scoring,
and playbook-context assembly. Deterministic and traceable.
"""
import pandas as pd
import numpy as np

def norm_txt(s):
    return str(s).lower().strip() if pd.notna(s) else ""

# --------------------------------------------------------------- cross-source flags
def red_zone_flags(g, red_zone):
    """Match Orennia POI text against DEP Red Zone substation names."""
    if red_zone is None or g is None: return pd.Series(False, index=g.index)
    subs = [s for s in red_zone["substation"].str.lower().unique() if len(s) >= 5]
    poi = g["Point of Interconnection"].fillna("").str.lower()
    return poi.apply(lambda p: any(s in p for s in subs) if p else False)

def county_risk_tables(g, restrictions, contested):
    res_c = set(restrictions["county_clean"].str.lower()) if restrictions is not None else set()
    con_c = set(contested["county_clean"].str.lower()) if contested is not None else set()
    cty = g["County"].fillna("").str.lower()
    return cty.isin(res_c), cty.isin(con_c)

def match_duke_queue(g, dq):
    """Join Orennia Queue ID to Duke queue file queue_id (exact), fallback none."""
    if dq is None: return {}
    dqi = dq.set_index(dq["queue_id"].astype(str).str.strip())
    out = {}
    for gid, q in zip(g["Generator ID"], g["Queue ID"].astype(str).str.strip()):
        if q and q != "nan" and q in dqi.index:
            row = dqi.loc[q]
            out[gid] = row.iloc[0] if isinstance(row, pd.DataFrame) else row
    return out

# --------------------------------------------------------------- screens
def opportunity_screens(g, eia=None, dq=None, red_zone=None, restrictions=None, contested=None, warn=None):
    out = {}
    op = g[g["Is Operating"]].copy()

    qf = op[(op["Is QF Scale"]) & (op["Age (yrs)"] >= 8)].copy()
    qf["Reason"] = ("QF-scale (" + qf["Capacity (MW)"].round(1).astype(str) + " MW), age "
                    + qf["Age (yrs)"].astype(str) + "y — repowering / roll-up candidate")
    out["qf_rollup"] = qf.sort_values(["County", "Age (yrs)"], ascending=[True, False])

    cc = op[op["Yrs to Contract End"].notna() & (op["Yrs to Contract End"] <= 5)].copy()
    cc["Reason"] = np.where(cc["Yrs to Contract End"] <= 0,
                            "PPA already expired — merchant/repricing exposure",
                            "PPA ends in " + cc["Yrs to Contract End"].astype(str) + "y")
    out["contract_cliff"] = cc.sort_values("Yrs to Contract End")

    up = op[(op["CF Trend (pp)"].notna()) & (op["CF Trend (pp)"] <= -1.5)].copy()
    up["Reason"] = "CF down " + (-up["CF Trend (pp)"]).round(1).astype(str) + "pp vs prior 12m"
    vsf = op[(op["CF (12m)"].notna()) & (op["CF (fcst 10y)"].notna())
             & (op["CF (12m)"] < 0.8 * op["CF (fcst 10y)"])].copy()
    vsf["Reason"] = ("Actual CF " + (100*vsf["CF (12m)"]).round(1).astype(str)
                     + "% vs fcst " + (100*vsf["CF (fcst 10y)"]).round(1).astype(str) + "% — >20% under")
    out["underperf"] = pd.concat([up, vsf]).drop_duplicates("Generator ID").sort_values("CF Trend (pp)")

    dd = g[g["Is Distress Status"]].copy()
    dd["Reason"] = "Status: " + dd["Detailed Status"] + " — owner may sell rather than continue"
    out["dev_distress"] = dd.sort_values("Capacity (MW)", ascending=False)

    ls = g[(~g["Is Operating"]) & (g["Dev Stage Score"] >= 60)].copy()
    ls["Reason"] = "Late-stage (" + ls["Detailed Status"] + ") — de-risked, bid-ready"
    out["late_stage"] = ls.sort_values(["Dev Stage Score", "Capacity (MW)"], ascending=False)

    ib = g[g["IX Cost $/kW"].notna() & (g["IX Cost $/kW"] > 150)].copy()
    ib["Reason"] = "IX cost $" + ib["IX Cost $/kW"].astype(int).astype(str) + "/kW upgrade burden"
    out["ix_burden"] = ib.sort_values("IX Cost $/kW", ascending=False)

    rh = op[op["Yrs to Est Retirement"].notna() & (op["Yrs to Est Retirement"] <= 5)].copy()
    rh["Reason"] = "Est. retirement in " + rh["Yrs to Est Retirement"].astype(str) + "y — site/queue reuse"
    out["retirement"] = rh.sort_values("Yrs to Est Retirement")

    # NEW: red-zone constrained POI
    rz = red_zone_flags(g, red_zone)
    rzd = g[rz].copy()
    rzd["Reason"] = "POI matches DEP Red Zone constrained substation — upgrade exposure / seller leverage"
    out["red_zone"] = rzd
    g = g.assign(_red_zone=rz)

    # NEW: county risk (restrictions / contested history)
    r_flag, c_flag = county_risk_tables(g, restrictions, contested)
    crd = g[r_flag | c_flag].copy()
    crd["Reason"] = np.where(r_flag[r_flag | c_flag] & c_flag[r_flag | c_flag],
                             "County has BOTH an ordinance restriction AND contested-project history",
                             np.where(r_flag[r_flag | c_flag], "County has a recorded solar ordinance restriction",
                                      "County has contested/canceled solar project history"))
    out["county_risk"] = crd

    # NEW: withdrawn queue universe (from Duke file — standalone table, not Orennia rows)
    if dq is not None:
        wd = dq[(dq["status"].str.lower() == "withdrawn")
                & (dq["fuel_tech"].isin(["Solar", "Battery", "Energy Storage"]))].copy()
        out["withdrawn_queue"] = wd.sort_values("mw", ascending=False)

# ── non-Orennia screens ──
    if dq is not None:
        wd_all = dq[dq["status"].str.lower() == "withdrawn"]
        wids = set(wd_all["queue_id"].astype(str).str.strip())
        m1 = g[g["Queue ID"].astype(str).str.strip().isin(wids)].copy()
        m1["Reason"] = "Queue ID appears as WITHDRAWN in Duke's official queue — utility-confirmed distress"
        out["duke_withdrawn_match"] = m1
        cw = wd_all.groupby(wd_all["county"].astype(str).str.lower())["mw"].sum()
        hot = set(cw[cw >= 50].index)
        m2 = g[g["County"].fillna("").str.lower().isin(hot)].copy()
        m2["Reason"] = "County has ≥50 MW withdrawn from Duke's queue — seller-rich environment"
        out["withdrawal_cluster"] = m2
    if warn is not None and len(warn) and "energy_relevant" in warn.columns:
        wcty = set(warn[warn["energy_relevant"] == True]["county"].astype(str).str.lower().str.strip())
        m3 = g[g["County"].fillna("").str.lower().isin(wcty)].copy()
        m3["Reason"] = "Energy-relevant WARN notice in the same county — sector labor stress near the asset"
        out["warn_county"] = m3

    if eia is not None and "Entity Name" in eia.columns:
        j = op.merge(eia[["EIA Plant ID", "Entity Name"]].drop_duplicates("EIA Plant ID"),
                     on="EIA Plant ID", how="left")
        oc = (j.dropna(subset=["Entity Name"]).groupby("Entity Name")
                .agg(units=("Generator ID", "count"), mw=("Capacity (MW)", "sum"),
                     avg_age=("Age (yrs)", "mean"), counties=("County", "nunique"))
                .query("units >= 3").sort_values("mw", ascending=False).round(1).reset_index())
        out["owner_concentration"] = oc
        out["_owner_map"] = dict(zip(j["Generator ID"], j["Entity Name"]))
    return out

DEFAULT_WEIGHTS = {"dev_distress": 4, "duke_withdrawn_match": 3.5, "contract_cliff": 3,
                   "underperf": 3, "ix_burden": 2.5, "red_zone": 2.5, "qf_rollup": 2,
                   "retirement": 2, "late_stage": 1.5, "withdrawal_cluster": 1,
                   "warn_county": 0.5, "county_risk": -1}
WEIGHTS = DEFAULT_WEIGHTS  # retro-compatibilidad

def composite_score(g, screens, weights=None, threshold=0.0):
    W = {**DEFAULT_WEIGHTS, **(weights or {})}
    s = pd.Series(0.0, index=g["Generator ID"]); reasons = {}; fired = {}
    for key, w in W.items():
        d = screens.get(key)
        if d is None or d.empty or "Generator ID" not in d.columns: continue
        for gid, r in zip(d["Generator ID"], d["Reason"]):
            s[gid] = s.get(gid, 0) + w
            reasons.setdefault(gid, []).append(("⚠️ " if w < 0 else "") + r)
            fired.setdefault(gid, []).append(key)
    top = g.set_index("Generator ID").copy()
    top["Opportunity Score"] = s
    top["Why"] = top.index.map(lambda i: " | ".join(reasons.get(i, [])))
    top["_fired"] = top.index.map(lambda i: fired.get(i, []))
    top = top[top["Opportunity Score"] >= max(threshold, 1e-9)]
    return top.sort_values("Opportunity Score", ascending=False).reset_index()

def build_playbook_context(row, screens, dq, restrictions, contested):
    """Assemble the ctx dict actions.generate_playbook needs, for one row."""
    gid = row["Generator ID"]
    owner_map = screens.get("_owner_map", {})
    qmatches = getattr(build_playbook_context, "_qcache", None)
    cty = norm_txt(row.get("County"))
    ctx = {
        "owner": owner_map.get(gid),
        "in_red_zone": bool(row.get("_red_zone", False)) or (
            screens.get("red_zone") is not None and gid in set(screens["red_zone"]["Generator ID"])),
        "county_restrictions": restrictions[restrictions["county_clean"].str.lower() == cty]
            if restrictions is not None else None,
        "county_contested": contested[contested["county_clean"].str.lower() == cty]
            if contested is not None else None,
        "queue_match": None,
    }
    if dq is not None:
        q = str(row.get("Queue ID", "")).strip()
        m = dq[dq["queue_id"].astype(str).str.strip() == q] if q and q != "nan" else pd.DataFrame()
        if len(m): ctx["queue_match"] = m.iloc[0]
    return ctx
