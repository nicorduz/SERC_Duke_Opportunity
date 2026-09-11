"""
geo_signals.py — geography-based opportunity signals (offline, no external API).

Two new signals, both returned in the SAME shape as engine.opportunity_screens
(a DataFrame with 'Generator ID' + 'Reason') so composite_score picks them up via
a weight key, PLUS richer detail frames for the Targets view and map layers.

  1. thermal_retirement_proximity : a renewable (Solar/BESS/Wind) project within
     R km of one or more thermal plants (Coal/Gas) retiring on/after year Y.
     Thesis: the retiring plant frees POI headroom, PPA demand, and grid capacity.
  2. datacenter_proximity : a project within R km of a data center, weighted by the
     data center's MW. Thesis: nearby large load = a potential offtaker.

Also provides circle_polygon(): the lat/lon ring to draw a radius on the map.

Distances use a vectorized haversine (no scikit-learn dependency needed).
"""
from __future__ import annotations
import numpy as np
import pandas as pd

EARTH_KM = 6371.0088


# ------------------------------------------------------------------ core geometry
def _haversine_matrix(lat1, lon1, lat2, lon2):
    """Pairwise great-circle distance (km). Inputs are 1-D arrays; returns |a| x |b|."""
    lat1 = np.radians(np.asarray(lat1, float))[:, None]
    lon1 = np.radians(np.asarray(lon1, float))[:, None]
    lat2 = np.radians(np.asarray(lat2, float))[None, :]
    lon2 = np.radians(np.asarray(lon2, float))[None, :]
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * EARTH_KM * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def circle_polygon(lat, lon, radius_km, n=48):
    """Return (lats, lons) tracing a circle of radius_km around (lat, lon).
    Use to draw the radius as a filled Scattermapbox trace (fill='toself')."""
    ang = np.linspace(0, 2 * np.pi, n)
    dlat = (radius_km / EARTH_KM) * (180 / np.pi)
    dlon = dlat / np.cos(np.radians(lat))
    return lat + dlat * np.sin(ang), lon + dlon * np.cos(ang)


def _xy(df):
    return (pd.to_numeric(df["Latitude (Degrees)"], errors="coerce"),
            pd.to_numeric(df["Longitude (Degrees)"], errors="coerce"))


# ------------------------------------------------------------------ thermal split
def split_thermal(g, thermal_types):
    """Separate the generators table into (renewable_targets, thermal_plants).
    Thermal plants are expected to be extra rows you add to the same Orennia CSV
    with Power Project Type in thermal_types and a retirement date populated."""
    if "Power Project Type" not in g.columns:
        return g, g.iloc[0:0]
    is_thermal = g["Power Project Type"].isin(thermal_types)
    return g[~is_thermal].copy(), g[is_thermal].copy()


def _retire_year(thermal):
    for c in ["Estimated Retirement Date", "Reported Retirement Date", "Yrs to Est Retirement"]:
        if c in thermal.columns:
            yr = pd.to_datetime(thermal[c], errors="coerce").dt.year
            if yr.notna().any():
                return yr
    return pd.Series(np.nan, index=thermal.index)


# ------------------------------------------------------------------ signal 1
def thermal_retirement_proximity(g, *, thermal_types, radius_km=10.0, from_year=2028,
                                 plant_types=None):
    """
    plant_types : optional subset of thermal_types to consider (UI filter for coal vs gas).
    Returns (screen_df, detail_df).
      screen_df : ['Generator ID','Reason'] — fires binary for composite_score.
      detail_df : one row per (project, nearby retiring plant) for map + Targets drilldown.
    """
    ren, thr = split_thermal(g, thermal_types)
    empty = pd.DataFrame(columns=["Generator ID", "Reason"])
    if thr.empty or ren.empty:
        return empty, pd.DataFrame()

    thr = thr.copy()
    thr["retire_year"] = _retire_year(thr)
    keep = thr["retire_year"] >= from_year
    if plant_types:
        keep &= thr["Power Project Type"].isin(plant_types)
    thr = thr[keep]
    if thr.empty:
        return empty, pd.DataFrame()

    rlat, rlon = _xy(ren); tlat, tlon = _xy(thr)
    ok_r = rlat.notna() & rlon.notna(); ok_t = tlat.notna() & tlon.notna()
    ren, rlat, rlon = ren[ok_r], rlat[ok_r], rlon[ok_r]
    thr, tlat, tlon = thr[ok_t], tlat[ok_t], tlon[ok_t]
    if ren.empty or thr.empty:
        return empty, pd.DataFrame()

    D = _haversine_matrix(rlat.values, rlon.values, tlat.values, tlon.values)  # ren x thr
    within = D <= radius_km

    detail = []
    for i, gid in enumerate(ren["Generator ID"].values):
        js = np.where(within[i])[0]
        for j in js:
            tr = thr.iloc[j]
            detail.append({
                "Generator ID": gid,
                "project": ren.iloc[i].get("Power Project Name"),
                "thermal_plant": tr.get("Power Project Name"),
                "thermal_type": tr.get("Power Project Type"),
                "thermal_mw": pd.to_numeric(tr.get("Capacity (MW)"), errors="coerce"),
                "retire_year": int(tr["retire_year"]) if pd.notna(tr["retire_year"]) else None,
                "dist_km": round(float(D[i, j]), 1),
                "lat": float(tlat.values[j]), "lon": float(tlon.values[j]),
            })
    detail = pd.DataFrame(detail)
    if detail.empty:
        return empty, detail

    agg = (detail.groupby("Generator ID")
                 .agg(n=("thermal_plant", "nunique"),
                      mw=("thermal_mw", "sum"),
                      nearest=("dist_km", "min"),
                      first_year=("retire_year", "min")).reset_index())
    agg["Reason"] = ("Within " + str(int(radius_km)) + "km of " + agg["n"].astype(str)
                     + " retiring thermal plant(s) (" + agg["mw"].round(0).astype("Int64").astype(str)
                     + " MW, from " + agg["first_year"].astype("Int64").astype(str)
                     + ") — POI/offtake reuse opportunity")
    return agg[["Generator ID", "Reason"]], detail


# ------------------------------------------------------------------ signal 2
def datacenter_proximity(g, dc, *, radius_km=20.0, target_types=None):
    """
    dc : the Orennia data-center table (Name, lat, lon, Power Capacity (MW), ...).
    Returns (screen_df, detail_df). Score magnitude ~ Σ (DC_MW · (1 - d/R)).
    """
    empty = pd.DataFrame(columns=["Generator ID", "Reason"])
    if dc is None or dc.empty:
        return empty, pd.DataFrame()
    proj = g.copy()
    if target_types and "Power Project Type" in proj.columns:
        proj = proj[proj["Power Project Type"].isin(target_types)]

    plat, plon = _xy(proj)
    dclat = pd.to_numeric(dc["Latitude (Degrees)"], errors="coerce")
    dclon = pd.to_numeric(dc["Longitude (Degrees)"], errors="coerce")
    dcmw = pd.to_numeric(dc.get("Power Capacity (MW)", 0), errors="coerce").fillna(0)
    okp = plat.notna() & plon.notna(); okd = dclat.notna() & dclon.notna()
    proj, plat, plon = proj[okp], plat[okp], plon[okp]
    dc, dclat, dclon, dcmw = dc[okd], dclat[okd], dclon[okd], dcmw[okd]
    if proj.empty or dc.empty:
        return empty, pd.DataFrame()

    D = _haversine_matrix(plat.values, plon.values, dclat.values, dclon.values)
    within = D <= radius_km
    detail = []
    for i, gid in enumerate(proj["Generator ID"].values):
        js = np.where(within[i])[0]
        if len(js) == 0:
            continue
        weight = float(np.sum(dcmw.values[js] * (1 - D[i, js] / radius_km)))
        detail.append({
            "Generator ID": gid,
            "project": proj.iloc[i].get("Power Project Name"),
            "n_dc": int(len(js)),
            "dc_mw_sum": float(dcmw.values[js].sum()),
            "nearest_km": round(float(D[i, js].min()), 1),
            "proximity_weight": round(weight, 1),
        })
    detail = pd.DataFrame(detail)
    if detail.empty:
        return empty, detail
    detail["Reason"] = ("Within " + str(int(radius_km)) + "km of " + detail["n_dc"].astype(str)
                        + " data center(s) (" + detail["dc_mw_sum"].round(0).astype(int).astype(str)
                        + " MW load) — potential offtaker")
    return detail[["Generator ID", "Reason"]], detail


# ------------------------------------------------------------------ utility territories
def convex_hull(points):
    """
    Monotone-chain convex hull. Pure Python (no scipy/shapely dependency).
    `points` is an iterable of (lon, lat). Returns the hull as a closed ring.
    Used to sketch each balancing authority's footprint from its project locations.
    NOTE: this is an APPROXIMATION derived from where projects sit — it is not an
    official service-territory boundary.
    """
    pts = sorted(set((float(x), float(y)) for x, y in points
                     if x == x and y == y))          # drop NaN, dedupe, sort
    if len(pts) <= 2:
        return pts
    def cross(o, a, b):
        return (a[0]-o[0])*(b[1]-o[1]) - (a[1]-o[1])*(b[0]-o[0])
    lower = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    ring = lower[:-1] + upper[:-1]
    return ring + [ring[0]] if ring else ring


def hull_centroid(ring):
    """Rough centre of a hull ring, for placing the territory label."""
    if not ring:
        return None, None
    xs = [p[0] for p in ring]; ys = [p[1] for p in ring]
    return sum(ys) / len(ys), sum(xs) / len(xs)      # (lat, lon)
