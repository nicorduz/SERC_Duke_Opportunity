"""
Nofar SERC Deal Intelligence — Duke Carolinas (DEC + DEP) · professional MVP UI
"""
import json, os, io, base64
import hashlib
import numpy as np
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import distress_scan, web_signals
from pathlib import Path

from preprocess_orennia import load_and_reduce
import parsers, engine, actions
import scope, geo_signals, distress_sources

# Optional modules: a missing file or dependency must NOT take the app down.
# Each one degrades to a no-op and the affected feature simply says why.
_MISSING = []
try:
    import warn_live
except Exception as _e:
    warn_live = None; _MISSING.append(f"warn_live ({_e})")
try:
    import lien_sources
except Exception as _e:
    lien_sources = None; _MISSING.append(f"lien_sources ({_e})")
try:
    import ai_assistant
except Exception as _e:
    ai_assistant = None; _MISSING.append(f"ai_assistant ({_e})")
try:
    import auth
except Exception as _e:
    auth = None; _MISSING.append(f"auth ({_e})")
import team_hub
@st.cache_data(show_spinner=False)
def load_counties():
    import json, urllib.request
    with urllib.request.urlopen(...) as r:
        return json.load(r)

    # FIPS de estado: NC=37, SC=45. Necesitamos county FIPS por nombre.
    NC_SC_FIPS = {
        # NC
        "robeson":"37155","cumberland":"37051","bladen":"37017","sampson":"37163","duplin":"37061",
        "columbus":"37047","harnett":"37085","johnston":"37101","wayne":"37191","scotland":"37165",
        "richmond":"37153","hoke":"37093","moore":"37125","lee":"37105","nash":"37127","wilson":"37195",
        "halifax":"37083","northampton":"37131","edgecombe":"37065","pitt":"37147","beaufort":"37013",
        "bertie":"37015","hertford":"37091","martin":"37117","greene":"37079","lenoir":"37107",
        "craven":"37049","onslow":"37133","anson":"37007","union":"37179","stanly":"37167",
        "montgomery":"37123","chatham":"37037","person":"37145","granville":"37077","warren":"37185",
        "franklin":"37069","vance":"37181","caswell":"37033","rockingham":"37157","guilford":"37081",
        "alamance":"37001",
        # SC
        "marlboro":"45069","dillon":"45033","marion":"45067","horry":"45051","florence":"45041",
        "darlington":"45031","chesterfield":"45025","lancaster":"45057","york":"45091","sumter":"45085",
        "clarendon":"45027","williamsburg":"45089","georgetown":"45043","berkeley":"45015",
        "orangeburg":"45075","kershaw":"45055",
    }
    wc = wd.copy()
    wc["cty"] = wc["county"].astype(str).str.lower().str.replace(" county","",regex=False).str.strip()
    agg = wc.groupby("cty").agg(withdrawals=("queue_id","count"), mw=("mw","sum")).reset_index()
    agg["fips"] = agg["cty"].map(NC_SC_FIPS)
    mapped = agg.dropna(subset=["fips"])
    st.markdown(f'<div class="sub">{int(mapped["withdrawals"].sum())} withdrawals across {len(mapped)} counties '
                f'(color = # withdrawals). Counties without a shape are in the list below.</div>', unsafe_allow_html=True)

    if len(mapped):
        geo = load_counties()
        fig_w = px.choropleth_mapbox(
            mapped, geojson=geo, locations="fips", color="withdrawals",
            color_continuous_scale=["#F6C9C4", "#E88A82", "#B3261E", "#7A140F"],
            range_color=(1, mapped["withdrawals"].max()),
            mapbox_style="open-street-map", zoom=6.1, center={"lat":35.2,"lon":-79.2},
            opacity=0.75, height=640,
            hover_name="cty",
            hover_data={"withdrawals":True, "mw":":.0f", "fips":False})
        # sitios Nofar como capa de texto grande
        fig_w.add_scattermapbox(
            lat=NOFAR_SITES["lat"], lon=NOFAR_SITES["lon"], mode="markers+text",
            marker=dict(size=20, color=GOLD), text=["★ "+n for n in NOFAR_SITES["name"]],
            textposition="top center", textfont=dict(color=DEEP, size=13),
            name="Nofar sites", hoverinfo="text")
        fig_w.update_layout(margin=dict(l=0,r=0,t=0,b=0), coloraxis_colorbar_title="Withdrawals")
        st.plotly_chart(fig_w, use_container_width=True, config={"displayModeBar": False})

BASE_DIR = Path(__file__).resolve().parent

DATA = BASE_DIR / "data"
UP = BASE_DIR / "data_uploads"

DATA.mkdir(parents=True, exist_ok=True)
UP.mkdir(parents=True, exist_ok=True)

REG = DATA / "sources_registry.json"
TODAY = pd.Timestamp.today().normalize()

# ─────────────────────────────── brand tokens
INDIGO   = "#4A2EE3"
DEEP     = "#2B1B8F"
INK      = "#17153A"
GOLD     = "#F4C843"
PAPER    = "#F7F6FC"
MIST     = "#E6E2FA"
PALETTE  = [INDIGO, GOLD, "#8F7EF0", DEEP, "#C9C2F5"]

st.set_page_config(page_title="Nofar · SERC Deal Intelligence", layout="wide",
                   page_icon="assets/nofar_logo.png", initial_sidebar_state="collapsed")

# Bump this on every change you push. It renders in the sidebar, so you can always
# confirm at a glance whether Streamlit Cloud is serving the build you just pushed.
APP_VERSION = "v6 · 2026-09-11 · free basemap + progress scan"

APP_USER = auth.require_login() if auth else "dev"  # bypasses if module/secrets missing

def logo_b64():
    try:
        return base64.b64encode(open("assets/nofar_logo.png", "rb").read()).decode()
    except Exception:
        return ""

st.markdown(f"""<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=Inter:wght@400;500;600&display=swap');

html, body, [class*="css"], .stApp {{ font-family:'Inter',sans-serif; color:{INK}; }}
.stApp {{ background:{PAPER}; }}
#MainMenu, footer {{ visibility:hidden; }}
header[data-testid="stHeader"] {{ background:transparent; }}
.block-container {{ padding-top:0.8rem; max-width:1400px; }}

h1,h2,h3,h4 {{ font-family:'Space Grotesk',sans-serif; color:{INK}; letter-spacing:-0.01em; }}

/* ── hero band with Nofar stripes */
.hero {{ background:linear-gradient(120deg,{DEEP} 0%,{INDIGO} 70%);
  border-radius:18px; padding:26px 34px 54px 34px; position:relative; overflow:hidden; }}
.hero::after {{ content:""; position:absolute; right:-40px; top:-60px; width:340px; height:340px;
  background:repeating-linear-gradient(45deg,{GOLD} 0 14px,transparent 14px 42px);
  opacity:.28; transform:rotate(8deg); border-radius:24px; }}
.hero img {{ height:44px; background:white; padding:7px 14px; border-radius:10px; }}
.hero .t {{ font-family:'Space Grotesk'; font-size:30px; font-weight:700; color:#fff; margin:12px 0 2px; }}
.hero .s {{ color:#CFC8F7; font-size:14.5px; }}
.hero .chip {{ display:inline-block; background:rgba(255,255,255,.14); color:#fff; font-size:12px;
  padding:4px 12px; border-radius:99px; margin-right:8px; margin-top:12px; }}

/* ── KPI chips overlapping hero */
.kpis {{ display:flex; gap:14px; margin:-34px 12px 8px 12px; position:relative; z-index:3; flex-wrap:wrap; }}
.kpi {{ flex:1; min-width:150px; background:#fff; border:1px solid {MIST}; border-radius:14px;
  padding:14px 18px 12px; box-shadow:0 8px 22px rgba(43,27,143,.10); position:relative; overflow:hidden; }}
.kpi::before {{ content:""; position:absolute; left:0; top:0; bottom:0; width:5px;
  background:repeating-linear-gradient(45deg,{GOLD} 0 6px,{INDIGO} 6px 12px); }}
.kpi .v {{ font-family:'Space Grotesk'; font-size:26px; font-weight:700; color:{INDIGO}; }}
.kpi .l {{ font-size:12px; color:#6B668F; margin-top:2px; }}

/* ── tabs as pills */
.stTabs [data-baseweb="tab-list"] {{ gap:8px; background:transparent; }}
.stTabs [data-baseweb="tab"] {{ background:#fff; border:1px solid {MIST}; border-radius:99px;
  padding:8px 18px; font-family:'Inter'; font-weight:500; color:{INK}; }}
.stTabs [aria-selected="true"] {{ background:{INDIGO} !important; color:#fff !important;
  border-color:{INDIGO} !important; }}
.stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"] {{ display:none; }}

/* ── cards & badges */
.card {{ background:#fff; border:1px solid {MIST}; border-radius:16px; padding:20px 22px;
  box-shadow:0 4px 16px rgba(43,27,143,.06); margin-bottom:14px; }}
.badge {{ display:inline-block; padding:3px 11px; border-radius:99px; font-size:11.5px; font-weight:600;
  margin:0 6px 6px 0; }}
.b-hot {{ background:{GOLD}; color:{INK}; }}
.b-sig {{ background:{MIST}; color:{DEEP}; }}
.b-warn {{ background:#FCE8E6; color:#B3261E; }}
.sect {{ font-family:'Space Grotesk'; font-weight:700; font-size:19px; margin:6px 0 2px;
  padding-left:14px; border-left:5px solid {GOLD}; }}
.sub {{ color:#6B668F; font-size:13px; margin-bottom:10px; }}

/* ── playbook timeline */
.pstep {{ display:flex; gap:16px; margin-bottom:0; }}
.pnum {{ min-width:34px; height:34px; border-radius:99px; background:{INDIGO}; color:#fff;
  font-family:'Space Grotesk'; font-weight:700; display:flex; align-items:center; justify-content:center; }}
.pline {{ width:4px; flex:1; margin:4px auto;
  background:repeating-linear-gradient(180deg,{GOLD} 0 6px,transparent 6px 12px); }}
.pbody {{ background:#fff; border:1px solid {MIST}; border-radius:14px; padding:14px 18px;
  margin-bottom:14px; flex:1; box-shadow:0 3px 10px rgba(43,27,143,.05); }}
.pbody b.t {{ font-family:'Space Grotesk'; font-size:15.5px; }}
.pbody .row {{ margin-top:6px; font-size:13.5px; }}
.pbody .k {{ color:{DEEP}; font-weight:600; }}
.pbody a {{ color:{INDIGO}; word-break:break-all; }}
.hl {{ background:{PAPER}; border-radius:8px; padding:8px 10px; margin-top:8px; font-size:12.5px; color:#4A4670; }}

.stButton>button {{ background:{INDIGO}; color:#fff; border:none; border-radius:10px;
  font-weight:600; padding:8px 18px; }}
.stButton>button:hover {{ background:{DEEP}; color:{GOLD}; }}
div[data-testid="stDataFrame"] {{ background:#fff; border-radius:14px; border:1px solid {MIST}; padding:6px; }}
</style>""", unsafe_allow_html=True)

# ─────────────────────────────── registry (AUTO sources only get buttons; manual = static)
AUTO = {"eia860m": "EIA-860M ownership", "courtlistener": "CourtListener bankruptcies",
        "ferc_elibrary": "FERC eLibrary", "media_rss": "Trade media"}
STATIC = {"orennia": "Orennia projects (1,271 gens)", "duke_queue": "Duke cluster queue",
          "duke_oasis": "OASIS FERC posting", "red_zone": "DEP Red Zone",
          "restrictions": "Sabin restrictions", "contested": "Contested projects",
          "warn_nc": "NC WARN", "warn_sc": "SC WARN"}

def load_reg():
    r = json.load(open(REG)) if os.path.exists(REG) else {}
    for k in AUTO: r.setdefault(k, {"last_updated": None, "rows": 0})
    return r
def save_reg(r): json.dump(r, open(REG, "w"), indent=1, default=str)
reg = load_reg()

# ─────────────────────────────── data
def file_signature(path):
    """
    Changes whenever the file is replaced, forcing Streamlit
    to reload the cached datasets.
    """
    path = Path(path)

    if not path.exists():
        return ("missing",)

    file_stat = path.stat()

    return (
        str(path.resolve()),
        file_stat.st_mtime_ns,
        file_stat.st_size,
    )


def normalize_red_zone(red_zone):
    """
    Makes both the old and new red-zone Parquet schemas compatible
    with engine.py and the Asset Map.

    Existing columns are preserved. Canonical lowercase columns
    are added for the app and engine.
    """
    if red_zone is None or red_zone.empty:
        return pd.DataFrame(
            columns=[
                "line_id",
                "line_name",
                "kv",
                "substation",
                "type",
                "latitude",
                "longitude",
            ]
        )

    result = red_zone.copy()

    # Actual column names indexed by normalized name.
    column_lookup = {
        str(column).strip().lower(): column
        for column in result.columns
    }

    aliases = {
        "line_id": [
            "line_id",
            "ol#",
            "ol #",
            "ol",
        ],
        "line_name": [
            "line_name",
            "line name",
        ],
        "kv": [
            "kv",
        ],
        "substation": [
            "substation",
            "substation name",
            "poi",
            "poi name",
        ],
        "type": [
            "type",
        ],
        "latitude": [
            "latitude",
            "lat",
            "latitude (degrees)",
            "poi latitude",
            "substation latitude",
        ],
        "longitude": [
            "longitude",
            "lon",
            "lng",
            "long",
            "longitude (degrees)",
            "poi longitude",
            "substation longitude",
        ],
    }

    # Add canonical lowercase columns without deleting original columns.
    for canonical_column, possible_names in aliases.items():
        if canonical_column in result.columns:
            continue

        source_column = next(
            (
                column_lookup[possible_name]
                for possible_name in possible_names
                if possible_name in column_lookup
            ),
            None,
        )

        if source_column is not None:
            result[canonical_column] = result[source_column]

    # engine.py requires this exact column.
    if "substation" not in result.columns:
        raise ValueError(
            "red_zone.parquet does not contain a recognizable "
            f"substation column. Columns found: {result.columns.tolist()}"
        )

    # Create optional columns when they are absent.
    for column in [
        "line_id",
        "line_name",
        "kv",
        "type",
        "latitude",
        "longitude",
    ]:
        if column not in result.columns:
            result[column] = pd.NA

    # Guarantee that engine.py receives valid strings only.
    result["substation"] = (
        result["substation"]
        .astype("string")
        .fillna("")
        .str.strip()
    )

    # Remove separator/header rows without an actual substation.
    result = result[
        result["substation"].ne("")
    ].copy()

    # Standardize text fields.
    for column in [
        "line_id",
        "line_name",
        "type",
    ]:
        result[column] = result[column].astype("string")

    # Standardize numeric fields.
    for column in [
        "kv",
        "latitude",
        "longitude",
    ]:
        result[column] = pd.to_numeric(
            result[column],
            errors="coerce",
        )

    return result


@st.cache_data(show_spinner=False)
def load_all(red_zone_signature):
    d = {}

    d["g"] = pd.read_parquet(
        DATA / "orennia_generators.parquet"
    )

    d["m"] = pd.read_parquet(
        DATA / "orennia_monthly.parquet"
    )

    for dataset_name in [
        "duke_queue",
        "duke_oasis",
        "red_zone",
        "restrictions",
        "contested",
        "warn_nc",
        "warn_sc",
    ]:
        dataset_path = UP / f"{dataset_name}.parquet"

        if not dataset_path.exists():
            continue

        dataset = pd.read_parquet(dataset_path)

        if dataset_name == "red_zone":
            dataset = normalize_red_zone(dataset)

        d[dataset_name] = dataset

    eia_path = DATA / "eia860m.parquet"

    if eia_path.exists():
        d["eia"] = pd.read_parquet(eia_path)

    return d


RED_ZONE_PATH = UP / "red_zone.parquet"

D = load_all(
    file_signature(RED_ZONE_PATH)
)
g = D["g"]

# >>> NOFAR-ADD: SERC-wide scope selector + geo-signal controls
with st.sidebar:
    st.markdown("### Universe")
    _scope_mode = st.radio("Scope", ["SERC (Non-ISO)", "Duke NC/SC only"], index=0, key="scope_mode")
    with st.expander("Geographic signals"):
        TH_R  = st.slider("Thermal radius (km)", 1, 50, 10, key="sb_th_r")
        TH_YR = st.slider("Retiring from year", 2026, 2045, 2028, key="sb_th_yr")
        TH_TY = st.multiselect("Plant type", sorted(scope.THERMAL_TYPES),
                               default=sorted(scope.THERMAL_TYPES), key="sb_th_ty")
        DC_R  = st.slider("Data center radius (km)", 1, 60, 20, key="sb_dc_r")
if _scope_mode == "Duke NC/SC only":
    g = scope.apply_scope(g, states=["NC", "SC"], duke_only=True)
else:
    g = scope.apply_scope(g, iso="Non-ISO")
# Thermal plants (Coal / Natural Gas) are CONTEXT, not acquisition targets:
# keep them in G_ALL for the proximity signal, exclude them from the target table.
G_ALL = g.copy()
if "Is Thermal" in g.columns:
    g = g[~g["Is Thermal"].fillna(False)].reset_index(drop=True)
st.sidebar.caption(f"Build: {APP_VERSION}")
if _MISSING:
    st.sidebar.warning("Optional modules not loaded:\n\n- " + "\n- ".join(_MISSING))
st.sidebar.caption("Universe: " + scope.region_label(g)
                   + (f" · {int(G_ALL['Is Thermal'].sum())} thermal plants (context)"
                      if "Is Thermal" in G_ALL.columns else ""))
# <<< NOFAR-ADD

_warn = pd.concat([D[k] for k in ("warn_nc", "warn_sc") if k in D], ignore_index=True) \
        if any(k in D for k in ("warn_nc", "warn_sc")) else None
scr = engine.opportunity_screens(g, D.get("eia"), D.get("duke_queue"), D.get("red_zone"),
                                 D.get("restrictions"), D.get("contested"), warn=_warn)

# >>> NOFAR-ADD: geo proximity + external-distress signals folded into the screen set
try:
    _entities = distress_sources.build_entity_list(g, D.get("duke_oasis"))
    _pp = DATA / "distress_perproj.parquet"
    _pv = DATA / "distress_provenance.parquet"
    per_proj   = pd.read_parquet(_pp) if _pp.exists() else pd.DataFrame()
    provenance = pd.read_parquet(_pv) if _pv.exists() else pd.DataFrame()
    scr["distress_external"] = distress_sources.distress_screen(per_proj)
    _th_scr, TH_DET = geo_signals.thermal_retirement_proximity(
        G_ALL, thermal_types=scope.THERMAL_TYPES, radius_km=TH_R,
        from_year=TH_YR, plant_types=TH_TY)
    _dc = pd.read_parquet(DATA / "data_centers.parquet") if (DATA / "data_centers.parquet").exists() else None
    _dc_scr, DC_DET = geo_signals.datacenter_proximity(
        g, _dc, radius_km=DC_R, target_types=scope.TARGET_TYPES)
    scr["thermal_retire"]  = _th_scr
    scr["datacenter_prox"] = _dc_scr
except Exception as _e:
    provenance, per_proj = pd.DataFrame(), pd.DataFrame()
    TH_DET, DC_DET = pd.DataFrame(), pd.DataFrame()
    st.sidebar.warning(f"New signals not loaded: {_e}")
# <<< NOFAR-ADD
DW = engine.DEFAULT_WEIGHTS
weights = {k: st.session_state.get(f"w_{k}", v) for k, v in DW.items()}
THRESHOLD = st.session_state.get("thr", 0.5)
top = engine.composite_score(g, scr, weights, THRESHOLD)
# Guarantee the columns the tables reference exist even when nothing scored,
# so an empty result renders an empty table instead of raising KeyError.
if top.empty:
    for _c in ["Power Project Name", "County", "State", "Capacity (MW)",
               "Detailed Status", "Opportunity Score", "Why", "Generator ID",
               "Latitude (Degrees)", "Longitude (Degrees)", "_fired"]:
        if _c not in top.columns:
            top[_c] = pd.Series(dtype="object")
media_df = pd.read_parquet(f"{DATA}/media.parquet") if os.path.exists(f"{DATA}/media.parquet") else None
cl_df = pd.read_parquet(f"{DATA}/courtlistener.parquet") if os.path.exists(f"{DATA}/courtlistener.parquet") else None
ownership = distress_scan.build_ownership(g, D.get("eia"))
dsig, dcomp = distress_scan.build_distress(g, scr, D.get("duke_queue"), _warn, media_df, cl_df)
own_by_id = ownership.set_index("project_id").to_dict("index") if "project_id" in ownership.columns else {}
op = g[g["Is Operating"]]
NOFAR_SITES = pd.DataFrame([
    {"name": "NYE",            "lat": 34.620000, "lon": -79.029836},
    {"name": "Lewis",          "lat": 34.853336, "lon": -79.161383},
    {"name": "Gardner",        "lat": 35.032947, "lon": -78.825672},
    {"name": "Hatcher",        "lat": 34.831122, "lon": -77.976219},
    {"name": "Shalimar Farms", "lat": 36.372836, "lon": -79.624592},
    {"name": "Regency (Ravi Reddy)", "lat": 36.122692, "lon": -78.284289},
])
NC_SC_COUNTY_LATLON = {
    "robeson": (34.64, -79.10), "cumberland": (35.05, -78.83), "bladen": (34.62, -78.56),
    "sampson": (35.02, -78.37), "duplin": (34.94, -77.93), "columbus": (34.27, -78.65),
    "harnett": (35.37, -78.87), "johnston": (35.51, -78.36), "wayne": (35.36, -78.00),
    "scotland": (34.84, -79.48), "richmond": (35.00, -79.75), "hoke": (35.02, -79.23),
    "moore": (35.31, -79.48), "lee": (35.47, -79.17), "nash": (35.97, -77.99),
    "wilson": (35.71, -77.92), "halifax": (36.25, -77.65), "northampton": (36.42, -77.40),
    "edgecombe": (35.91, -77.60), "pitt": (35.59, -77.37), "beaufort": (35.49, -76.85),
    "bertie": (36.06, -77.00), "hertford": (36.36, -76.98), "martin": (35.84, -77.10),
    "greene": (35.48, -77.68), "lenoir": (35.24, -77.64), "craven": (35.12, -77.08),
    "onslow": (34.76, -77.40), "anson": (34.97, -80.10), "union": (34.99, -80.53),
    "stanly": (35.31, -80.25), "montgomery": (35.33, -79.90), "chatham": (35.70, -79.25),
    "person": (36.39, -78.97), "granville": (36.30, -78.65), "warren": (36.40, -78.10),
    "franklin": (36.08, -78.28), "vance": (36.36, -78.41), "caswell": (36.39, -79.34),
    "rockingham": (36.39, -79.77), "guilford": (36.08, -79.79), "alamance": (36.04, -79.40),
    # SC
    "marlboro": (34.60, -79.68), "dillon": (34.39, -79.37), "marion": (34.08, -79.36),
    "horry": (33.90, -78.98), "florence": (34.05, -79.70), "darlington": (34.33, -79.95),
    "chesterfield": (34.63, -80.16), "lancaster": (34.69, -80.71), "york": (34.97, -81.19),
    "sumter": (33.92, -80.38), "clarendon": (33.66, -80.21), "williamsburg": (33.62, -79.72),
    "georgetown": (33.43, -79.36), "berkeley": (33.20, -79.95), "orangeburg": (33.44, -80.80),
    "calhoun": (33.68, -80.78), "lee": (34.16, -80.25), "kershaw": (34.34, -80.59),
}

def add_nofar_layer(fig, show=True):
    if not show: return fig
    fig.add_trace(go.Scattermapbox(
        lat=NOFAR_SITES["lat"], lon=NOFAR_SITES["lon"], mode="markers+text",
        marker=dict(size=22, color=GOLD),
        text=["📍 " + n for n in NOFAR_SITES["name"]], textposition="top center",
        textfont=dict(color=DEEP, size=13, family="Space Grotesk"),
        name="Nofar sites", hovertext="⭐ Nofar: " + NOFAR_SITES["name"], hoverinfo="text"))
    return fig

# ─────────────────────────────── fetchers
def fetch_media():
    import feedparser
    feeds = {"PV Magazine USA": "https://pv-magazine-usa.com/feed/",
             "Utility Dive": "https://www.utilitydive.com/feeds/news/",
             "Canary Media": "https://www.canarymedia.com/rss.xml",
             "Renewable Energy World": "https://www.renewableenergyworld.com/feed/"}
    GEO = ["north carolina", "south carolina", "carolinas", "duke energy"]
    TOP = ["solar", "storage", "battery", "interconnection", "purpa", "bankrupt",
           "acquisition", "sale", "rfp", "data center", "ppa", "qf"]
    rows = []
    for src, url in feeds.items():
        try:
            for e in feedparser.parse(url).entries[:60]:
                t = f" {e.get('title','')} {e.get('summary','')} ".lower()
                if any(k in t for k in TOP) and any(k in t for k in GEO):
                    rows.append({"source": src, "title": e.get("title", ""),
                                 "link": e.get("link", ""), "published": e.get("published", "")[:16]})
        except Exception:
            pass
    pd.DataFrame(rows).to_parquet(f"{DATA}/media.parquet", index=False)
    reg["media_rss"] = {"last_updated": str(TODAY.date()), "rows": len(rows)}; save_reg(reg)

def fetch_ferc():
    import feedparser, urllib.parse
    rows = []
    for q in ("solar North Carolina", "solar South Carolina", "Duke Energy Progress"):
        try:
            fp = feedparser.parse("https://elibrary.ferc.gov/eLibrary/rss?searchText=" + urllib.parse.quote(q))
            rows += [{"query": q, "title": e.get("title", ""), "link": e.get("link", ""),
                      "published": e.get("published", "")[:16]} for e in fp.entries[:30]]
        except Exception:
            pass
    pd.DataFrame(rows).to_parquet(f"{DATA}/ferc.parquet", index=False)
    reg["ferc_elibrary"] = {"last_updated": str(TODAY.date()), "rows": len(rows)}; save_reg(reg)

def fetch_courtlistener():
    import requests
    rows = []
    for t in ("solar", "renewable energy"):
        try:
            r = requests.get("https://www.courtlistener.com/api/rest/v4/search/",
                             params={"q": f'"{t}"', "type": "r", "order_by": "dateFiled desc",
                                     "filed_after": str((TODAY - pd.Timedelta(days=120)).date())}, timeout=25)
            rows += [{"term": t, "case": i.get("caseName", ""), "court": i.get("court", ""),
                      "filed": i.get("dateFiled", ""),
                      "link": "https://www.courtlistener.com" + (i.get("absolute_url") or "")}
                     for i in r.json().get("results", [])[:25]]
        except Exception:
            pass
    pd.DataFrame(rows).to_parquet(f"{DATA}/courtlistener.parquet", index=False)
    reg["courtlistener"] = {"last_updated": str(TODAY.date()), "rows": len(rows)}; save_reg(reg)

def fetch_warn_layoffs():
    """AUTOMATIC daily layoffs for all SERC states (WARN Firehose). Cached to parquet."""
    if warn_live is None:
        return pd.DataFrame()
    w = warn_live.fetch_warn_live(states=scope.SERC_STATES,
                                  api_key=st.secrets.get("WARN_API_KEY"))
    if len(w):
        w.to_parquet(f"{DATA}/warn_live.parquet", index=False)
        reg["warn_live"] = {"last_updated": str(TODAY.date()), "rows": len(w)}; save_reg(reg)
    return w

def fetch_distress(max_entities=20, do_warn=True, do_news=True,
                   do_courtlistener=True, do_liens=False, status=None, bar=None):
    """
    Entity-centric distress scan, incremental and interruptible.

    CourtListener's free tier allows ~5 requests/min, so each entity costs ~12 s.
    Scanning 80 entities across two passes takes ~25 min, which Streamlit will drop
    long before it finishes. Hence: a capped entity count, per-source switches, and
    live progress so it is never a black box.
    """
    def say(msg):
        if status is not None:
            status.update(label=msg)

    def mk_progress(tag, base, span):
        def _cb(i, n, name):
            if bar is not None:
                bar.progress(min(base + span * i / max(n, 1), 1.0),
                             text=f"{tag} {i}/{n} · {str(name)[:38]}")
        return _cb

    say("Building the deduplicated entity list...")
    ent = distress_sources.build_entity_list(g, D.get("duke_oasis"))
    frames = []

    # county-level ambient layer — instant, no network
    say("Aggregating county-level signals...")
    frames.append(distress_sources.county_ambient(
        g, warn=_warn, duke_queue=D.get("duke_queue"),
        restrictions=D.get("restrictions"), contested=D.get("contested")))

    if do_warn and warn_live is not None:
        say("Fetching live WARN layoffs (1 call per state)...")
        if bar is not None: bar.progress(0.10, text="WARN layoffs...")
        wl = fetch_warn_layoffs()
        if len(wl):
            frames.append(warn_live.to_provenance(wl, ent, g))

    if do_news:
        say("Scanning news per entity...")
        frames.append(distress_sources.fetch_news(ent, max_entities=max_entities))

    if do_courtlistener:
        say(f"CourtListener bankruptcies — {max_entities} entities (~12 s each)...")
        frames.append(distress_sources.fetch_courtlistener(
            ent, token=st.secrets.get("COURTLISTENER_TOKEN"),
            max_entities=max_entities, progress=mk_progress("Bankruptcy", 0.20, 0.40)))

    if do_liens:
        say(f"Liens / foreclosures — {max_entities} entities (~12 s each)...")
        frames.append(distress_sources.fetch_liens_free(
            ent, courtlistener_token=st.secrets.get("COURTLISTENER_TOKEN"),
            max_entities=max_entities, progress=mk_progress("Liens", 0.60, 0.35)))

    say("Matching signals to projects...")
    if bar is not None: bar.progress(0.97, text="Matching...")
    pp, prov = distress_sources.assemble(*frames)
    pp.to_parquet(f"{DATA}/distress_perproj.parquet", index=False)
    prov.to_parquet(f"{DATA}/distress_provenance.parquet", index=False)
    reg["distress"] = {"last_updated": str(TODAY.date()), "rows": len(prov)}; save_reg(reg)
    if bar is not None: bar.progress(1.0, text="Done")
    return len(prov), len(ent)

def fetch_eia860m():
    import requests
    base = "https://www.eia.gov/electricity/data/eia860m/xls/{m}_generator{y}.xlsx"
    for mth in pd.date_range(end=TODAY, periods=6, freq="MS")[::-1]:
        try:
            r = requests.get(base.format(m=mth.strftime("%B").lower(), y=mth.year), timeout=60)
            if r.status_code != 200: continue
            xls = pd.ExcelFile(io.BytesIO(r.content)); fr = []
            for sh in xls.sheet_names:
                if any(k in sh for k in ("Operating", "Planned", "Retired")):
                    dd = pd.read_excel(xls, sh, skiprows=2); dd["EIA Sheet"] = sh; fr.append(dd)
            df = pd.concat(fr, ignore_index=True)
            sc = "Plant State" if "Plant State" in df.columns else "State"
            df = df[df[sc].isin(scope.SERC_STATES)]
            keep = [c for c in ["Entity Name", "Plant ID", "Plant Name", sc, "County",
                                "Nameplate Capacity (MW)", "Technology", "Status", "EIA Sheet"] if c in df.columns]
            df[keep].rename(columns={"Plant ID": "EIA Plant ID"}).to_parquet(f"{DATA}/eia860m.parquet", index=False)
            reg["eia860m"] = {"last_updated": str(TODAY.date()), "rows": len(df)}; save_reg(reg)
            return True
        except Exception:
            continue
    return False

# ─────────────────────────────── HERO + KPIs
st.markdown(f"""
<div class="hero">
  <img src="data:image/png;base64,{logo_b64()}">
  <div class="t">SERC Deal Intelligence · Duke Carolinas</div>
  <div class="s">DEC + DEP territory · NC &amp; SC · solar PV &amp; storage · free-source screens, fully traceable</div>
  <span class="chip">Data vintage: Orennia Jul 2026</span><span class="chip">Queue Mar 2026</span>
  <span class="chip">OASIS Jun 2026</span><span class="chip">{len(top)} live opportunities</span>
</div>
<div class="kpis">
  <div class="kpi"><div class="v">{len(g):,}</div><div class="l">Generators tracked</div></div>
  <div class="kpi"><div class="v">{int(op['Capacity (MW)'].sum()):,}</div><div class="l">Operating MW</div></div>
  <div class="kpi"><div class="v">{int(g[~g['Is Operating']]['Capacity (MW)'].sum()):,}</div><div class="l">Pipeline MW</div></div>
  <div class="kpi"><div class="v">{len(scr.get('withdrawn_queue', [])):,}</div><div class="l">Queue withdrawals</div></div>
  <div class="kpi"><div class="v">{len(scr['red_zone'])}</div><div class="l">Red-zone POIs</div></div>
  <div class="kpi"><div class="v">{len(top)}</div><div class="l">Scored opportunities</div></div>
</div>""", unsafe_allow_html=True)

(
    tab_date_updates,
    tab_live_signals,
    tab_score_methodology,
    tab_targets_playbooks,
    tab_dashboard,
    tab_map,
    tab_withdrawals,
    tab_action_queue,
    tab_team_hub,
) = st.tabs([
    "Date & Updates",
    "Live Signals",
    "Score & Methodology",
    "Targets & Playbooks",
    "Dashboard",
    "Map",
    "Withdrawals",
    "Action Queue",
    "Team Hub",
])

# Column formatting for the tables.
# NOTE: max_value must never be NaN — Streamlit cannot serialize it to JSON and
# raises StreamlitAPIException. `float(x or 8)` is NOT safe here because NaN is
# truthy in Python, so an empty `top` would leak NaN straight through.
def _score_ceiling(frame, col="Opportunity Score", default=8.0):
    try:
        v = float(pd.to_numeric(frame[col], errors="coerce").max())
    except Exception:
        return default
    return v if np.isfinite(v) and v > 0 else default

FMT = {"Capacity (MW)": st.column_config.NumberColumn("MW", format="%.1f"),
       "Opportunity Score": st.column_config.ProgressColumn(
           "Score", min_value=0, max_value=_score_ceiling(top), format="%.1f"),
       "CF (12m)": st.column_config.NumberColumn("CF 12m", format="percent"),
       "Age (yrs)": st.column_config.NumberColumn("Age", format="%.0f y")}

# ─────────────────────────────── DASHBOARD
with tab_dashboard:
    a, b = st.columns([3, 2])
    with a:
        st.markdown('<div class="sect">Top opportunities</div><div class="sub">Composite of nine screens — every point decomposes in the Why column.</div>', unsafe_allow_html=True)
        if top.empty:
            st.info("No project scored above the current threshold. Lower it in "
                    "**Score & Methodology**, widen the Universe in the sidebar, or run "
                    "**Update distress signals** in Data & Updates to bring in signals.")
        else:
            st.dataframe(top[["Power Project Name", "County", "State", "Capacity (MW)",
                              "Detailed Status", "Opportunity Score", "Why"]].head(25),
                         use_container_width=True, height=430,
                         column_config=FMT, hide_index=True)
    with b:
        st.markdown('<div class="sect">Where the signals are</div><div class="sub">Hits per screen (a project can fire several).</div>', unsafe_allow_html=True)
        counts = {"QF roll-up": len(scr["qf_rollup"]), "Contract cliff": len(scr["contract_cliff"]),
                  "Underperformance": len(scr["underperf"]), "Dev distress": len(scr["dev_distress"]),
                  "Late-stage": len(scr["late_stage"]), "IX burden": len(scr["ix_burden"]),
                  "Red zone": len(scr["red_zone"]), "County risk": len(scr["county_risk"])}
        cdf = pd.DataFrame(counts.items(), columns=["Screen", "Hits"]).sort_values("Hits")
        fig = px.bar(cdf, x="Hits", y="Screen", orientation="h", color_discrete_sequence=[INDIGO])
        fig.update_layout(height=300, margin=dict(l=0, r=10, t=6, b=0), plot_bgcolor="white",
                          font_family="Inter", xaxis_title=None, yaxis_title=None)
        fig.update_traces(marker_line_width=0)
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

        cc = g.dropna(subset=["Contract Termination Date"]).copy()
        cc["yr"] = pd.to_datetime(cc["Contract Termination Date"]).dt.year
        cc = cc[(cc.yr >= 2026) & (cc.yr <= 2038)].groupby("yr")["Capacity (MW)"].sum().reset_index()
        st.markdown('<div class="sect">Contract cliff</div><div class="sub">MW with PPAs ending, by year.</div>', unsafe_allow_html=True)
        f2 = px.bar(cc, x="yr", y="Capacity (MW)", color_discrete_sequence=[GOLD])
        f2.update_layout(height=230, margin=dict(l=0, r=10, t=6, b=0), plot_bgcolor="white",
                         font_family="Inter", xaxis_title=None, yaxis_title="MW")
        st.plotly_chart(f2, use_container_width=True, config={"displayModeBar": False})

    if "owner_concentration" in scr:
        st.markdown('<div class="sect">Roll-up targets by owner</div><div class="sub">Owners with ≥3 operating units (EIA-860M join). Units × age = portfolio-approach candidates.</div>', unsafe_allow_html=True)
        st.dataframe(scr["owner_concentration"].head(15), use_container_width=True, hide_index=True)
    else:
        st.info("Run the EIA-860M update (Data & updates) to unlock owner roll-up analysis.")

# ─────────────────────────────── TARGETS & PLAYBOOKS
with tab_targets_playbooks:
    left, right = st.columns([2, 3])
    with left:
        st.markdown('<div class="sect">Pick a target</div>', unsafe_allow_html=True)
        f1, f2 = st.columns(2)
        _st_opts = sorted(g["State"].dropna().unique())
        stt = f1.multiselect("State", _st_opts, default=_st_opts,
                             label_visibility="collapsed", key="tgt_state")
        minmw = f2.slider("Min MW", 0.0, 80.0, 0.0, 1.0,
                          label_visibility="collapsed", key="tgt_minmw")
        tt = top[top["State"].isin(stt) & (top["Capacity (MW)"] >= minmw)] if len(top) \
             else top
        if tt.empty:
            # Do NOT call st.stop(): that would abort every other tab too.
            st.info("No targets match the current filters or threshold. "
                    "Lower the threshold in Score & Methodology or widen the Universe.")
        if not tt.empty:
            sel = st.selectbox("Target", tt["Generator ID"].head(80), key="tgt_sel",
                               format_func=lambda i: (lambda r: f"{r['Power Project Name']} · {r['County']} {r['State']} · {r['Capacity (MW)']:.0f} MW · ★{r['Opportunity Score']:.1f}")(tt.set_index("Generator ID").loc[i]),
                               label_visibility="collapsed")
            row = pd.concat([pd.Series({"Generator ID": sel}), top.set_index("Generator ID").loc[sel]])
            badges = "".join(f'<span class="badge b-sig">{s.replace("_"," ")}</span>' for s in row["_fired"] if s != "county_risk")
            if "county_risk" in row["_fired"]: badges += '<span class="badge b-warn">county risk</span>'
            own = scr.get("_owner_map", {}).get(sel)
            st.markdown(f"""<div class="card">
    <b style="font-family:'Space Grotesk';font-size:19px">{row['Power Project Name']}</b><br>
    <span class="sub">{row['County']} County, {row['State']} · {row['Technology']}</span><br>{badges}
    <table style="width:100%;font-size:13.5px;margin-top:8px">
    <tr><td style="color:#6B668F">Capacity</td><td><b>{row['Capacity (MW)']:.1f} MW AC</b> {f"/ {row['DC Capacity (MW)']:.1f} DC" if pd.notna(row['DC Capacity (MW)']) else ""}</td></tr>
    <tr><td style="color:#6B668F">Status</td><td>{row['Detailed Status']}</td></tr>
    <tr><td style="color:#6B668F">Owner (EIA)</td><td>{own or "unknown — step 1 of playbook"}</td></tr>
    <tr><td style="color:#6B668F">Age</td><td>{row['Age (yrs)'] if pd.notna(row['Age (yrs)']) else '—'} yrs</td></tr>
    <tr><td style="color:#6B668F">CF (12m / fcst)</td><td>{f"{row['CF (12m)']*100:.1f}%" if pd.notna(row['CF (12m)']) else '—'} / {f"{row['CF (fcst 10y)']*100:.1f}%" if pd.notna(row['CF (fcst 10y)']) else '—'}</td></tr>
    <tr><td style="color:#6B668F">Contract</td><td>{f"{row['Contract Price ($/MWh)']:.0f} $/MWh" if pd.notna(row['Contract Price ($/MWh)']) else '—'}{f" · ends {str(row['Contract Termination Date'])[:10]}" if pd.notna(row['Contract Termination Date']) else ""}</td></tr>
    <tr><td style="color:#6B668F">Queue</td><td>{row['Queue ID'] if pd.notna(row['Queue ID']) else '—'} · {row['Queue Cycle'] if pd.notna(row['Queue Cycle']) else ''}</td></tr>
    <tr><td style="color:#6B668F">Why flagged</td><td>{row['Why']}</td></tr>
    </table></div>""", unsafe_allow_html=True)

            # >>> NOFAR-ADD: full attribute sheet from the merged Orennia exports
            _ATTR_GROUPS = {
                "Identification": ["Generator ID", "Generator Name", "Owner", "Parent Company",
                                   "Parent Company 2", "EIA Plant ID", "EIA Generator ID",
                                   "EIA Unit Code", "FERC Docket ID"],
                "Equipment & technology": ["Power Project Type", "Equipment Manufacturer",
                                        "Equipment Model", "Panel Type", "Battery Type",
                                        "Storage Duration (Hours)", "Storage Energy Rating (MWh)",
                                        "Number of Turbines (Number)", "Wind Turbine Capacity (kW)",
                                        "Capex Per Watt ($/W)", "EPC"],
                "Incentives & siting": ["PTC/ITC", "Native American Lands",
                                        "Low Income Communities",
                                        "Retired Coal Facilities Energy Communities",
                                        "Behind the Meter", "CCUS Status"],
                "Interconnection": ["Balancing Authority Code", "ISO", "Transmission Owner",
                                  "Point of Interconnection", "Connection Voltage (kV)",
                                  "Queue ID", "Queue Cycle", "Queue Date",
                                  "Interconnection Service Type",
                                  "Interconnection Cost Total ($)", "IX Cost $/kW"],
                "Contract": ["Contract Type", "Contract Offtaker", "Contract Offtaker Type",
                             "Contract Price Type", "Contract Price ($/MWh)",
                             "Contract Price ($/kW-month)", "Contract Capacity (MW)",
                             "Contract Term Years (Year)", "Contract Execution Date",
                             "Contract Termination Date", "Contract Delivery Location"],
                "Dates & performance": ["Power Project Status", "Detailed Status",
                                       "Chance of Success (Percentage)", "IRR (Percentage)",
                                       "First Power Date", "Reported First Power Date",
                                       "Estimated Retirement Date", "Reported Retirement Date",
                                       "Repowered", "Repower Date", "Lifetime Capacity Factor",
                                       "CF (12m)", "CF (prev 12m)", "CF Trend (pp)",
                                       "CF (fcst 10y)", "Has Generation History"],
            }
            with st.expander("📋 Full project sheet (all Orennia fields)"):
                _hide_empty = st.checkbox("Hide empty fields", value=True, key=f"he_{sel}")
                for _grp, _cols in _ATTR_GROUPS.items():
                    _rows = []
                    for _c in _cols:
                        if _c not in row.index:
                            continue
                        _v = row[_c]
                        _empty = pd.isna(_v) or str(_v).strip() in ("", "nan", "NaT")
                        if _empty and _hide_empty:
                            continue
                        if isinstance(_v, pd.Timestamp):
                            _v = _v.strftime("%Y-%m-%d")
                        _rows.append({"Field": _c, "Value": "—" if _empty else str(_v)})
                    if _rows:
                        st.markdown(f"**{_grp}**")
                        st.dataframe(pd.DataFrame(_rows), hide_index=True,
                                     use_container_width=True, height=min(35 * len(_rows) + 38, 320))
            # <<< NOFAR-ADD

            if pd.notna(row["Latitude (Degrees)"]):
                mf = px.scatter_mapbox(pd.DataFrame([{"lat": row["Latitude (Degrees)"], "lon": row["Longitude (Degrees)"],
                                                      "n": row["Power Project Name"], "mw": row["Capacity (MW)"]}]),
                                       lat="lat", lon="lon", size="mw", hover_name="n",
                                       color_discrete_sequence=[INDIGO], zoom=9, height=230)
                mf.update_layout(mapbox_style="open-street-map", margin=dict(l=0, r=0, t=0, b=0), showlegend=False)
                mf = add_nofar_layer(mf, True)
                # NOFAR-ADD: radius circles around retiring thermal plants near this target
                if isinstance(TH_DET, pd.DataFrame) and len(TH_DET) and "Generator ID" in TH_DET.columns:
                    for _, _t in TH_DET[TH_DET["Generator ID"] == sel].iterrows():
                        _la, _lo = geo_signals.circle_polygon(_t["lat"], _t["lon"], TH_R)
                        mf.add_trace(go.Scattermapbox(lat=_la, lon=_lo, mode="lines", fill="toself",
                            fillcolor="rgba(244,200,67,0.10)", line=dict(color="rgba(244,200,67,0.55)"),
                            hoverinfo="skip", showlegend=False))
                st.plotly_chart(mf, use_container_width=True, config={"displayModeBar": False})
            mo = D["m"][D["m"]["Generator ID"] == sel].sort_values("Date").tail(36)
            if len(mo) > 3:
                sp = px.area(mo, x="Date", y="Capacity Factor (Number)", color_discrete_sequence=[INDIGO])
                sp.update_layout(height=150, margin=dict(l=0, r=0, t=4, b=0), plot_bgcolor="white",
                                 font_family="Inter", yaxis_tickformat=".0%", yaxis_title=None, xaxis_title=None)
                sp.update_traces(line_width=2)
                st.markdown('<div class="sub">Monthly capacity factor (last 36m actuals)</div>', unsafe_allow_html=True)
                st.plotly_chart(sp, use_container_width=True, config={"displayModeBar": False})

    with right:
        if not tt.empty:
            st.markdown('<div class="sect">Action playbook</div><div class="sub">Exact link → what to do → what to verify → what we have vs lack.</div>', unsafe_allow_html=True)
            ctx = engine.build_playbook_context(row, scr, D.get("duke_queue"), D.get("restrictions"), D.get("contested"))
            for s in actions.generate_playbook(row, row["_fired"], ctx):
                lk = f'<a href="{s["link"]}" target="_blank">{s["link"]}</a>' if s["link"] else "—"
                st.markdown(f"""<div class="pstep"><div><div class="pnum">{s['step']}</div><div class="pline"></div></div>
    <div class="pbody"><b class="t">{s['title']}</b>
    <div class="row"><span class="k">Link</span> · {lk}</div>
    <div class="row"><span class="k">Do</span> · {s['do']}</div>
    <div class="row"><span class="k">Verify</span> · {s['verify']}</div>
    <div class="hl">{s['have_lack']}</div></div></div>""", unsafe_allow_html=True)

            st.divider()
            _sig_here = provenance[provenance["Generator ID"] == sel] \
                if len(provenance) and "Generator ID" in provenance.columns else None
            if _sig_here is not None and len(_sig_here):
                with st.expander(f"🔎 Distress signals ({len(_sig_here)}) — sources"):
                    st.dataframe(_sig_here[["match_type","signal_type","matched_on","title","date","source","url"]],
                                 hide_index=True, use_container_width=True,
                                 column_config={"url": st.column_config.LinkColumn("Source")})
            if ai_assistant is not None:
                ai_assistant.render_project_chat(row, _sig_here,
                                                 api_key=st.secrets.get("OPENAI_API_KEY"))

# ─────────────────────────────── MAP
# Glyph + colour per technology. Plotly's mapbox `marker.symbol` only works with a
# Mapbox token, so we draw a small dot plus a unicode glyph as text — that renders
# on the free open-street-map style and stays readable at any zoom.
TECH_STYLE = {
    "Solar":       {"glyph": "☀", "color": "#E0A500", "label": "Solar"},
    "Storage":     {"glyph": "▮", "color": "#4A2EE3", "label": "Storage / BESS"},
    "Wind":        {"glyph": "✦", "color": "#00A88F", "label": "Wind"},
    "Coal":        {"glyph": "▲", "color": "#4A4458", "label": "Coal"},
    "Natural Gas": {"glyph": "⬣", "color": "#C96A1B", "label": "Natural gas"},
}
FALLBACK_STYLE = {"glyph": "●", "color": "#8F7EF0", "label": "Other"}
NOFAR_COLOR   = "#FF2D95"   # Nofar sites: unique magenta, never reused
DC_COLOR      = "#00B7FF"   # data centers
THERMAL_COLOR = "#C1121F"   # retiring thermal
BA_PALETTE = ["#4A2EE3", "#E0A500", "#00A88F", "#C96A1B", "#B3261E", "#7A5AF8",
              "#0F9D58", "#D81B60", "#00838F", "#5D4037", "#455A64", "#8E24AA",
              "#F4511E"]


def _truthy(series):
    return series.astype(str).str.strip().str.lower().isin(["true", "yes", "y", "1"])


def _flag_label(frame, col, text):
    """Append the number of positives so a dead filter is obvious before you use it."""
    if col not in frame.columns:
        return f"{text} (n/a)"
    return f"{text} ({int(_truthy(frame[col]).sum())} yes)"


with tab_map:
    st.markdown(
        '<div class="sect">Asset map</div>'
        '<div class="sub">Each technology has its own glyph and colour · marker size = capacity · '
        'toggle layers for data centers, retiring thermal plants and utility territories.</div>',
        unsafe_allow_html=True)

    # ---------- filter panel ----------
    with st.expander("🔎 Map filters", expanded=True):
        r1 = st.columns(4)
        _state_opts = sorted(g["State"].dropna().unique())
        f_state = r1[0].multiselect("State", _state_opts, default=_state_opts, key="map_state")
        _ba_opts = sorted(g["Balancing Authority Code"].dropna().unique()) \
            if "Balancing Authority Code" in g.columns else []
        f_ba = r1[1].multiselect("Balancing authority (utility)", _ba_opts, default=_ba_opts,
                                 key="map_ba")
        _tcol = "Power Project Type" if "Power Project Type" in g.columns else "Technology"
        _ty_opts = sorted(g[_tcol].dropna().unique())
        f_type = r1[2].multiselect("Technology", _ty_opts, default=_ty_opts, key="map_type")
        f_status = r1[3].multiselect("Status", sorted(g["Detailed Status"].dropna().unique()),
                                     default=[], key="map_status")

        r2 = st.columns(4)
        _mwmax = int(np.nan_to_num(g["Capacity (MW)"].max(), nan=1000)) or 1000
        f_mw = r2[0].slider("Capacity (MW)", 0, _mwmax, (0, _mwmax), key="map_mw")
        f_score = r2[1].slider("Min opportunity score", 0.0,
                               float(max(_score_ceiling(top, default=10.0), 10.0)),
                               0.0, 0.5, key="map_score")
        _owner_opts = sorted(g["Owner"].dropna().unique()) if "Owner" in g.columns else []
        f_owner = r2[2].multiselect("Owner", _owner_opts, default=[], key="map_owner")
        marker_scale = r2[3].slider("Marker size", 4, 20, 9, key="map_msize")
        # Only these two Plotly mapbox styles are free. Carto's positron/dark-matter
        # now require an API key and render an "API KEY REQUIRED" watermark.
        _bm_label = st.selectbox("Base map", ["Streets (OpenStreetMap)", "Minimal (no tiles)"],
                                 key="map_basemap")
        _basemap = "open-street-map" if _bm_label.startswith("Streets") else "white-bg"

        # Siting flags — the label carries the number of positives, because Orennia
        # reports Native American Lands and Low Income Communities as false for every
        # project in this export. Selecting "Yes" there legitimately returns nothing.
        r3 = st.columns(4)
        f_native = r3[0].selectbox(_flag_label(g, "Native American Lands", "Native American lands"),
                                   ["Any", "Yes", "No"], key="map_native")
        f_lowinc = r3[1].selectbox(_flag_label(g, "Low Income Communities", "Low income community"),
                                   ["Any", "Yes", "No"], key="map_lowinc")
        f_coalec = r3[2].selectbox(_flag_label(g, "Retired Coal Facilities Energy Communities",
                                               "Retired-coal energy community"),
                                   ["Any", "Yes", "No"], key="map_coalec")
        f_incent = r3[3].multiselect("Incentive (PTC/ITC)",
                                     sorted(g["PTC/ITC"].dropna().unique())
                                     if "PTC/ITC" in g.columns else [], default=[],
                                     key="map_incent")

        r4 = st.columns(4)
        f_contract = r4[0].selectbox("Contract", ["Any", "Has offtaker", "No offtaker"],
                                     key="map_contract")
        f_signal = r4[1].selectbox("External distress signal", ["Any", "With signal", "Without"],
                                   key="map_signal")
        f_btm = r4[2].selectbox(_flag_label(g, "Behind the Meter", "Behind the meter"),
                                ["Any", "Yes", "No"], key="map_btm")
        only_opp = r4[3].toggle("Opportunities only", value=False, key="map_onlyopp")

        st.markdown("**Layers**")
        l = st.columns(6)
        show_nofar    = l[0].toggle("Nofar sites", value=True, key="map_l_nofar")
        show_dc       = l[1].toggle("Data centers", value=True, key="map_l_dc")
        show_thermal  = l[2].toggle("Retiring thermal", value=True, key="map_l_thermal")
        show_circles  = l[3].toggle("Radius circles", value=True, key="map_l_circles")
        show_utility  = l[4].toggle("Utility territory", value=False, key="map_l_utility")
        show_restricted_pois = l[5].toggle("Restricted POIs", value=False, key="map_l_poi")

    # ---------- apply filters ----------
    mm = g.dropna(subset=["Latitude (Degrees)", "Longitude (Degrees)"]).copy()
    mm = mm.merge(top[["Generator ID", "Opportunity Score"]], on="Generator ID", how="left")
    mm["Opportunity Score"] = pd.to_numeric(mm["Opportunity Score"], errors="coerce").fillna(0)

    def _yn(frame, col, choice):
        if choice == "Any" or col not in frame.columns:
            return frame
        t = _truthy(frame[col])
        return frame[t] if choice == "Yes" else frame[~t]

    if f_state: mm = mm[mm["State"].isin(f_state)]
    if f_ba and "Balancing Authority Code" in mm.columns:
        mm = mm[mm["Balancing Authority Code"].isin(f_ba)]
    if f_type:   mm = mm[mm[_tcol].isin(f_type)]
    if f_status: mm = mm[mm["Detailed Status"].isin(f_status)]
    if f_owner:  mm = mm[mm["Owner"].isin(f_owner)]
    if f_incent and "PTC/ITC" in mm.columns:
        mm = mm[mm["PTC/ITC"].isin(f_incent)]
    mm = mm[mm["Capacity (MW)"].between(f_mw[0], f_mw[1])]
    mm = mm[mm["Opportunity Score"] >= f_score]
    mm = _yn(mm, "Native American Lands", f_native)
    mm = _yn(mm, "Low Income Communities", f_lowinc)
    mm = _yn(mm, "Retired Coal Facilities Energy Communities", f_coalec)
    mm = _yn(mm, "Behind the Meter", f_btm)
    if f_contract == "Has offtaker":
        mm = mm[mm["Contract Offtaker"].notna()]
    elif f_contract == "No offtaker":
        mm = mm[mm["Contract Offtaker"].isna()]
    if f_signal != "Any" and isinstance(provenance, pd.DataFrame) and len(provenance) \
            and "Generator ID" in provenance.columns:
        flagged = set(provenance["Generator ID"])
        mm = mm[mm["Generator ID"].isin(flagged)] if f_signal == "With signal" \
            else mm[~mm["Generator ID"].isin(flagged)]
    if only_opp:
        mm = mm[mm["Opportunity Score"] >= max(THRESHOLD, 1e-9)]

    st.caption(f"{len(mm)} projects shown · {mm['Capacity (MW)'].sum():,.0f} MW")
    for _c, _lbl, _ch in [("Native American Lands", "Native American lands", f_native),
                          ("Low Income Communities", "Low income community", f_lowinc)]:
        if _ch == "Yes" and _c in g.columns and int(_truthy(g[_c]).sum()) == 0:
            st.warning(f"Orennia reports **{_lbl} = false for every project** in this "
                       f"export, so this filter can never return a result. Set it back to *Any*.")

    fig = go.Figure()

    # ---------- utility (balancing authority) territories ----------
    # Approximated as the convex hull of each BA's projects. This sketches the
    # operating footprint; it is NOT an official service-territory boundary.
    if show_utility and "Balancing Authority Code" in mm.columns:
        for i, (ba, grp) in enumerate(mm.groupby("Balancing Authority Code")):
            ring = geo_signals.convex_hull(
                zip(grp["Longitude (Degrees)"], grp["Latitude (Degrees)"]))
            if len(ring) < 4:
                continue
            col = BA_PALETTE[i % len(BA_PALETTE)]
            r, gg, b = int(col[1:3], 16), int(col[3:5], 16), int(col[5:7], 16)
            fig.add_trace(go.Scattermapbox(
                lat=[p[1] for p in ring], lon=[p[0] for p in ring],
                mode="lines", fill="toself",
                fillcolor=f"rgba({r},{gg},{b},0.07)",
                line=dict(color=f"rgba({r},{gg},{b},0.55)", width=2),
                name=f"{ba} territory",
                hovertemplate=f"<b>{ba}</b> — {scope.BA_UTILITY.get(ba, 'utility')}"
                              f"<br>{len(grp)} projects<extra></extra>"))

    # ---------- one trace per technology: small dot + glyph ----------
    _mwv = pd.to_numeric(mm["Capacity (MW)"], errors="coerce").fillna(0)
    _mwmax_v = max(float(_mwv.max()), 1.0)
    for tech, grp in mm.groupby(_tcol):
        stl = TECH_STYLE.get(str(tech), FALLBACK_STYLE)
        gmw = pd.to_numeric(grp["Capacity (MW)"], errors="coerce").fillna(0)
        sizes = (marker_scale * 0.55 + marker_scale * (gmw / _mwmax_v) ** 0.5).clip(4, 30)
        hov = ("<b>%{customdata[0]}</b><br>" + str(tech) +
               " · %{customdata[1]:.1f} MW<br>%{customdata[2]}<br>"
               "Owner: %{customdata[3]}<br>%{customdata[4]} County, %{customdata[5]}"
               " · BA %{customdata[6]}<br>Score: %{customdata[7]:.1f}<extra></extra>")
        cd = np.stack([
            grp["Power Project Name"].astype(str), gmw,
            grp["Detailed Status"].astype(str),
            grp.get("Owner", pd.Series("—", index=grp.index)).fillna("—").astype(str),
            grp["County"].astype(str), grp["State"].astype(str),
            grp.get("Balancing Authority Code", pd.Series("—", index=grp.index)).fillna("—").astype(str),
            grp["Opportunity Score"].astype(float)], axis=-1)
        fig.add_trace(go.Scattermapbox(
            lat=grp["Latitude (Degrees)"], lon=grp["Longitude (Degrees)"],
            mode="markers+text",
            marker=dict(size=sizes, color=stl["color"], opacity=0.45),
            text=[stl["glyph"]] * len(grp), textposition="middle center",
            textfont=dict(size=max(9, marker_scale), color=stl["color"]),
            name=f'{stl["glyph"]}  {stl["label"]}',
            customdata=cd, hovertemplate=hov))

    # ---------- data centers + their radius ----------
    if show_dc:
        _dcf = DATA / "data_centers.parquet"
        if _dcf.exists():
            _dc = pd.read_parquet(_dcf).dropna(
                subset=["Latitude (Degrees)", "Longitude (Degrees)"])
            if f_state and "State" in _dc.columns:
                _dc = _dc[_dc["State"].isin(f_state)]
            if len(_dc):
                _dmw = pd.to_numeric(_dc.get("Power Capacity (MW)"), errors="coerce").fillna(0)
                fig.add_trace(go.Scattermapbox(
                    lat=_dc["Latitude (Degrees)"], lon=_dc["Longitude (Degrees)"],
                    mode="markers+text",
                    marker=dict(size=(marker_scale * 0.6
                                      + marker_scale * (_dmw / max(_dmw.max(), 1)) ** 0.5).clip(4, 26),
                                color=DC_COLOR, opacity=0.5),
                    text=["▣"] * len(_dc), textposition="middle center",
                    textfont=dict(size=max(9, marker_scale), color=DC_COLOR),
                    name="▣  Data centers",
                    customdata=np.stack([_dc.get("Name", pd.Series("", index=_dc.index)).astype(str),
                                         _dmw], axis=-1),
                    hovertemplate="<b>%{customdata[0]}</b><br>Data center · "
                                  "%{customdata[1]:.0f} MW<extra></extra>"))
                if show_circles:
                    for _, _d in _dc.head(80).iterrows():
                        _la, _lo = geo_signals.circle_polygon(
                            _d["Latitude (Degrees)"], _d["Longitude (Degrees)"], DC_R)
                        fig.add_trace(go.Scattermapbox(
                            lat=_la, lon=_lo, mode="lines", fill="toself",
                            fillcolor="rgba(0,183,255,0.07)",
                            line=dict(color="rgba(0,183,255,0.40)", width=1),
                            hoverinfo="skip", showlegend=False))

    # ---------- retiring thermal + their radius ----------
    if show_thermal and "Is Thermal" in G_ALL.columns:
        _th = G_ALL[G_ALL["Is Thermal"].fillna(False)].dropna(
            subset=["Latitude (Degrees)", "Longitude (Degrees)"])
        if "Retirement Year" in _th.columns:
            _th = _th[_th["Retirement Year"] >= TH_YR]
        if f_state and "State" in _th.columns:
            _th = _th[_th["State"].isin(f_state)]
        if TH_TY and "Power Project Type" in _th.columns:
            _th = _th[_th["Power Project Type"].isin(TH_TY)]
        if len(_th):
            _tmw = pd.to_numeric(_th["Capacity (MW)"], errors="coerce").fillna(0)
            fig.add_trace(go.Scattermapbox(
                lat=_th["Latitude (Degrees)"], lon=_th["Longitude (Degrees)"],
                mode="markers+text",
                marker=dict(size=(marker_scale * 0.6
                                  + marker_scale * (_tmw / max(_tmw.max(), 1)) ** 0.5).clip(4, 26),
                            color=THERMAL_COLOR, opacity=0.45),
                text=["▲"] * len(_th), textposition="middle center",
                textfont=dict(size=max(9, marker_scale), color=THERMAL_COLOR),
                name=f"▲  Retiring thermal (≥{TH_YR})",
                customdata=np.stack([_th["Power Project Name"].astype(str),
                                     _th["Power Project Type"].astype(str), _tmw,
                                     _th["Retirement Year"].astype("Int64").astype(str)], axis=-1),
                hovertemplate="<b>%{customdata[0]}</b><br>%{customdata[1]} · "
                              "%{customdata[2]:.0f} MW<br>Retires %{customdata[3]}<extra></extra>"))
            if show_circles:
                for _, _t in _th.head(80).iterrows():
                    _la, _lo = geo_signals.circle_polygon(
                        _t["Latitude (Degrees)"], _t["Longitude (Degrees)"], TH_R)
                    fig.add_trace(go.Scattermapbox(
                        lat=_la, lon=_lo, mode="lines", fill="toself",
                        fillcolor="rgba(193,18,31,0.06)",
                        line=dict(color="rgba(193,18,31,0.35)", width=1),
                        hoverinfo="skip", showlegend=False))

    # ---------- Nofar sites (unique colour, always on top) ----------
    if show_nofar:
        fig.add_trace(go.Scattermapbox(
            lat=NOFAR_SITES["lat"], lon=NOFAR_SITES["lon"], mode="markers+text",
            marker=dict(size=max(12, marker_scale + 4), color=NOFAR_COLOR, opacity=0.95),
            text=["★"] * len(NOFAR_SITES), textposition="top center",
            textfont=dict(size=16, color=NOFAR_COLOR, family="Space Grotesk"),
            name="★  Nofar sites",
            customdata=NOFAR_SITES["name"],
            hovertemplate="<b>Nofar · %{customdata}</b><extra></extra>"))

    # ---------- restricted POIs ----------
    if show_restricted_pois:
        _rz = D.get("red_zone", pd.DataFrame()).copy()
        if _rz.empty:
            st.caption("No restricted-POI dataset loaded (Duke NC/SC only).")
        else:
            _lk = {str(c).strip().lower(): c for c in _rz.columns}
            _latc = next((_lk[n] for n in ["latitude", "lat"] if n in _lk), None)
            _lonc = next((_lk[n] for n in ["longitude", "lon", "lng", "long"] if n in _lk), None)
            _namc = next((_lk[n] for n in ["substation", "name", "poi"] if n in _lk), None)
            if _latc and _lonc:
                _rz = _rz.dropna(subset=[_latc, _lonc])
                fig.add_trace(go.Scattermapbox(
                    lat=_rz[_latc], lon=_rz[_lonc], mode="markers+text",
                    marker=dict(size=9, color="#D7263D", opacity=0.7),
                    text=["■"] * len(_rz), textposition="middle center",
                    textfont=dict(size=10, color="#D7263D"),
                    name="■  Restricted POIs",
                    hovertext=_rz[_namc] if _namc else None, hoverinfo="text"))
            else:
                st.caption("Restricted-POI file has no coordinate columns.")

    if mm.empty and not show_thermal:
        st.warning("No projects match these filters.")
    else:
        _clat = float(mm["Latitude (Degrees)"].mean()) if len(mm) else 34.5
        _clon = float(mm["Longitude (Degrees)"].mean()) if len(mm) else -81.0
        fig.update_layout(
            mapbox=dict(style=_basemap, zoom=5.3,
                        center={"lat": _clat, "lon": _clon}),
            margin=dict(l=0, r=0, t=0, b=0), height=720, font_family="Inter",
            legend=dict(bgcolor="rgba(255,255,255,0.9)", bordercolor="#E6E2FA",
                        borderwidth=1, itemsizing="constant",
                        yanchor="top", y=0.99, xanchor="left", x=0.01),
            hoverlabel=dict(bgcolor="white", font_size=12))
        st.plotly_chart(fig, use_container_width=True,
                        config={"displayModeBar": True, "scrollZoom": True})

        st.caption("Glyphs: ☀ solar · ▮ storage · ✦ wind · ▲ thermal · ▣ data center · "
                   "★ Nofar. Utility territories are convex hulls of each balancing "
                   "authority's projects — an approximation, not an official boundary.")

        with st.expander(f"📄 Table of the {len(mm)} projects shown"):
            _cols = [c for c in ["Power Project Name", "Power Project Type", "Capacity (MW)",
                                 "Detailed Status", "Owner", "Parent Company", "County",
                                 "State", "Balancing Authority Code", "PTC/ITC",
                                 "Opportunity Score"] if c in mm.columns]
            st.dataframe(mm[_cols].sort_values("Opportunity Score", ascending=False),
                         hide_index=True, use_container_width=True, height=380)


# ─────────────────────────────── WITHDRAWALS
with tab_withdrawals:
    wd = scr.get("withdrawn_queue", pd.DataFrame())
    st.markdown(f'<div class="sect">Withdrawn from Duke queue — {len(wd)} solar/battery positions</div>'
                '<div class="sub">Every row = a developer who sank deposits and walked. Color = # withdrawals per county.</div>',
                unsafe_allow_html=True)

    NC_SC_FIPS = {
        "robeson":"37155","cumberland":"37051","bladen":"37017","sampson":"37163","duplin":"37061",
        "columbus":"37047","harnett":"37085","johnston":"37101","wayne":"37191","scotland":"37165",
        "richmond":"37153","hoke":"37093","moore":"37125","lee":"37105","nash":"37127","wilson":"37195",
        "halifax":"37083","northampton":"37131","edgecombe":"37065","pitt":"37147","beaufort":"37013",
        "bertie":"37015","hertford":"37091","martin":"37117","greene":"37079","lenoir":"37107",
        "craven":"37049","onslow":"37133","anson":"37007","union":"37179","stanly":"37167",
        "montgomery":"37123","chatham":"37037","person":"37145","granville":"37077","warren":"37185",
        "franklin":"37069","vance":"37181","caswell":"37033","rockingham":"37157","guilford":"37081",
        "alamance":"37001",
        "marlboro":"45069","dillon":"45033","marion":"45067","horry":"45051","florence":"45041",
        "darlington":"45031","chesterfield":"45025","lancaster":"45057","york":"45091","sumter":"45085",
        "clarendon":"45027","williamsburg":"45089","georgetown":"45043","berkeley":"45015",
        "orangeburg":"45075","kershaw":"45055",
    }

    @st.cache_data(show_spinner=False)
    def load_counties():
        import json, urllib.request
        with urllib.request.urlopen("https://raw.githubusercontent.com/plotly/datasets/master/geojson-counties-fips.json") as r:
            return json.load(r)

    if len(wd):
        wc = wd.copy()
        wc["cty"] = wc["county"].astype(str).str.lower().str.replace(" county","",regex=False).str.strip()
        agg = wc.groupby("cty").agg(withdrawals=("queue_id","count"), mw=("mw","sum")).reset_index()
        agg["fips"] = agg["cty"].map(NC_SC_FIPS)
        mapped = agg.dropna(subset=["fips"])
        st.markdown(f'<div class="sub">{int(mapped["withdrawals"].sum())} withdrawals across {len(mapped)} counties. '
                    f'Counties without a shape are in the list below.</div>', unsafe_allow_html=True)

        if len(mapped):
            geo = load_counties()
            fig_w = px.choropleth_mapbox(
                mapped, geojson=geo, locations="fips", color="withdrawals",
                color_continuous_scale=["#F6C9C4", "#E88A82", "#B3261E", "#7A140F"],
                range_color=(1, int(mapped["withdrawals"].max())),
                mapbox_style="open-street-map", zoom=6.1, center={"lat":35.2,"lon":-79.2},
                opacity=0.75, height=640, hover_name="cty",
                hover_data={"withdrawals":True, "mw":":.0f", "fips":False})
            fig_w.add_scattermapbox(
                lat=NOFAR_SITES["lat"], lon=NOFAR_SITES["lon"], mode="markers+text",
                marker=dict(size=20, color=GOLD), text=["★ "+n for n in NOFAR_SITES["name"]],
                textposition="top center", textfont=dict(color=DEEP, size=13),
                name="Nofar sites", hoverinfo="text")
            fig_w.update_layout(margin=dict(l=0,r=0,t=0,b=0), coloraxis_colorbar_title="Withdrawals")
            st.plotly_chart(fig_w, use_container_width=True, config={"displayModeBar": False})

        st.markdown('<div class="sect" style="margin-top:12px">Withdrawals by county — click to expand</div>', unsafe_allow_html=True)
        for cty in agg.sort_values("withdrawals", ascending=False)["cty"]:
            rows = wc[wc["cty"] == cty]
            with st.expander(f"{cty.title()} County — {len(rows)} withdrawals · {rows['mw'].sum():.0f} MW"):
                st.dataframe(rows[["queue_id","cluster_cycle","fuel_tech","mw","state","queue_date"]],
                             use_container_width=True, hide_index=True)
    else:
        st.info("No withdrawals found in the Duke queue file.")

# ─────────────────────────────── ACTION QUEUE
with tab_action_queue:
    st.markdown('<div class="sect">Action Queue</div>'
                '<div class="sub">Only projects above threshold, each with a recommended action, '
                'the signals that fired it, and the source link to verify before contacting.</div>',
                unsafe_allow_html=True)
    aq = top.copy()
    aq["Owner"] = aq["Generator ID"].map(lambda i: (own_by_id.get(i) or {}).get("current_owner") or "—")
    aq["Recommended action"] = aq.apply(lambda r: distress_scan.recommend_action(
        r["_fired"], own_by_id.get(r["Generator ID"]),
        dsig[dsig["company"] == r["Power Project Name"]]["signal_type"].tolist() if len(dsig) else []), axis=1)
    aq["Source"] = aq["Power Project Name"].map(
        lambda n: (dsig[dsig["company"] == n]["url"].iloc[0]
                   if len(dsig) and (dsig["company"] == n).any()
                   and dsig[dsig["company"] == n]["url"].iloc[0] else ""))
    show = aq[["Power Project Name", "Owner", "County", "State", "Capacity (MW)",
               "Opportunity Score", "Recommended action", "Source", "Why"]]
    st.dataframe(show, use_container_width=True, height=460, hide_index=True,
                 column_config={**FMT, "Source": st.column_config.LinkColumn("Source")})

    st.markdown('<div class="sect" style="margin-top:14px">Company distress ranking</div>'
                '<div class="sub">Decay-weighted sum of active signals per company (recent = heavier).</div>',
                unsafe_allow_html=True)
    if len(dcomp):
        st.dataframe(dcomp, use_container_width=True, hide_index=True)
    else:
        st.info("No distress signals yet — run the live updates (media, CourtListener) in Data & updates.")

    st.download_button("⬇️ Action Queue CSV", show.to_csv(index=False), key="btn_dl_queue",
                       file_name="action_queue.csv", mime="text/csv")

# ─────────────────────────────── TEAM HUB
with tab_team_hub:
    team_hub.render({"INDIGO": INDIGO, "GOLD": GOLD, "DEEP": DEEP, "INK": INK})


# ─────────────────────────────── SIGNALS
with tab_live_signals:
    def cardlist(path, kind):
        if not os.path.exists(path):
            st.markdown(f'<div class="card"><b>{kind}</b><br><span class="sub">Not fetched yet — use Data & updates.</span></div>', unsafe_allow_html=True); return
        dd = pd.read_parquet(path)
        for _, r in dd.head(12).iterrows():
            title = r.get("title", r.get("case", ""))
            meta = r.get("published", r.get("filed", "")) or ""
            src = r.get("source", r.get("court", r.get("query", "")))
            st.markdown(f"""<div class="card" style="padding:12px 18px">
<span class="badge b-sig">{src}</span> <span class="sub">{meta}</span><br>
<a href="{r.get('link','')}" target="_blank" style="color:{INK};font-weight:600;text-decoration:none">{title}</a></div>""",
                        unsafe_allow_html=True)

    c1, c2, c3 = st.columns(3)
    with c1: st.markdown('<div class="sect">Media</div>', unsafe_allow_html=True); cardlist(f"{DATA}/media.parquet", "Trade media")
    with c2: st.markdown('<div class="sect">Bankruptcies</div>', unsafe_allow_html=True); cardlist(f"{DATA}/courtlistener.parquet", "CourtListener")
    with c3: st.markdown('<div class="sect">FERC filings</div>', unsafe_allow_html=True); cardlist(f"{DATA}/ferc.parquet", "FERC eLibrary")

    st.markdown('<div class="sect" style="margin-top:16px">Company stress (web search)</div>'
                '<div class="sub">Google News hits per NC/SC company. Verify each before acting — headlines ≠ confirmation.</div>', unsafe_allow_html=True)
    if os.path.exists(f"{DATA}/web_signals.parquet"):
        ws = pd.read_parquet(f"{DATA}/web_signals.parquet")
        for _, r in ws.head(20).iterrows():
            st.markdown(f"""<div class="card" style="padding:12px 18px">
<span class="badge b-warn">{r['signal_type']}</span><span class="badge b-sig">{r['company']}</span>
<span class="sub">{r['published']}</span><br>
<a href="{r['link']}" target="_blank" style="color:{INK};font-weight:600;text-decoration:none">{r['title']}</a></div>""",
                        unsafe_allow_html=True)
    else:
        st.info("Run 'Scan web' in Data & updates to populate company stress signals.")

# ─────────────────────────────── DATA & UPDATES
with tab_date_updates:
    st.markdown('<div class="sect">Live sources — one-click update</div><div class="sub">These fetch from the internet now. Everything else below is static by design (refresh by committing new files to the repo).</div>', unsafe_allow_html=True)
    cols = st.columns(4)
    labels = {"media_rss": ("Trade media RSS", fetch_media), "ferc_elibrary": ("FERC eLibrary", fetch_ferc),
              "courtlistener": ("CourtListener", fetch_courtlistener), "eia860m": ("EIA-860M ownership", fetch_eia860m)}
    for (k, (lbl, fn)), c in zip(labels.items(), cols):
        with c:
            m = reg.get(k, {})
            lu = m.get("last_updated") or "never"
            st.markdown(f'<div class="card" style="text-align:center"><b>{lbl}</b><br><span class="sub">last: {lu} · {m.get("rows",0)} rows</span></div>', unsafe_allow_html=True)
            if st.button(f"Update", key=f"u{k}", use_container_width=True):
                with st.spinner("Fetching..."): fn()
                st.cache_data.clear(); st.rerun()
    if st.button("Update all four", type="primary", key="btn_update_all"):
        with st.spinner("Fetching all live sources..."):
            fetch_media(); fetch_ferc(); fetch_courtlistener(); fetch_eia860m()
        st.cache_data.clear(); st.rerun()
    if st.button("🔎 Scan web (Google News)", key="btn_scan_web"):
        with st.spinner("Searching news for NC/SC company stress..."):
            ws = web_signals.scan_web_signals(g, ownership)
            ws.to_parquet(f"{DATA}/web_signals.parquet", index=False)
        st.cache_data.clear(); st.rerun()
    st.markdown('<div class="sect" style="margin-top:14px">Distress scan</div>'
                '<div class="sub">Searches per ENTITY (owner / parent), never per project. '
                "CourtListener's free tier allows ~5 requests per minute, so each entity "
                "costs about 12 seconds — pick the scope accordingly.</div>",
                unsafe_allow_html=True)
    dcol = st.columns([1, 1, 1, 1])
    _dm = dcol[0].slider("Entities to scan", 5, 60, 20, 5, key="ds_max")
    _d_news = dcol[1].toggle("News", value=True, key="ds_news")
    _d_cl   = dcol[2].toggle("Bankruptcy", value=True, key="ds_cl")
    _d_lien = dcol[3].toggle("Liens (slow)", value=False, key="ds_lien")

    _eta = (_dm * 12 * ((1 if _d_cl else 0) + (1 if _d_lien else 0))
            + (_dm * 1.5 if _d_news else 0) + 20)
    st.caption(f"County signals and WARN layoffs always run (fast). "
               f"Estimated time: **~{_eta/60:.0f} min**. Keep this tab open.")

    if st.button("🧭 Run distress scan", key="btn_update_distress", type="primary"):
        _bar = st.progress(0.0, text="Starting...")
        with st.status("Distress scan running...", expanded=True) as _stt:
            try:
                _n, _ne = fetch_distress(max_entities=_dm, do_news=_d_news,
                                         do_courtlistener=_d_cl, do_liens=_d_lien,
                                         status=_stt, bar=_bar)
                _stt.update(label=f"Done — {_n} signals across {_ne} entities",
                            state="complete")
            except Exception as _e:
                _stt.update(label=f"Failed: {_e}", state="error")
        st.cache_data.clear(); st.rerun()

    st.markdown('<div class="sect" style="margin-top:18px">Static datasets in this build</div>', unsafe_allow_html=True)
    chips = {"Orennia projects": "Jul 2026 · 1,271 generators", "Duke cluster queue": "Mar 2026 · incl. 249 withdrawals",
             "OASIS FERC posting": "Jun 2026 · customer names", "DEP Red Zone": "2022 · 245 substations",
             "Sabin restrictions": "2025 · NC/SC solar", "Contested projects": "2025 · NC/SC solar",
             "NC WARN": "Jul 2026 · 52 notices", "SC WARN": "Jul 2026 · 26 notices"}
    st.markdown('<div class="card">' + "".join(
        f'<span class="badge b-sig" style="font-size:12.5px;padding:6px 14px">{k} — {v}</span>' for k, v in chips.items())
        + '<div class="sub" style="margin-top:8px">To refresh a static dataset: replace its file in <code>data_uploads/</code> (run parsers via <code>refresh_static.py</code>) and push to GitHub — Streamlit Cloud redeploys automatically.</div></div>',
        unsafe_allow_html=True)

# ─────────────────────────────── SCORE & METHODOLOGY
with tab_score_methodology:
    st.markdown('<div class="sect">How the score is calculated</div>'
                '<div class="sub">Weighted sum: each project passes through 9 filters ("screens"). '
                'For every rule it meets, it adds the weight assigned to that screen. It is a simple and auditable sum: '
                'the Why column lists exactly what contributed to the score. A project is classified as an OPPORTUNITY if its total ≥ the threshold.</div>',
                unsafe_allow_html=True)
    st.markdown(f'<div class="card"><b>Example:</b> a project with a PPA expiring in 3 years (+{weights["contract_cliff"]}) '
                f'and production 25% below forecast (+{weights["underperf"]}) '
                f'in a county with a moratorium ({weights["county_risk"]}) = score '
                f'{weights["contract_cliff"]+weights["underperf"]+weights["county_risk"]:.1f}.</div>', unsafe_allow_html=True)

    c1, c2 = st.columns([1, 2])
    with c1:
        st.markdown('<div class="sect">Settings (recalculate everything live)</div>', unsafe_allow_html=True)
        st.slider("Opportunity threshold (minimum score)", 0.0, 10.0, 0.5, 0.5, key="thr")
        for k, v in DW.items():
            st.slider(k, -3.0, 6.0, float(v), 0.5, key=f"w_{k}")
        st.caption(f"With these values: {len(top)} opportunities out of {len(g)} generators.")
        if st.button("Restore default values", key="btn_restore_weights"):
            for k in DW: st.session_state[f"w_{k}"] = float(DW[k])
            st.session_state["thr"] = 0.5; st.rerun()

    INFO = {
      "dev_distress": ("Development distress", "Project status is Suspended, Postponed, or Moved to another cluster.",
        "A developer freezing a project it already invested in (queue deposits, studies) is the classic motivated seller: usually prefers selling the position over losing it.",
        "'Detailed Status' column of the Orennia export."),
      "duke_withdrawn_match": ("Duke-confirmed withdrawal", "The project's Queue ID shows status WITHDRAWN in Duke's official queue file.",
        "Hardest distress evidence short of bankruptcy: the utility itself records that the developer abandoned the position after paying deposits and studies. Near-certain motivated seller.",
        "Join of Orennia 'Queue ID' vs Duke's cluster queue file (20260331_Cluster_QueueDEP.xlsx), status = Withdrawn. 100% Duke source, not Orennia."),
      "contract_cliff": ("Contract cliff (PPA)", "The power purchase agreement ends within ≤5 years, or already expired.",
        "Without a PPA the project reprices onto today's (lower) avoided-cost rate. The owner faces revenue uncertainty = a buying window before the reprice.",
        "'Contract Termination Date' and 'Contract Price' columns of Orennia."),
      "underperf": ("Underperformance", "Capacity factor fell ≥1.5pp year-over-year, OR actual CF is <80% of Orennia's forecast for that site.",
        "Falling output = equipment degradation, outages, or curtailment. A sick asset whose owner lacks repair capital is a discount-plus-repower candidate.",
        "Orennia's monthly actual generation series + Orennia's own forward forecast (same file)."),
      "ix_burden": ("Interconnection burden", "Assigned interconnection cost >$150/kW.",
        "Expensive grid upgrades kill project economics; the owner may sell the queue position rather than pay. For the buyer, negotiating leverage.",
        "'Interconnection Cost Physical/System Upgrade' columns of Orennia (only 33 projects carry them)."),
      "red_zone": ("Duke red zone", "The point of interconnection (POI) matches a substation on DEP's constrained-zone list.",
        "Duke declared those zones saturated: connecting there means long, costly upgrades. Dual signal: risk for new projects, scarcity (value) for already-connected positions.",
        "Text join: Orennia 'Point of Interconnection' vs Duke's DEP Red Zone file. ⚠️ Partial coverage: only ~236 of 1,271 generators carry POI text in Orennia."),
      "qf_rollup": ("Aging QF universe", "Operating, ≤5.5 MW, and ≥8 years old.",
        "This is NC's PURPA fleet: hundreds of small same-generation plants with fragmented owners and old contracts. Roll-up thesis: buy several, run as a portfolio, repower.",
        "Capacity, 'First Power Date' and status, from Orennia. 5.5 MW = NC's standard PURPA threshold."),
      "retirement": ("Retirement horizon", "Estimated retirement date within ≤5 years.",
        "A retiring site keeps its most valuable pieces: the interconnection and the land. Site/queue reuse play with new equipment.",
        "'Estimated Retirement Date' column of Orennia."),
      "late_stage": ("Late-stage pipeline", "In development (not operating) at a mature stage: interconnection agreement, engineering, or construction.",
        "De-risked projects are today's hottest commodity: nearly all development risk is behind them. Low weight because it's attractive, not distressed.",
        "Orennia 'Detailed Status' mapped to a 0-100 maturity ladder (Dev Stage Score ≥60)."),
      "withdrawal_cluster": ("County withdrawal cluster", "The county accumulates ≥50 MW withdrawn from Duke's queue.",
        "Where many projects die together there's usually a common cause (costly upgrades, saturation). Every owner in that zone faces the same pressure: an environment with multiple potential sellers. Low weight — it's context, not project-specific evidence.",
        "Sum of Withdrawn MW by county, from Duke's queue file. Source: Duke."),
      "warn_county": ("WARN in county", "An energy-relevant WARN notice (mass layoff/closure) exists in the same county.",
        "Weak but early signal of sector stress in the area: an EPC or electrical manufacturer closing nearby can foreshadow orphaned projects. Minimal weight: county context, not asset-specific.",
        "NC Commerce and SC DEW WARN portals (warn_nc / warn_sc files), keyword-filtered to energy. Source: state governments."),
      "county_risk": ("County risk (SUBTRACTS)", "The county has a recorded solar restriction/moratorium, or a history of contested/canceled projects.",
        "Not an opportunity — a warning. Local opposition can block repowering or expansion. Hence the negative weight: it penalizes the score without eliminating the project.",
        "Sabin Center 2025 files: Restrictions and Contested Projects, filtered to NC/SC + solar."),
    }
    with c2:
        st.markdown('<div class="sect">The 9 screens, explained</div>', unsafe_allow_html=True)
        for k, (nom, que, porque, fuente) in INFO.items():
            n = len(scr.get(k, []))
            st.markdown(f"""<div class="card"><b style="font-family:'Space Grotesk'">{nom}</b>
<span class="badge b-sig">weight {weights[k]:+.1f}</span><span class="badge b-sig">{n} hits</span>
<div class="row" style="margin-top:6px"><b>What it is:</b> {que}</div>
<div class="row"><b>Why it matters for M&A:</b> {porque}</div>
<div class="row" style="color:#6B668F"><b>Data source:</b> {fuente}</div></div>""", unsafe_allow_html=True)
