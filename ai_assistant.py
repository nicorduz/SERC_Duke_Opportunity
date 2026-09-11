"""
ai_assistant.py — per-project acquisition chat (Targets & Playbooks tab).

SELF-CONTAINED BY DESIGN.
Earlier versions imported `openai_service.py` from another repository, which caused
a ModuleNotFoundError here. This version talks to the OpenAI Responses API directly
using `requests` (already a dependency), so it needs NO extra file and NO httpx.

If `openai_service.py` DOES happen to be present in the repo, we use it, because it
adds vector-store document handling. Otherwise we fall back to the built-in client
below, which supports web search and conversation threading — everything except
uploading your own documents.

Grounding for every answer:
  · the project's structured Orennia row,
  · the external distress signals already matched to that project,
  · live web search,
  · (optional) documents you upload, when openai_service is available.

Requires OPENAI_API_KEY in st.secrets.
"""
from __future__ import annotations
import json
import streamlit as st

API_URL = "https://api.openai.com/v1/responses"
DEFAULT_MODEL = "gpt-5.6-terra"   # verify the current name at platform.openai.com/docs/models

# Optional richer client (documents / vector stores). Never fatal if absent.
try:
    from openai_service import OpenAIProjectClient
    _HAS_DOC_CLIENT = True
except Exception:
    OpenAIProjectClient = None
    _HAS_DOC_CLIENT = False


def is_available(api_key=None) -> tuple[bool, str]:
    """(ready, reason) — the chat only needs requests + an API key."""
    try:
        import requests  # noqa: F401
    except Exception as e:
        return False, f"`requests` is not installed ({e}). Add it to requirements.txt."
    if not (api_key or st.secrets.get("OPENAI_API_KEY")):
        return False, "Add OPENAI_API_KEY under Settings → Secrets to enable the AI chat."
    return True, ""


# ──────────────────────────────────────────────────────── system pre-prompt
SYSTEM_ROLE = """You are the acquisition screening analyst for Nofar USA's SERC Deal
Intelligence desk. Nofar buys DISTRESSED and UNDERPERFORMING renewable energy assets
(solar PV, battery storage, wind) in the SERC / non-ISO US Southeast — the vertically
integrated utility territories of Duke Energy (DEC, DEP, Duke Florida), Southern Company
(Georgia, Alabama, Mississippi Power), Florida Power & Light, TVA, Santee Cooper,
Dominion Energy South Carolina and the Florida municipals. The thesis is: acquire a
distressed or stalled project, reposition it, exit.

YOUR JOB on every question about a project:
1. ESTABLISH WHO OWNS IT. Name the project company / SPV, then the parent or sponsor
   behind it. If the owner field is blank, say so explicitly and suggest where it can be
   found (the utility's interconnection queue customer field, the state Secretary of
   State registry, SEC EDGAR, the project's permit filings).
2. BUILD THE OWNER'S CONTEXT. Is the sponsor healthy or under strain? Look for
   bankruptcy or receivership filings, lawsuits, liens or UCC filings, layoffs (WARN
   notices), missed milestones, asset sales, portfolio write-downs, financing trouble,
   leadership churn, or news of them exiting a market. An owner in distress elsewhere
   still puts THIS project in play.
3. READ THE LOCAL CONTEXT. County-level signals matter: mass layoffs nearby, other
   projects withdrawn from the same queue cluster, solar moratoria or restrictive
   ordinances, organised local opposition, transmission constraints at the point of
   interconnection.
4. WEIGH THE ASSET ITSELF. Stage and momentum in the interconnection queue, capacity
   factor versus forecast, PPA or avoided-cost exposure and when it expires,
   interconnection upgrade cost, equipment vintage and manufacturer, retirement horizon,
   proximity to a retiring thermal plant (freed capacity and POI) or to a data center
   (potential offtaker).
5. REACH A VERDICT. Say plainly whether the evidence supports a DISTRESS thesis, an
   UNDERPERFORMANCE thesis, an OPPORTUNISTIC thesis (healthy but for sale), or NO CASE.
   Then give the concrete next diligence step.

HOW TO ANSWER:
- Separate three things at all times: what the app's data shows, what you found on the
  web just now, and what you are inferring. Label inference as inference.
- Cite sources for anything from the web. Quote the filing, docket or article.
- If you cannot verify something, say "not verified" rather than filling the gap.
- Distinguish the PROJECT entity from the PARENT. A parent's bankruptcy does not mean
  the project company filed, and vice versa — state which one the evidence concerns.
- Never treat a headline as proof of a filing; a docket number or filing record is proof.
- Any valuation, avoided-cost or IRR remark is back-of-the-envelope only; say so and
  recommend an external specialist for anything binding.
- Be concise and specific. Lead with the verdict, then the evidence.

The structured record below comes from Nofar's own database (Orennia licensed data plus
free public sources). Treat it as the baseline fact set and use web search to extend,
corroborate or contradict it."""


def _project_context(row, signals_df=None) -> str:
    def gv(k, default="not reported"):
        v = row.get(k, None)
        if v is None or (isinstance(v, float) and v != v) or str(v).strip() in ("", "nan", "NaT"):
            return default
        return str(v)

    L = [SYSTEM_ROLE, "", "=" * 62, "PROJECT RECORD (Nofar SERC Deal Intelligence)", "=" * 62,
         "", "-- Identity --",
         f"Project: {gv('Power Project Name')}   [{gv('Generator ID')}]",
         f"Owner (project company): {gv('Owner')}",
         f"Parent / sponsor: {gv('Parent Company')} {gv('Parent Company 2', '')}",
         f"EIA Plant ID: {gv('EIA Plant ID')} | EIA Generator ID: {gv('EIA Generator ID')}",
         f"FERC docket: {gv('FERC Docket ID')} | EPC: {gv('EPC')}",
         "", "-- Asset --",
         f"Type: {gv('Power Project Type')} | Capacity: {gv('Capacity (MW)')} MW AC / {gv('DC Capacity (MW)')} MW DC",
         f"Status: {gv('Detailed Status')} | Chance of success: {gv('Chance of Success (Percentage)')}",
         f"Equipment: {gv('Equipment Manufacturer')} {gv('Equipment Model', '')} | Panel type: {gv('Panel Type')}",
         f"Capex: {gv('Capex Per Watt ($/W)')} $/W | Incentive: {gv('PTC/ITC')}",
         f"First power: {gv('First Power Date')[:10]} | Est. retirement: {gv('Estimated Retirement Date')[:10]}",
         "", "-- Grid --",
         f"Balancing authority: {gv('Balancing Authority Code')} | Transmission owner: {gv('Transmission Owner')}",
         f"Location: {gv('County')} County, {gv('State')}  ({gv('Latitude (Degrees)')}, {gv('Longitude (Degrees)')})",
         f"Queue ID: {gv('Queue ID')} | Cycle: {gv('Queue Cycle')} | Queued: {gv('Queue Date')[:10]}",
         f"POI: {gv('Point of Interconnection')} at {gv('Connection Voltage (kV)')} kV",
         f"Interconnection cost: {gv('Interconnection Cost Total ($)')} total | {gv('IX Cost $/kW')} $/kW",
         "", "-- Revenue --",
         f"Offtaker: {gv('Contract Offtaker')} ({gv('Contract Offtaker Type')}) | Type: {gv('Contract Type')}",
         f"Price: {gv('Contract Price ($/MWh)')} $/MWh | Term: {gv('Contract Term Years (Year)')} yrs",
         f"Contract ends: {gv('Contract Termination Date')[:10]}",
         "", "-- Performance --",
         f"Capacity factor last 12m: {gv('CF (12m)')} | prior 12m: {gv('CF (prev 12m)')} | trend: {gv('CF Trend (pp)')} pp",
         f"Forecast CF (10y): {gv('CF (fcst 10y)')} | Lifetime CF: {gv('Lifetime Capacity Factor')}",
         "", "-- Siting flags --",
         f"Native American lands: {gv('Native American Lands')} | Low income community: {gv('Low Income Communities')}",
         f"Retired-coal energy community: {gv('Retired Coal Facilities Energy Communities')} | "
         f"Behind the meter: {gv('Behind the Meter')}",
         "", "-- Nofar screening --",
         f"Opportunity grade: {gv('Opportunity Score')} / 10",
         f"Screens fired: {gv('Why')}"]

    if signals_df is not None and len(signals_df):
        L += ["", "-- External distress signals already matched to this project --"]
        for _, s_ in signals_df.head(20).iterrows():
            L.append(f"  [{s_.get('match_type')}] {s_.get('signal_type')}: "
                     f"{str(s_.get('title',''))[:120]} "
                     f"({s_.get('source')}, {str(s_.get('date',''))[:10]}) {s_.get('url','')}")
        L.append("  NOTE: 'direct' means the signal names this owner/project. "
                 "'ambient' means it was recorded in the same county and is context only.")
    else:
        L += ["", "-- External distress signals --",
              "  None matched yet. Either the distress scan has not been run for this "
              "entity, or nothing was found. Absence is NOT evidence of health — verify "
              "on the web before concluding anything."]
    return "\n".join(L)


SUGGESTED_QUESTIONS = [
    "Who really owns this project, and is that owner under financial strain?",
    "Is there any evidence of bankruptcy, liens or litigation against the owner or parent?",
    "What is happening in this county that could affect the project?",
    "Build the distress case for this project — or tell me there isn't one.",
    "What would I need to verify before approaching the owner?",
]


# ──────────────────────────────────────────────────────── built-in client
def _ask_builtin(api_key, instructions, prompt, previous_response_id=None,
                 model=DEFAULT_MODEL, timeout=180):
    """Minimal Responses API call with web_search. Returns (text, response_id, sources)."""
    import requests
    body = {
        "model": model,
        "instructions": instructions,
        "input": prompt,
        "tools": [{"type": "web_search"}],
        "tool_choice": "auto",
        "store": True,
    }
    if previous_response_id:
        body["previous_response_id"] = previous_response_id

    r = requests.post(API_URL, timeout=timeout,
                      headers={"Authorization": f"Bearer {api_key}",
                               "Content-Type": "application/json"},
                      data=json.dumps(body))
    if r.status_code >= 400:
        raise RuntimeError(f"OpenAI API {r.status_code}: {r.text[:400]}")
    data = r.json()

    # Prefer the convenience field; otherwise walk the output blocks.
    text = data.get("output_text") or ""
    sources = []
    if not text:
        chunks = []
        for item in data.get("output", []):
            for c in item.get("content", []) or []:
                if c.get("type") in ("output_text", "text") and c.get("text"):
                    chunks.append(c["text"])
                for ann in c.get("annotations", []) or []:
                    u = ann.get("url")
                    if u and u not in sources:
                        sources.append(u)
        text = "\n".join(chunks)
    else:
        for item in data.get("output", []):
            for c in item.get("content", []) or []:
                for ann in c.get("annotations", []) or []:
                    u = ann.get("url")
                    if u and u not in sources:
                        sources.append(u)
    return text or "(empty response)", data.get("id"), sources


def _ask_with_documents(client, instructions, prompt, previous_response_id, model):
    """Richer path when openai_service.py is present: adds file_search over the VDR."""
    vs_id = client.ensure_vector_store()
    tools = [{"type": "web_search"}]
    if client.project_file_ids():
        tools.append({"type": "file_search",
                      "vector_store_ids": [vs_id], "max_num_results": 12})
    body = {"model": model, "instructions": instructions, "input": prompt,
            "tools": tools, "tool_choice": "auto",
            "include": ["file_search_call.results"],
            "reasoning": {"effort": "medium"}, "store": True}
    if previous_response_id:
        body["previous_response_id"] = previous_response_id
    res = client._parse_assistant_result(client._post_response(body))
    return res.text, res.response_id, list(res.sources or [])


# ──────────────────────────────────────────────────────── UI
def render_project_chat(row, signals_df=None, *, api_key=None, model=DEFAULT_MODEL):
    api_key = api_key or st.secrets.get("OPENAI_API_KEY")
    ok, reason = is_available(api_key)

    st.markdown("#### 🤖 AI acquisition chat")
    if not ok:
        st.info(reason)
        return

    gid = str(row.get("Generator ID", "project"))
    hist_key, resp_key = f"chat_{gid}", f"respid_{gid}"
    st.session_state.setdefault(hist_key, [])

    client = None
    if _HAS_DOC_CLIENT:
        try:
            client = OpenAIProjectClient(api_key, project_slug=gid)
        except Exception:
            client = None

    if client is not None:
        with st.expander("Project documents (VDR)"):
            up = st.file_uploader("Upload PDFs / Excel for this target",
                                  accept_multiple_files=True, key=f"up_{gid}")
            if up and st.button("Index documents", key=f"idx_{gid}"):
                for f in up:
                    client.upload_project_file(f.name, f.read())
                st.success(f"{len(up)} file(s) indexed.")
    else:
        st.caption("Web search enabled. Document upload needs `openai_service.py` "
                   "in the repo — optional.")

    if not st.session_state[hist_key]:
        st.caption("Suggested starting points:")
        for _qi, _q in enumerate(SUGGESTED_QUESTIONS):
            if st.button(_q, key=f"sq_{gid}_{_qi}", use_container_width=True):
                st.session_state[f"pending_{gid}"] = _q
                st.rerun()

    for m in st.session_state[hist_key]:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])
            if m.get("sources"):
                st.caption("Sources: " + " · ".join(m["sources"][:8]))

    q = st.chat_input("Ask about this target (data + web)...")
    if not q and st.session_state.get(f"pending_{gid}"):
        q = st.session_state.pop(f"pending_{gid}")
    if q:
        st.session_state[hist_key].append({"role": "user", "content": q})
        with st.chat_message("user"):
            st.markdown(q)
        with st.chat_message("assistant"):
            with st.spinner("Analyzing..."):
                try:
                    ctx = _project_context(row, signals_df)
                    prev = st.session_state.get(resp_key)
                    if client is not None:
                        text, rid, srcs = _ask_with_documents(client, ctx, q, prev, model)
                    else:
                        text, rid, srcs = _ask_builtin(api_key, ctx, q, prev, model)
                    st.markdown(text)
                    if srcs:
                        st.caption("Sources: " + " · ".join(srcs[:8]))
                    st.session_state[resp_key] = rid
                    st.session_state[hist_key].append(
                        {"role": "assistant", "content": text, "sources": srcs})
                except Exception as e:
                    st.error(f"Error: {e}")
                    st.caption("If the model name is rejected, update DEFAULT_MODEL "
                               "in ai_assistant.py with a current model id.")
