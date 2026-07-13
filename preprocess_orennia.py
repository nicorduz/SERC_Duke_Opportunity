"""
Preprocess an Orennia 'Power Generation / Power Projects' CSV export into
compact analysis tables. Used both offline and by the Streamlit app on upload.

Input : raw Orennia CSV (monthly generator-level time series, static attrs repeated)
Output: (generators_df, monthly_df)
  generators_df : one row per Generator ID with static attributes + derived metrics
  monthly_df    : Generator ID x month actual generation (past only), compact
"""
import pandas as pd
import numpy as np

STATIC_COLS = [
    "Generator ID", "Power Project Name", "State", "County",
    "Capacity (MW)", "DC Capacity (MW)", "Panel Type", "Detailed Status",
    "First Power Date", "Estimated Retirement Date",
    "Contract Offtaker", "Contract Offtaker Type",
    "Contract Price ($/MWh)", "Contract Price ($/kW-month)",
    "Contract Term Years (Year)", "Contract Termination Date",
    "Contract Capacity (MW)",
    "Queue Cycle", "Queue Date", "Queue ID",
    "Interconnection Cost Physical ($)", "Interconnection Cost System Upgrade ($)",
    "Point of Interconnection", "Connection Voltage (kV)",
    "EIA Plant ID", "EIA Generator ID", "FERC Docket ID",
    "Latitude (Degrees)", "Longitude (Degrees)",
    "Solar Irradiance GHI (W/m2)", "Capex Per Watt ($/W)", "PTC/ITC",
]

DEV_STAGE_MAP = {
    # ordered development ladder for scoring (higher = more advanced)
    "Operating": 100, "Construction Complete": 95,
    "In Construction - More Than 50% Complete": 90,
    "In Construction": 85, "In Construction - Less Than 50% Complete": 80,
    "Engineering Design - Permits Received": 75, "Engineering Design": 70,
    "Engineering Design - Permits Pending": 68, "Engineering Design - In Progress": 68,
    "IA Document Posted": 66, "Interconnection Agreement": 66,
    "SCGIA - Permits Received": 64, "SCGIA": 62, "LGIANTP-1 Given": 62,
    "Interconnection Agreement Execution - Pending": 60,
    "Phase 3 Cluster Study - Study Complete": 55,
    "Phase 3 Cluster Study - Study Complete - Permits Pending": 55,
    "Facilities Study - Permits Received": 50, "Facility Study": 48, "FS In Progress": 46,
    "Phase 2 Cluster Study - Study Complete": 44, "Phase 2 Cluster Study": 40,
    "System Impact Study": 38, "Phase 1 Cluster Study": 30,
    "2026 Cluster": 22, "2025 Cluster": 22, "2024 Cluster": 22, "2023 Cluster": 22,
    "2023 Cluster - Permits Received": 26,
    "Permits Received": 24, "Permits Pending": 18, "Permits Not Initiated": 12,
    "Active": 20, "In Progress": 20,
    "GEN REP - Permits Not Initiated": 10,
}
DISTRESS_STATUSES = {
    "Suspended", "Suspended - Permits Received", "Postponed",
    "Moved to Trans Cluster (see below)",
    "Moved to Trans Cluster (see below) - Permits Received",
}


def load_and_reduce(path_or_buffer, today=None):
    today = pd.Timestamp(today) if today else pd.Timestamp.today().normalize()
    df = pd.read_csv(path_or_buffer, low_memory=False)
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")

    # ---- static table: latest row per generator ----
    keep = [c for c in STATIC_COLS if c in df.columns]
    g = (df.sort_values("Date").groupby("Generator ID", as_index=False).tail(1))[keep].copy()

    # tech classification: Orennia leaves Panel Type empty for storage/hybrid
    name = g["Power Project Name"].fillna("").str.lower()
    is_storage_name = name.str.contains("bess|battery|storage|hybrid")
    g["Technology"] = np.where(
        g["Panel Type"].notna(), "Solar PV",
        np.where(is_storage_name, "Storage/Hybrid", "Storage/Other"))

    for c in ["First Power Date", "Contract Termination Date",
              "Estimated Retirement Date", "Queue Date"]:
        if c in g.columns:
            g[c] = pd.to_datetime(g[c], errors="coerce")

    g["Age (yrs)"] = ((today - g["First Power Date"]).dt.days / 365.25).round(1)
    g["Yrs to Contract End"] = ((g["Contract Termination Date"] - today).dt.days / 365.25).round(1)
    g["Yrs to Est Retirement"] = ((g["Estimated Retirement Date"] - today).dt.days / 365.25).round(1)
    g["Dev Stage Score"] = g["Detailed Status"].map(DEV_STAGE_MAP)
    g["Is Distress Status"] = g["Detailed Status"].isin(DISTRESS_STATUSES)
    g["Is Operating"] = g["Detailed Status"].eq("Operating")
    g["Is QF Scale"] = g["Capacity (MW)"].le(5.5)  # NC PURPA standard-offer scale
    ix = (g["Interconnection Cost Physical ($)"].fillna(0)
          + g["Interconnection Cost System Upgrade ($)"].fillna(0))
    g["IX Cost $/kW"] = np.where(
        (ix > 0) & g["Capacity (MW)"].gt(0),
        ix / (g["Capacity (MW)"] * 1000), np.nan).round(0)

    # ---- monthly actuals (past only; forecasts summarized separately) ----
    past = df[df["Date"] <= today]
    monthly = past[["Generator ID", "Date", "Generation (MWh)",
                    "Capacity Factor (Number)"]].dropna(subset=["Generation (MWh)"]).copy()

    # trailing-12m capacity factor and CF trend per generator
    m = monthly.sort_values("Date")
    last12 = m.groupby("Generator ID").tail(12)
    cf12 = last12.groupby("Generator ID")["Capacity Factor (Number)"].mean().rename("CF (12m)")
    prev12 = m.groupby("Generator ID").tail(24).groupby("Generator ID").head(12)
    cfprev = prev12.groupby("Generator ID")["Capacity Factor (Number)"].mean().rename("CF (prev 12m)")
    g = g.merge(cf12, on="Generator ID", how="left").merge(cfprev, on="Generator ID", how="left")
    g["CF Trend (pp)"] = ((g["CF (12m)"] - g["CF (prev 12m)"]) * 100).round(2)

    # forecast energy (Orennia forward rows) summarized: next-10y avg CF
    fut = df[(df["Date"] > today) & (df["Date"] <= today + pd.DateOffset(years=10))]
    fcf = fut.groupby("Generator ID")["Capacity Factor (Number)"].mean().rename("CF (fcst 10y)")
    g = g.merge(fcf, on="Generator ID", how="left")

    monthly["Date"] = monthly["Date"].dt.to_period("M").dt.to_timestamp()
    return g.reset_index(drop=True), monthly.reset_index(drop=True)


if __name__ == "__main__":
    import sys
    src = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else "data"
    import os
    os.makedirs(out, exist_ok=True)
    g, m = load_and_reduce(src)
    g.to_parquet(f"{out}/orennia_generators.parquet", index=False)
    m.to_parquet(f"{out}/orennia_monthly.parquet", index=False)
    print(f"generators: {len(g)} rows -> {out}/orennia_generators.parquet")
    print(f"monthly:    {len(m)} rows -> {out}/orennia_monthly.parquet")
