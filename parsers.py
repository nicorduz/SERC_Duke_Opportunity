"""
parsers.py — loaders matched to the EXACT structure of Nofar's manual uploads.
Each parser is defensive: it locates the header row by signature so minor
layout shifts don't break ingestion, and returns a normalized DataFrame.
"""
import pandas as pd
import numpy as np

def _find_header(df_raw, must_contain):
    for i in range(min(10, len(df_raw))):
        row = df_raw.iloc[i].astype(str).str.strip().tolist()
        if all(any(m.lower() in str(c).lower() for c in row) for m in must_contain):
            return i
    return None

def parse_duke_cluster_queue(path_or_buf):
    """20260331_Cluster_QueueDEP.xlsx — sheet 'DEP Cluster Queue' (also handles DEC)."""
    xls = pd.ExcelFile(path_or_buf)
    sheet = next((s for s in xls.sheet_names if "Cluster Queue" in s and "internal" not in s.lower()),
                 xls.sheet_names[0])
    raw = pd.read_excel(xls, sheet, header=None)
    h = _find_header(raw, ["Queue Number", "Energy Source", "Facility County"])
    df = pd.read_excel(xls, sheet, header=h)
    df = df.dropna(how="all").dropna(subset=["Queue Number"])
    df = df.rename(columns={
        "OPCO": "utility", "Queue Number": "queue_id",
        "Queue Indicator 1": "cluster_cycle", "Operational Status": "status",
        "Complete Interconnection Request Date": "queue_date",
        "Distribution or Transmission": "dist_or_trans", "State or FERC": "jurisdiction",
        "Installed Capacity MW AC": "mw", "Energy Source Type": "fuel_tech",
        "NRIS or ERIS": "service", "Facility County": "county", "Facility State": "state",
        "Transmission Line": "transmission_line", "Substation Name": "substation",
        "Duke Estimated Startup Date": "est_startup", "Operational Date": "operational_date"})
    keep = [c for c in ["utility", "queue_id", "cluster_cycle", "status", "queue_date",
                        "dist_or_trans", "jurisdiction", "mw", "fuel_tech", "service",
                        "county", "state", "transmission_line", "substation", "est_startup"] if c in df.columns]
    df = df[keep]
    df["queue_date"] = pd.to_datetime(df["queue_date"], errors="coerce")
    df["mw"] = pd.to_numeric(df["mw"], errors="coerce")
    return df.reset_index(drop=True)

def parse_oasis_posting(path_or_buf):
    """20260609_FERC-4_5-OASIS-Posting-DEP.xlsx — sheet 'DEP' (or 'DEC').
    Contains Interconnection Customer = OWNERSHIP signal for pipeline projects."""
    xls = pd.ExcelFile(path_or_buf)
    sheet = next((s for s in xls.sheet_names if s in ("DEP", "DEC")), xls.sheet_names[0])
    raw = pd.read_excel(xls, sheet, header=None)
    h = _find_header(raw, ["Queue Number", "Interconnection Customer"])
    df = pd.read_excel(xls, sheet, header=h)
    df = df.dropna(how="all").dropna(subset=["Queue Number"])
    df = df.rename(columns={
        "OPCO": "utility", "Queue Number": "queue_id", "Queue Issued Date": "queue_date",
        "Interconnection Customer": "interconnection_customer",
        "Queue Indicator*": "cluster_cycle", "Queue Indicator": "cluster_cycle",
        "Operational Status": "status", "Installed Capacity MW AC": "mw",
        "Energy Source Type": "fuel_tech", "Facility County": "county",
        "Facility State": "state", "Transmission Line": "transmission_line",
        "Substation Name": "substation", "Duke Estimated Startup Date": "est_startup",
        "Type of Service": "service"})
    keep = [c for c in ["utility", "queue_id", "queue_date", "interconnection_customer",
                        "cluster_cycle", "status", "mw", "fuel_tech", "county", "state",
                        "transmission_line", "substation", "est_startup", "service"] if c in df.columns]
    df = df[keep]
    df["queue_date"] = pd.to_datetime(df["queue_date"], errors="coerce")
    df["mw"] = pd.to_numeric(df["mw"], errors="coerce")
    return df.reset_index(drop=True)

def parse_red_zone(path_or_buf):
    """DEP_Red_Zone_Lines_and_Subs_V3_*.xlsx — constrained transmission zones."""
    df = pd.read_excel(path_or_buf, sheet_name=0)
    df.columns = [str(c).strip() for c in df.columns]
    ren = {}
    for c in df.columns:
        cl = c.lower()
        if "line" in cl and "name" in cl: ren[c] = "line_name"
        elif cl in ("kv", "voltage"): ren[c] = "kv"
        elif "substation" in cl: ren[c] = "substation"
        elif cl == "type": ren[c] = "type"
        elif "ol" in cl: ren[c] = "line_id"
    df = df.rename(columns=ren)
    df["substation"] = df.get("substation", pd.Series(dtype=str)).astype(str).str.strip()
    df = df[df["substation"].ne("-") & df["substation"].ne("nan")]
    return df.reset_index(drop=True)

def parse_restrictions(path_or_buf, states=("NC", "SC")):
    """2025-Restrictions.csv — Sabin Center local restrictions; filter NC/SC + solar."""
    df = pd.read_csv(path_or_buf, encoding="latin1", low_memory=False)
    df = df[df["State"].isin(states)].copy()
    df = df[df["Type"].fillna("").str.contains("Solar", case=False)]
    df = df.rename(columns={"Title": "title", "Status": "status", "Year Adopted": "year_adopted",
                            "State": "state", "County": "county", "Type": "type",
                            "Content": "content", "Citations": "citations",
                            "Date of Last Event": "last_event", "Level": "level"})
    df["county_clean"] = df["county"].astype(str).str.replace(" County", "", regex=False).str.strip()
    return df.reset_index(drop=True)

def parse_contested(path_or_buf, states=("NC", "SC")):
    """2025-Contested-Projects.csv — contested/canceled projects; filter NC/SC + solar."""
    df = pd.read_csv(path_or_buf, encoding="latin1", low_memory=False)
    df = df[df["State"].isin(states)].copy()
    df = df[df["Type"].fillna("").str.contains("Solar", case=False)]
    df = df.rename(columns={"Title": "title", "Status": "status", "Litigation": "litigation",
                            "State": "state", "County": "county", "Type": "type",
                            "Capacity": "mw", "Content": "content", "Citations": "citations",
                            "Year Cancelled": "year_cancelled", "Date of Last Event": "last_event"})
    df["county_clean"] = df["county"].astype(str).str.replace(" County", "", regex=False).str.strip()
    return df.reset_index(drop=True)

ENERGY_KWS = ["solar", "energy", "power", "renewab", "electric", "epc", "utilit",
              "battery", "storage", "grid", "wind", "photovolt", "invert", "panel"]

def parse_warn_nc(path_or_buf):
    """NCwarn_summary_report_*.csv — NC Commerce export format."""
    df = pd.read_csv(path_or_buf)
    df = df.rename(columns={
        "County": "county", "Warn Number": "warn_no", "Date of Notice": "notice_date",
        "Effective Date": "effective_date", "WARN Notice: WARN Notice Name": "company",
        "WARN notice type": "notice_type", "Type of layoff or closure": "layoff_type",
        "Number affected at this location": "employees_affected", "City": "city"})
    df["state"] = "NC"
    df["county"] = df["county"].astype(str).str.replace(" County", "", regex=False)
    df["notice_date"] = pd.to_datetime(df["notice_date"], errors="coerce")
    df["energy_relevant"] = df["company"].fillna("").str.lower().apply(
        lambda s: any(k in s for k in ENERGY_KWS))
    return df.reset_index(drop=True)

def parse_warn_sc(path_or_buf):
    """warn_sc.csv — normalized from the SC DEW PDF (template columns)."""
    df = pd.read_csv(path_or_buf)
    df["state"] = "SC"
    df["notice_date"] = pd.to_datetime(df["notice_date"], errors="coerce")
    df["energy_relevant"] = df["company"].fillna("").str.lower().apply(
        lambda s: any(k in s for k in ENERGY_KWS))
    return df.reset_index(drop=True)

PARSERS = {
    "duke_queue": parse_duke_cluster_queue,
    "duke_oasis": parse_oasis_posting,
    "red_zone": parse_red_zone,
    "restrictions": parse_restrictions,
    "contested": parse_contested,
    "warn_nc": parse_warn_nc,
    "warn_sc": parse_warn_sc,
}
