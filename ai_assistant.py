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


# ──────────────────────────────────────────────────────── context
def _project_context(row, signals_df=None) -> str:
    def gv(k):
        v = row.get(k, "")
        return "" if v is None or (isinstance(v, float) and v != v) else str(v)

    lines = [
        "You are an M&A analyst screening distressed and underperforming solar PV,",
        "storage and wind projects across the SERC (non-ISO) Southeast for acquisition.",
        "Be concrete, cite your sources (documents and web), separate fact from inference,",
        "and flag clearly what cannot be verified. Treat any valuation or avoided-cost",
        "remark as back-of-the-envelope and recommend an external specialist for anything",
        "binding.",
        "",
        f"PROJECT: {gv('Power Project Name')}  ({gv('Generator ID')})",
        f"Type: {gv('Power Project Type')} | Technology: {gv('Technology')} | Capacity: {gv('Capacity (MW)')} MW",
        f"Status: {gv('Detailed Status')} | Owner: {gv('Owner')} | Parent: {gv('Parent Company')}",
        f"Balancing Authority: {gv('Balancing Authority Code')} | {gv('County')} County, {gv('State')}",
        f"Queue ID: {gv('Queue ID')} | POI: {gv('Point of Interconnection')} | EIA Plant ID: {gv('EIA Plant ID')}",
        f"Equipment: {gv('Equipment Manufacturer')} {gv('Equipment Model')} | Incentive: {gv('PTC/ITC')}",
        f"Siting flags — Native American Lands: {gv('Native American Lands')} | "
        f"Low Income Community: {gv('Low Income Communities')} | "
        f"Retired Coal Energy Community: {gv('Retired Coal Facilities Energy Communities')}",
        f"Contract: {gv('Contract Offtaker')} @ {gv('Contract Price ($/MWh)')} $/MWh, ends {gv('Contract Termination Date')[:10]}",
        f"Capacity factor — last 12m: {gv('CF (12m)')} | trend: {gv('CF Trend (pp)')} pp",
    ]
    if signals_df is not None and len(signals_df):
        lines.append("\nEXTERNAL DISTRESS SIGNALS MATCHED TO THIS PROJECT:")
        for _, s in signals_df.head(15).iterrows():
            lines.append(
                f"- [{s.get('match_type')}/{s.get('signal_type')}] "
                f"{str(s.get('title', ''))[:110]} "
                f"({s.get('source')}, {str(s.get('date', ''))[:10]}) {s.get('url', '')}")
    return "\n".join(lines)


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

    for m in st.session_state[hist_key]:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])
            if m.get("sources"):
                st.caption("Sources: " + " · ".join(m["sources"][:8]))

    if q := st.chat_input("Ask about this target (data + web)..."):
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
