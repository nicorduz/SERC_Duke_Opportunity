"""
scope.py — SERC-wide scope configuration.

The tool started life scoped to Duke Carolinas (DEC + DEP) in NC/SC. This module
widens the base universe to ALL of SERC / Non-ISO while letting the NC/SC-only
data layers (Duke queue, OASIS, Red Zone) degrade gracefully: those signals only
apply where we actually have the data, everything else (Orennia attributes,
geography-based signals, distress, thermal/data-center proximity) works region-wide.

Design principle: never *drop* a project for lack of a NC/SC-only artifact —
only *skip the NC/SC-only signal* for it.
"""
from __future__ import annotations
import pandas as pd

# Balancing-authority codes present in the Non-ISO Southeast, mapped to the
# operating utility and whether we currently hold granular OASIS/queue detail.
BA_UTILITY = {
    "SOCO": "Southern Company (GA/AL/MS Power)",
    "FPL":  "Florida Power & Light (NextEra)",
    "CPLE": "Duke Energy Progress East",
    "CPLW": "Duke Energy Progress West",
    "DUK":  "Duke Energy Carolinas",
    "FPC":  "Duke Energy Florida",
    "TVA":  "Tennessee Valley Authority",
    "SC":   "Santee Cooper (SC Public Service Authority)",
    "SCEG": "Dominion Energy South Carolina",
    "TEC":  "Tampa Electric (TECO)",
    "JEA":  "Jacksonville (JEA)",
    "SEPA": "Southeastern Power Administration",
    "FMPP": "Florida Municipal Power Pool",
    "SEC":  "Seminole Electric Cooperative",
}

# BAs for which we currently ingest granular queue/OASIS/Red-Zone detail.
OASIS_DETAIL_BAS = {"DUK", "CPLE", "CPLW", "FPC"}   # Duke family only, for now

# Renewable technologies we treat as acquisition targets vs. thermal we treat as
# retirement-proximity context. Adjust as your Orennia export's vocabulary evolves.
# Orennia's EXACT vocabulary in the current export.
TARGET_TYPES  = {"Solar", "Storage", "Wind"}
THERMAL_TYPES = {"Coal", "Natural Gas"}

SERC_STATES = ["NC", "SC", "GA", "FL", "AL", "MS", "TN", "VA", "KY"]


def apply_scope(g: pd.DataFrame, *, iso="Non-ISO", states=None, bas=None,
                duke_only=False) -> pd.DataFrame:
    """
    Filter the generators table to the desired universe.
      iso       : keep only this ISO value (default 'Non-ISO' == SERC vertical utilities)
      states    : optional list of state codes to keep
      bas       : optional list of Balancing Authority codes to keep
      duke_only : convenience flag == bas={DUK,CPLE,CPLW,FPC}
    Missing columns are tolerated (older exports); the relevant filter is simply skipped.
    """
    out = g.copy()
    if iso and "ISO" in out.columns:
        out = out[out["ISO"].astype(str).str.strip() == iso]
    if duke_only:
        bas = ["DUK", "CPLE", "CPLW", "FPC"]
    if bas and "Balancing Authority Code" in out.columns:
        out = out[out["Balancing Authority Code"].isin(bas)]
    if states and "State" in out.columns:
        out = out[out["State"].isin(states)]
    return out.reset_index(drop=True)


def has_oasis_detail(row) -> bool:
    """True if this project's BA is one we hold granular Duke queue/OASIS data for."""
    return str(row.get("Balancing Authority Code", "")).strip() in OASIS_DETAIL_BAS


def region_label(g: pd.DataFrame) -> str:
    """Human summary of the loaded universe for the UI header."""
    n = len(g)
    st = ", ".join(sorted(g["State"].dropna().unique())) if "State" in g else "?"
    ba = g["Balancing Authority Code"].nunique() if "Balancing Authority Code" in g else 0
    return f"{n} projects · {st} · {ba} balancing authorities"


# ─────────────────────────────────────────────────────── CourtListener scoping
# Federal BANKRUPTCY court ids covering the SERC / non-ISO Southeast. Used to keep
# generic (non-entity) case searches inside our footprint — without this a query for
# "solar" returns dockets from California, Texas and overseas subsidiaries.
SERC_BANKRUPTCY_COURTS = [
    "nceb", "ncmb", "ncwb",            # North Carolina
    "scb",                             # South Carolina
    "ganb", "gamb", "gasb",            # Georgia
    "flnb", "flmb", "flsb",            # Florida
    "alnb", "almb", "alsb",            # Alabama
    "msnb", "mssb",                    # Mississippi
    "tneb", "tnmb", "tnwb",            # Tennessee
    "vaeb", "vawb",                    # Virginia
    "kyeb", "kywb",                    # Kentucky
]
# Federal DISTRICT courts in the same states (lien / foreclosure / contract suits).
SERC_DISTRICT_COURTS = [
    "nced", "ncmd", "ncwd", "scd", "gand", "gamd", "gasd",
    "flnd", "flmd", "flsd", "alnd", "almd", "alsd",
    "msnd", "mssd", "tned", "tnmd", "tnwd", "vaed", "vawd", "kyed", "kywd",
]
SERC_COURTS = SERC_BANKRUPTCY_COURTS + SERC_DISTRICT_COURTS

# Geographic terms used to keep free-text news searches inside the footprint.
SERC_GEO_TERMS = [
    "North Carolina", "South Carolina", "Georgia", "Florida", "Alabama",
    "Mississippi", "Tennessee", "Carolinas", "Southeast",
    "Duke Energy", "Southern Company", "Georgia Power", "Alabama Power",
    "Florida Power", "Santee Cooper", "Dominion Energy South Carolina", "TVA",
]


def in_serc_court(court_id) -> bool:
    return str(court_id or "").strip().lower() in set(SERC_COURTS)
