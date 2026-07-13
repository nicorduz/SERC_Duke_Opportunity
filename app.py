"""
Nofar SERC Deal Intelligence — Duke Carolinas (DEC + DEP) · professional MVP UI
"""
import json, os, io, base64
import numpy as np
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

from preprocess_orennia import load_and_reduce
import parsers, engine, actions

DATA, UP = "data", "data_uploads"
os.makedirs(DATA, exist_ok=True)
REG = os.path.join(DATA, "sources_registry.json")
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
@st.cache_data(show_spinner=False)
def load_all():
    d = {}
    d["g"] = pd.read_parquet(f"{DATA}/orennia_generators.parquet")
    d["m"] = pd.read_parquet(f"{DATA}/orennia_monthly.parquet")
    for k in ["duke_queue", "duke_oasis", "red_zone", "restrictions", "contested", "warn_nc", "warn_sc"]:
        p = f"{UP}/{k}.parquet"
        if os.path.exists(p): d[k] = pd.read_parquet(p)
    if os.path.exists(f"{DATA}/eia860m.parquet"): d["eia"] = pd.read_parquet(f"{DATA}/eia860m.parquet")
    return d

D = load_all()
g = D["g"]
scr = engine.opportunity_screens(g, D.get("eia"), D.get("duke_queue"),
                                 D.get("red_zone"), D.get("restrictions"), D.get("contested"))
DW = engine.DEFAULT_WEIGHTS
weights = {k: st.session_state.get(f"w_{k}", v) for k, v in DW.items()}
THRESHOLD = st.session_state.get("thr", 0.5)
top = engine.composite_score(g, scr, weights, THRESHOLD)
op = g[g["Is Operating"]]

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
            df = df[df[sc].isin(["NC", "SC"])]
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

tabs = st.tabs([ "Dashboard", "Targets & playbooks", "Map", "Withdrawals",
                "Live signals", "Data & updates" , "Score & Methodology"])

FMT = {"Capacity (MW)": st.column_config.NumberColumn("MW", format="%.1f"),
       "Opportunity Score": st.column_config.ProgressColumn("Score", min_value=0, max_value=float(top["Opportunity Score"].max() or 8), format="%.1f"),
       "CF (12m)": st.column_config.NumberColumn("CF 12m", format="percent"),
       "Age (yrs)": st.column_config.NumberColumn("Age", format="%.0f y")}

# ─────────────────────────────── DASHBOARD
with tabs[0]:
    a, b = st.columns([3, 2])
    with a:
        st.markdown('<div class="sect">Top opportunities</div><div class="sub">Composite of nine screens — every point decomposes in the Why column.</div>', unsafe_allow_html=True)
        st.dataframe(top[["Power Project Name", "County", "State", "Capacity (MW)",
                          "Detailed Status", "Opportunity Score", "Why"]].head(25),
                     use_container_width=True, height=430, column_config=FMT, hide_index=True)
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
with tabs[1]:
    left, right = st.columns([2, 3])
    with left:
        st.markdown('<div class="sect">Pick a target</div>', unsafe_allow_html=True)
        f1, f2 = st.columns(2)
        stt = f1.multiselect("State", ["NC", "SC"], default=["NC", "SC"], label_visibility="collapsed")
        minmw = f2.slider("Min MW", 0.0, 80.0, 0.0, 1.0, label_visibility="collapsed")
        tt = top[top["State"].isin(stt) & (top["Capacity (MW)"] >= minmw)]
        sel = st.selectbox("Target", tt["Generator ID"].head(80),
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

        if pd.notna(row["Latitude (Degrees)"]):
            mf = px.scatter_mapbox(pd.DataFrame([{"lat": row["Latitude (Degrees)"], "lon": row["Longitude (Degrees)"],
                                                  "n": row["Power Project Name"], "mw": row["Capacity (MW)"]}]),
                                   lat="lat", lon="lon", size="mw", hover_name="n",
                                   color_discrete_sequence=[INDIGO], zoom=9, height=230)
            mf.update_layout(mapbox_style="open-street-map", margin=dict(l=0, r=0, t=0, b=0), showlegend=False)
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

# ─────────────────────────────── MAP
with tabs[2]:
    st.markdown('<div class="sect">Asset map</div><div class="sub">Size = MW · color = opportunity score. Filter, hover, zoom.</div>', unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    stt = c1.multiselect("State ", ["NC", "SC"], default=["NC", "SC"])
    tech = c2.multiselect("Technology", sorted(g["Technology"].unique()), default=sorted(g["Technology"].unique()))
    only_opp = c3.toggle("Opportunities only", value=False)
    mm = g[g["State"].isin(stt) & g["Technology"].isin(tech)].dropna(subset=["Latitude (Degrees)", "Longitude (Degrees)"])
    mm = mm.merge(top[["Generator ID", "Opportunity Score"]], on="Generator ID", how="left")
    mm["Opportunity Score"] = mm["Opportunity Score"].fillna(0)
    rz_ids = set(scr["red_zone"]["Generator ID"])
    mm["Categoría"] = np.where(mm["Opportunity Score"] >= max(THRESHOLD, 1e-9), "Opportunity", "No Signal")
    if c3.toggle("POI Congested)"):
        mm.loc[mm["Generator ID"].isin(rz_ids) & (mm["Category"] == "Opportunity"),
               "Category"] = "Opportunity on POI Congested"
    if only_opp: mm = mm[mm["Category"] != "No Signal"]
    fig = px.scatter_mapbox(mm, lat="Latitude (Degrees)", lon="Longitude (Degrees)",
                            size="Capacity (MW)", color="Category",
                            color_discrete_map={"Sin señal": "#C7C4D9", "Opportunity": INDIGO,
                                                "Opportunity on POI Congested": GOLD},
                            hover_name="Power Project Name",
                            hover_data={"County": True, "Detailed Status": True,
                                        "Opportunity Score": ":.1f", "Capacity (MW)": ":.1f",
                                        "Latitude (Degrees)": False, "Longitude (Degrees)": False},
                            zoom=6.2, height=650)
    fig.update_layout(mapbox_style="open-street-map", margin=dict(l=0, r=0, t=0, b=0),
                      font_family="Inter", coloraxis_colorbar_title="Score")
    st.plotly_chart(fig, use_container_width=True)

# ─────────────────────────────── WITHDRAWALS
with tabs[3]:
    wd = scr.get("withdrawn_queue", pd.DataFrame())
    st.markdown(f'<div class="sect">Withdrawn from Duke queue — {len(wd)} solar/battery positions</div>'
                '<div class="sub">Every row = a developer who sank deposits and walked. Sorted by MW; group by county to find stress clusters.</div>', unsafe_allow_html=True)
    a, b = st.columns([3, 2])
    with a:
        st.dataframe(wd[["utility", "queue_id", "cluster_cycle", "fuel_tech", "mw", "county", "state", "queue_date"]],
                     use_container_width=True, height=520, hide_index=True)
    with b:
        byc = wd.groupby("county")["mw"].sum().sort_values(ascending=False).head(15).reset_index()
        f = px.bar(byc, x="mw", y="county", orientation="h", color_discrete_sequence=[INDIGO])
        f.update_layout(height=520, margin=dict(l=0, r=10, t=4, b=0), plot_bgcolor="white",
                        font_family="Inter", xaxis_title="Withdrawn MW", yaxis_title=None,
                        yaxis=dict(autorange="reversed"))
        st.plotly_chart(f, use_container_width=True, config={"displayModeBar": False})

# ─────────────────────────────── SIGNALS
with tabs[4]:
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

# ─────────────────────────────── DATA & UPDATES
with tabs[5]:
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
    if st.button("Update all four", type="primary"):
        with st.spinner("Fetching all live sources..."):
            fetch_media(); fetch_ferc(); fetch_courtlistener(); fetch_eia860m()
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
with tabs[6]:
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
        if st.button("Restore default values"):
            for k in DW: st.session_state[f"w_{k}"] = float(DW[k])
            st.session_state["thr"] = 0.5; st.rerun()

    INFO = {
      "dev_distress": ("Development distress", "The project is Suspended, Postponed, or Moved to another cluster.",
        "A developer that stops a project after already investing in it, such as queue deposits and studies, is a classic motivated seller: it will often prefer to sell the queue position rather than lose it.",
        "The 'Detailed Status' column from the Orennia export."),
      "contract_cliff": ("Contract expiration (PPA)", "The energy sales contract expires in ≤5 years or has already expired.",
        "Without a PPA, the project becomes exposed to repricing at the current, lower avoided-cost rate. The owner faces revenue uncertainty, creating an acquisition window before repricing.",
        "The 'Contract Termination Date' and 'Contract Price' columns from Orennia."),
      "underperf": ("Underperformance", "The capacity factor decreased by ≥1.5 percentage points compared with the previous year, OR the actual CF is <80% of Orennia's forecast for that site.",
        "Declining production may indicate equipment degradation, failures, or curtailment. An underperforming asset owned by a party without the capital to repair it may be acquired at a discount and repowered.",
        "Orennia's monthly actual-generation series and forward forecast from the same file."),
      "ix_burden": ("Interconnection burden", "Allocated interconnection cost >$150/kW.",
        "Expensive grid upgrades can destroy project economics, causing the owner to sell the queue position rather than pay the required costs. For the buyer, this provides negotiation leverage.",
        "Orennia's 'Interconnection Cost Physical/System Upgrade' columns. Only 33 projects include this information."),
      "red_zone": ("Duke red zone", "The point of interconnection (POI) matches a substation included in DEP's restricted-zone list.",
        "Duke has identified these zones as constrained: connecting there may require lengthy and expensive upgrades. This is a dual signal: higher risk for new projects and scarcity value for positions that are already connected.",
        "Text match between Orennia's 'Point of Interconnection' and Duke's DEP Red Zone file. ⚠️ Partial coverage: only approximately 236 of 1,271 generators include POI text in Orennia."),
      "qf_rollup": ("Aging QF universe", "Operating, ≤5.5 MW, and ≥8 years old.",
        "This is North Carolina's PURPA fleet: hundreds of small plants from the same development generation, with fragmented ownership and older contracts. Roll-up thesis: acquire multiple assets, operate them as a portfolio, and repower them.",
        "Capacity, 'First Power Date,' and operating status from Orennia. 5.5 MW is the standard PURPA threshold in North Carolina."),
      "retirement": ("Retirement horizon", "Estimated retirement date in ≤5 years.",
        "A site approaching retirement retains its most valuable components: the interconnection position and the land. This creates an opportunity to reuse the site or queue position with new equipment.",
        "The 'Estimated Retirement Date' column from Orennia."),
      "late_stage": ("Advanced pipeline", "Under development, but not operating, with a mature stage such as an interconnection agreement, engineering, or construction.",
        "De-risked projects are among the most sought-after assets in the current market because most development risk has already been resolved. The weight is low because this indicates attractiveness rather than distress.",
        "Orennia's 'Detailed Status' mapped to a 0-100 maturity scale, with Dev Stage Score ≥60."),
      "county_risk": ("County risk (SUBTRACTS)", "The county has a recorded solar restriction or moratorium, or a history of disputed or cancelled projects.",
        "This is not an opportunity signal; it is a warning. Local opposition may prevent repowering or expansion. Its weight is therefore negative, reducing the score without excluding the project.",
        "Sabin Center 2025 files: Restrictions and Contested Projects, filtered for NC/SC and solar."),
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
