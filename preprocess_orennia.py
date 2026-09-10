"""
preprocess_orennia.py — Orennia export -> compact analysis tables.

MERGES ORENNIA'S TWO EXPORTS INTO ONE TABLE
-------------------------------------------
Orennia splits the data across two downloads that must be combined:

  A) "Power Projects"            -> one row per project (the MASTER list).
     Only file with: Balancing Authority Code, Estimated Retirement Date,
     Interconnection Service Type, Repower Date, Wind Turbine Capacity.
  B) "Power Generation / Power Projects" -> monthly rows per project.
     Only file with: Date, Generation (MWh), Capacity Factor, outage rates,
     Equipment Manufacturer, Equipment Model, Panel Type, Native American Lands,
     Retired Coal Facilities Energy Communities, Behind the Meter,
     Contract Offtaker Type / Price Type / Delivery Location / Execution Date.

JOIN KEY: 'Generator ID' (or:generator:NNNNN) — unique in A, 100% of B's
projects exist in A. Verified: the two files have ZERO conflicting values on
their shared columns, so the merge is lossless.

A is the base (superset). B contributes its exclusive attributes plus history.
Projects present in A but absent from B (queue-stage, most thermal) simply have
no generation history — that is expected, not an error.

Either file can be passed alone: with only A you get the attributes and no
history; with only B you get history and lose A's exclusive columns.

Missing columns never crash the script: every optional field is guarded, so an
export without 'Panel Type', 'Solar Irradiance GHI' or the split interconnection
cost columns still processes cleanly.

ALSO PREPROCESSES DATA CENTERS (same coordinate fix, its own parquet).

Run from VS Code (Play button) or terminal:
    python3 preprocess_orennia.py                       # uses the default paths below
    python3 preprocess_orennia.py <power_csv> <outdir>  # explicit
    python3 preprocess_orennia.py <power_csv> <outdir> <datacenters_csv>
"""
import os
import sys
import pandas as pd
import numpy as np

# ─────────────────────────────────────────────────────────── default paths
# Files are looked up NEXT TO THIS SCRIPT, so the VS Code Play button just works
# as long as the CSVs sit in the same folder as preprocess_orennia.py.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECTS_CSV_DEFAULT   = os.path.join(BASE_DIR, "2_1_Power Projects-2026-09-10T12-51-56.csv")
GENERATION_CSV_DEFAULT = os.path.join(BASE_DIR, "2_Power Generation_ Power Projects-2026-09-10T14-48-12.csv")
DC_CSV_DEFAULT         = os.path.join(BASE_DIR, "data_centers.csv")
OUT_DIR_DEFAULT        = os.path.join(BASE_DIR, "data")

# If a filename has changed, you can also drop the CSVs next to this script and
# let these glob patterns find them automatically.
PROJECTS_GLOB   = "*Power Projects*.csv"
GENERATION_GLOB = "*Power Generation*.csv"

STATIC_COLS = [
    "Generator ID", "Generator Name", "Power Project Name", "State", "County",
    "Capacity (MW)", "DC Capacity (MW)", "Panel Type",
    "Power Project Status", "Detailed Status",
    "First Power Date", "Reported First Power Date",
    "Estimated Retirement Date", "Reported Retirement Date",
    "Contract Offtaker", "Contract Offtaker Type", "Contract Type",
    "Contract Price ($/MWh)", "Contract Price ($/kW-month)",
    "Contract Term Years (Year)", "Contract Termination Date",
    "Contract Capacity (MW)",
    "Queue Cycle", "Queue Date", "Queue ID",
    "Interconnection Cost Physical ($)", "Interconnection Cost System Upgrade ($)",
    "Interconnection Cost Total ($)", "Interconnection Service Type",
    "Point of Interconnection", "Connection Voltage (kV)", "Transmission Owner",
    "EIA Plant ID", "EIA Generator ID", "EIA Unit Code", "FERC Docket ID",
    "Latitude (Degrees)", "Longitude (Degrees)",
    "Solar Irradiance GHI (W/m2)", "Capex Per Watt ($/W)", "PTC/ITC",
    # SERC scope + distress linking
    "Owner", "Parent Company", "Parent Company 2",
    "Balancing Authority Code", "ISO", "Power Project Type",
    # extra attributes present in the new export
    "Chance of Success (Percentage)", "IRR (Percentage)", "Lifetime Capacity Factor",
    "EPC", "Battery Type", "Storage Duration (Hours)", "Storage Energy Rating (MWh)",
    "Number of Turbines (Number)", "Low Income Communities", "Repowered",
    "Repower Date", "Wind Turbine Capacity (kW)",
    # --- exclusive to the "Power Generation" export (equipment / siting / contract) ---
    "Equipment Manufacturer", "Equipment Model", "Panel Type",
    "Native American Lands", "Retired Coal Facilities Energy Communities",
    "Behind the Meter", "CCUS Status", "CCUS ID",
    "Contract Offtaker Type", "Contract Price Type",
    "Contract Delivery Location", "Contract Execution Date",
]

# Columns that exist ONLY in the generation export and are pure attributes
# (not time series). Used to enrich the master list.
GEN_ONLY_ATTRS = [
    "Equipment Manufacturer", "Equipment Model", "Panel Type",
    "Native American Lands", "Retired Coal Facilities Energy Communities",
    "Behind the Meter", "CCUS Status",
    "Contract Offtaker Type", "Contract Price Type",
    "Contract Delivery Location", "Contract Execution Date",
]

TIMESERIES_COLS = [
    "Date", "Generator ID", "Generation (MWh)", "Capacity Factor (Number)",
    "Partial Outage Rate (Percentage)", "Total Outage Rate (Percentage)",
    "Full Outage Rate (Percentage)",
]

DEV_STAGE_MAP = {
    "Operating": 100, "Construction Complete": 95,
    "In Construction - More Than 50% Complete": 90,
    "In Construction": 85, "In Construction - Less Than 50% Complete": 80,
    "Engineering Design - Permits Received": 75, "Engineering Design": 70,
    "Engineering Design - Permits Pending": 68, "Engineering Design - In Progress": 68,
    "IA Document Posted": 66, "Interconnection Agreement": 66, "IA Executed": 66,
    "SCGIA - Permits Received": 64, "SCGIA": 62, "LGIANTP-1 Given": 62,
    "Interconnection Agreement Execution - Pending": 60,
    "Phase 3 Cluster Study - Study Complete": 55,
    "Phase 3 Cluster Study - Study Complete - Permits Pending": 55,
    "Facilities Study - Permits Received": 50, "Facility Study": 48, "FS In Progress": 46,
    "Phase 2 Cluster Study - Study Complete": 44, "Phase 2 Cluster Study": 40,
    "System Impact Study": 38, "Phase 1 Cluster Study": 30,
    "Studies Undergoing": 35, "Pre-Study": 20,
    "2026 Cluster": 22, "2025 Cluster": 22, "2024 Cluster": 22, "2023 Cluster": 22,
    "2023 Cluster - Permits Received": 26,
    "Permits Received": 24, "Permits Pending": 18, "Permits Not Initiated": 12,
    "Active": 20, "In Progress": 20,
    "GEN REP - Permits Not Initiated": 10,
}
DISTRESS_STATUSES = {
    "Suspended", "Suspended - Permits Received", "Postponed", "Inactive",
    "Moved to Trans Cluster (see below)",
    "Moved to Trans Cluster (see below) - Permits Received",
}

# Orennia's exact vocabulary for the thermal plants you append to the same CSV.
THERMAL_TYPES = {"Coal", "Natural Gas"}


# ─────────────────────────────────────────────────────────── helpers
def fix_coord(v):
    """'27.580.883' -> 27.580883 ; '-84.670.698' -> -84.670698 ; clean values pass through."""
    if pd.isna(v):
        return np.nan
    t = str(v).strip()
    if t == "" or t.lower() == "nan":
        return np.nan
    neg = t.startswith("-")
    body = t.lstrip("-")
    if body.count(".") <= 1:                        # already a normal decimal
        try:
            x = float(body)
        except ValueError:
            return np.nan
    else:                                           # locale thousands separators
        digits = body.replace(".", "")
        try:
            x = int(digits) / (10 ** (len(digits) - 2))
        except ValueError:
            return np.nan
    return -x if neg else x


def _num(s):
    return pd.to_numeric(s, errors="coerce")


def to_dt(s):
    """
    Robust date parser for MIXED formats in the same column.

    Why this exists: Orennia exports ISO dates ('2057-01-01'), but when you append
    thermal plants by hand from Excel the dates often come out as '1/01/29'.
    Plain pd.to_datetime infers ONE format from the column and silently turns every
    non-matching value into NaT — which would kill the thermal-retirement signal
    with no error message at all. This parses element by element instead.
    """
    s = pd.Series(s)
    try:                                     # pandas >= 2.0
        out = pd.to_datetime(s, errors="coerce", format="mixed", dayfirst=True)
    except (ValueError, TypeError):
        out = pd.to_datetime(s, errors="coerce", dayfirst=True)
    miss = out.isna() & s.notna() & (s.astype(str).str.strip() != "")
    if miss.any():                           # per-element rescue pass
        out.loc[miss] = s[miss].map(
            lambda v: pd.to_datetime(v, errors="coerce", dayfirst=True))
    return out


def _col(df, name, default=np.nan):
    """Return the column if present, else a constant series of the right length."""
    return df[name] if name in df.columns else pd.Series(default, index=df.index)


# ─────────────────────────────────────────────────────────── readers
def _read(path):
    df = pd.read_csv(path, low_memory=False)
    df.columns = [str(c).replace("\ufeff", "").strip() for c in df.columns]
    # the generation export ships 'Generator ID' twice -> pandas makes 'Generator ID.1'
    dupes = [c for c in df.columns if c.endswith(".1") and c[:-2] in df.columns]
    return df.drop(columns=dupes)


def merge_exports(projects_csv=None, generation_csv=None):
    """
    Combine Orennia's two exports into (master_attributes, monthly_timeseries).
    Either argument may be None. Join key: 'Generator ID'.
    """
    A = _read(projects_csv) if projects_csv else None        # master project list
    B = _read(generation_csv) if generation_csv else None    # monthly generation

    if A is None and B is None:
        raise ValueError("Debes pasar al menos uno de los dos CSV de Orennia.")

    # ---- monthly time series (from B) ----
    if B is not None and "Date" in B.columns:
        ts_cols = [c for c in TIMESERIES_COLS if c in B.columns]
        monthly = B[ts_cols].copy()
        monthly["Date"] = to_dt(monthly["Date"])
        monthly = monthly.dropna(subset=["Date"])
        # drop outage columns that are entirely empty in this export
        for c in ["Partial Outage Rate (Percentage)", "Total Outage Rate (Percentage)",
                  "Full Outage Rate (Percentage)"]:
            if c in monthly.columns and monthly[c].notna().sum() == 0:
                monthly = monthly.drop(columns=[c])
    else:
        monthly = pd.DataFrame(columns=["Generator ID", "Date",
                                        "Generation (MWh)", "Capacity Factor (Number)"])

    # ---- static attributes from each file ----
    def static_of(df):
        if df is None:
            return None
        # dict.fromkeys keeps order and guards against a name listed twice
        cols = list(dict.fromkeys(c for c in STATIC_COLS if c in df.columns))
        if "Date" in df.columns:                       # collapse the time series
            out = df.sort_values("Date").drop_duplicates("Generator ID", keep="last")
        else:
            out = df.drop_duplicates("Generator ID", keep="last")
        return out[cols].copy()

    sA, sB = static_of(A), static_of(B)

    if sA is not None and sB is not None:
        # A is the master (superset). Add B's exclusive attributes, then use B to
        # fill any gap in shared columns (verified: no conflicting values).
        add = ["Generator ID"] + [c for c in sB.columns
                                  if c not in sA.columns or c in GEN_ONLY_ATTRS]
        add = list(dict.fromkeys(add))
        g = sA.merge(sB[add], on="Generator ID", how="left", suffixes=("", "_gen"))
        for c in [c for c in sB.columns if c != "Generator ID" and c in sA.columns
                  and c not in GEN_ONLY_ATTRS]:
            filler = sB.set_index("Generator ID")[c]
            g[c] = g[c].fillna(g["Generator ID"].map(filler))
        g = g.drop(columns=[c for c in g.columns if c.endswith("_gen")])
    else:
        g = sA if sA is not None else sB

    g = g.loc[:, ~g.columns.duplicated()]
    return g.reset_index(drop=True), monthly.reset_index(drop=True)


# ─────────────────────────────────────────────────────────── main loader
def load_and_reduce(projects_csv=None, generation_csv=None, today=None):
    """
    Build the analysis table. Accepts either export, or both (recommended).
    Back-compatible: load_and_reduce(single_csv) still works — the file is
    routed by whether it contains a 'Date' column.
    """
    today = pd.Timestamp(today) if today else pd.Timestamp.today().normalize()

    # back-compat: a single path was passed
    if generation_csv is None and projects_csv is not None:
        probe = pd.read_csv(projects_csv, nrows=1)
        probe.columns = [str(c).replace("\ufeff", "").strip() for c in probe.columns]
        if "Date" in probe.columns:
            projects_csv, generation_csv = None, projects_csv

    g, monthly = merge_exports(projects_csv, generation_csv)

    # ---- coordinates ----
    for c in ["Latitude (Degrees)", "Longitude (Degrees)"]:
        if c in g.columns:
            g[c] = g[c].map(fix_coord)

    # ---- numerics ----
    for c in ["Capacity (MW)", "DC Capacity (MW)", "Contract Price ($/MWh)",
              "Contract Price ($/kW-month)", "Contract Capacity (MW)",
              "Capex Per Watt ($/W)", "Connection Voltage (kV)",
              "Chance of Success (Percentage)", "IRR (Percentage)",
              "Lifetime Capacity Factor", "Storage Duration (Hours)",
              "Storage Energy Rating (MWh)", "Interconnection Cost Total ($)",
              "Number of Turbines (Number)", "Wind Turbine Capacity (kW)"]:
        if c in g.columns:
            g[c] = _num(g[c])

    # ---- technology ----
    ppt = _col(g, "Power Project Type")
    name = _col(g, "Power Project Name", "").fillna("").astype(str).str.lower()
    is_storage_name = name.str.contains("bess|battery|storage|hybrid")
    if "Panel Type" in g.columns and g["Panel Type"].notna().any():
        g["Technology"] = np.where(
            g["Panel Type"].notna(), "Solar PV",
            np.where(is_storage_name, "Storage/Hybrid",
                     ppt.fillna("Unknown").astype(str)))
    else:
        g["Technology"] = ppt.fillna(
            pd.Series(np.where(is_storage_name, "Storage/Hybrid", "Unknown"), index=g.index))
    g["Is Thermal"] = ppt.isin(THERMAL_TYPES)

    # ---- dates ----
    for c in ["First Power Date", "Reported First Power Date",
              "Contract Termination Date", "Estimated Retirement Date",
              "Reported Retirement Date", "Queue Date", "Repower Date",
              "Contract Execution Date"]:
        if c in g.columns:
            g[c] = to_dt(g[c])

    fpd = to_dt(_col(g, "First Power Date"))
    if fpd.isna().all():
        fpd = to_dt(_col(g, "Reported First Power Date"))
    retire = to_dt(_col(g, "Estimated Retirement Date"))
    retire = retire.fillna(to_dt(_col(g, "Reported Retirement Date")))

    g["Age (yrs)"] = ((today - fpd).dt.days / 365.25).round(1)
    g["Yrs to Contract End"] = (
        (to_dt(_col(g, "Contract Termination Date")) - today).dt.days / 365.25).round(1)
    g["Yrs to Est Retirement"] = ((retire - today).dt.days / 365.25).round(1)
    g["Retirement Year"] = retire.dt.year

    # ---- status flags ----
    status = _col(g, "Detailed Status")
    if status.isna().all():
        status = _col(g, "Power Project Status")
        g["Detailed Status"] = status
    g["Dev Stage Score"] = status.map(DEV_STAGE_MAP)
    g["Is Distress Status"] = status.isin(DISTRESS_STATUSES)
    g["Is Operating"] = (status.eq("Operating")
                         | _col(g, "Power Project Status").eq("Operating"))
    g["Is QF Scale"] = _num(_col(g, "Capacity (MW)")).le(5.5)

    # ---- interconnection cost ($/kW) ----
    if "Interconnection Cost Total ($)" in g.columns:
        ix = _num(g["Interconnection Cost Total ($)"]).fillna(0)
    else:
        ix = (_num(_col(g, "Interconnection Cost Physical ($)")).fillna(0)
              + _num(_col(g, "Interconnection Cost System Upgrade ($)")).fillna(0))
    mw = _num(_col(g, "Capacity (MW)"))
    g["IX Cost $/kW"] = np.where((ix > 0) & mw.gt(0), ix / (mw * 1000), np.nan).round(0)

    # ---- CF metrics from the monthly history ----
    if len(monthly) and "Capacity Factor (Number)" in monthly.columns:
        monthly["Capacity Factor (Number)"] = _num(monthly["Capacity Factor (Number)"])
        monthly["Generation (MWh)"] = _num(_col(monthly, "Generation (MWh)"))
        past = monthly[monthly["Date"] <= today].sort_values("Date")
        cf12 = (past.groupby("Generator ID").tail(12)
                    .groupby("Generator ID")["Capacity Factor (Number)"]
                    .mean().rename("CF (12m)"))
        cfprev = (past.groupby("Generator ID").tail(24).groupby("Generator ID").head(12)
                      .groupby("Generator ID")["Capacity Factor (Number)"]
                      .mean().rename("CF (prev 12m)"))
        g = g.merge(cf12, on="Generator ID", how="left") \
             .merge(cfprev, on="Generator ID", how="left")
        g["CF Trend (pp)"] = ((g["CF (12m)"] - g["CF (prev 12m)"]) * 100).round(2)
        fut = monthly[(monthly["Date"] > today)
                      & (monthly["Date"] <= today + pd.DateOffset(years=10))]
        fcf = (fut.groupby("Generator ID")["Capacity Factor (Number)"]
                  .mean().rename("CF (fcst 10y)"))
        g = g.merge(fcf, on="Generator ID", how="left")
        g["Has Generation History"] = g["Generator ID"].isin(set(past["Generator ID"]))
        monthly["Date"] = monthly["Date"].dt.to_period("M").dt.to_timestamp()
    else:
        g["CF (12m)"] = _num(_col(g, "Lifetime Capacity Factor"))
        g["CF (prev 12m)"] = np.nan
        g["CF Trend (pp)"] = np.nan
        g["CF (fcst 10y)"] = np.nan
        g["Has Generation History"] = False

    return g.reset_index(drop=True), monthly.reset_index(drop=True)


# ─────────────────────────────────────────────────────────── data centers
def load_data_centers(path_or_buffer):
    dc = pd.read_csv(path_or_buffer, low_memory=False)
    for c in ["Latitude (Degrees)", "Longitude (Degrees)"]:
        if c in dc.columns:
            dc[c] = dc[c].map(fix_coord)
    for c in ["Power Capacity (MW)", "Square Footage (Sq Ft)",
              "Chance of Success (Percentage)", "Transmission Risk (Percentage)"]:
        if c in dc.columns:
            dc[c] = _num(dc[c])
    for c in ["Construction Date", "First Power Date"]:
        if c in dc.columns:
            dc[c] = to_dt(dc[c])
    return dc.reset_index(drop=True)


# ─────────────────────────────────────────────────────────── CLI
def _autofind(pattern, explicit):
    """Use the explicit path if it exists, else glob next to this script."""
    import glob
    if explicit and os.path.exists(explicit):
        return explicit
    hits = sorted(glob.glob(os.path.join(BASE_DIR, pattern)))
    # never let the generation export match the projects pattern
    if pattern == PROJECTS_GLOB:
        hits = [h for h in hits if "Power Generation" not in os.path.basename(h)]
    return hits[-1] if hits else None


if __name__ == "__main__":
    args = sys.argv[1:]
    projects_csv   = args[0] if len(args) > 0 else None
    generation_csv = args[1] if len(args) > 1 else None
    out            = args[2] if len(args) > 2 else OUT_DIR_DEFAULT
    dc_src         = args[3] if len(args) > 3 else DC_CSV_DEFAULT

    projects_csv   = _autofind(PROJECTS_GLOB,   projects_csv   or PROJECTS_CSV_DEFAULT)
    generation_csv = _autofind(GENERATION_GLOB, generation_csv or GENERATION_CSV_DEFAULT)
    os.makedirs(out, exist_ok=True)

    print("Archivos de entrada:")
    print(f"  proyectos : {projects_csv or 'NO ENCONTRADO'}")
    print(f"  generacion: {generation_csv or 'NO ENCONTRADO'}")
    if not projects_csv and not generation_csv:
        sys.exit("ERROR: no encontré ningún CSV de Orennia junto a este script.\n"
                 "Pon los dos CSV en esta carpeta, o pásalos como argumentos:\n"
                 "  python3 preprocess_orennia.py <proyectos.csv> <generacion.csv>")

    g, m = load_and_reduce(projects_csv, generation_csv)
    g.to_parquet(f"{out}/orennia_generators.parquet", index=False)
    m.to_parquet(f"{out}/orennia_monthly.parquet", index=False)

    print(f"\ngenerators: {len(g):>7} filas x {len(g.columns)} columnas "
          f"-> {out}/orennia_generators.parquet")
    print(f"monthly:    {len(m):>7} filas -> {out}/orennia_monthly.parquet")
    if len(m):
        print(f"   histórico: {m['Date'].min():%Y-%m} a {m['Date'].max():%Y-%m} "
              f"({int(g['Has Generation History'].sum())} proyectos con historia)")
    if "ISO" in g.columns:
        print("   Non-ISO  :", int((g["ISO"] == "Non-ISO").sum()))
    if "Power Project Type" in g.columns:
        print("   Tipos    :", g["Power Project Type"].value_counts().to_dict())
    if "Owner" in g.columns:
        print("   Con Owner:", int(g["Owner"].notna().sum()), "/", len(g))
    if "Is Thermal" in g.columns:
        print("   Térmicas :", int(g["Is Thermal"].sum()),
              "| con fecha de retiro:",
              int(g.loc[g["Is Thermal"], "Retirement Year"].notna().sum()))
    for c in ["Equipment Manufacturer", "Panel Type", "Native American Lands",
              "PTC/ITC", "Retired Coal Facilities Energy Communities"]:
        if c in g.columns:
            print(f"   {c:42s} {100*g[c].notna().mean():5.1f}% lleno")

    if os.path.exists(dc_src):
        dc = load_data_centers(dc_src)
        dc.to_parquet(f"{out}/data_centers.parquet", index=False)
        print(f"data ctrs:  {len(dc):>7} filas -> {out}/data_centers.parquet")
    else:
        print(f"(data centers omitidos: no existe {dc_src})")

    # column dictionary for the dashboard
    pd.DataFrame({"column": g.columns,
                  "dtype": [str(t) for t in g.dtypes],
                  "fill_pct": [round(100 * g[c].notna().mean(), 1) for c in g.columns]}) \
      .to_csv(f"{out}/column_dictionary.csv", index=False)
    print(f"diccionario de columnas -> {out}/column_dictionary.csv")
