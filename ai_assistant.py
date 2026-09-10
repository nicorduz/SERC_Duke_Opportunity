"""
ai_assistant.py — per-project acquisition chat for the Targets & Playbooks tab.

Reuses your existing openai_service.OpenAIProjectClient (vector stores, file upload,
retry logic, result parsing) and adds the web_search tool, which your client did not
expose. Each target gets its own vector store (slug = Generator ID), so uploaded VDR
docs stay scoped to that project. The chat is grounded in:
  - the structured Orennia row (via the crosswalk),
  - the external distress signals already matched to this project,
  - any documents you upload for it (file_search),
  - live web lookups (web_search).

Add OPENAI_API_KEY to st.secrets. Model defaults are placeholders — confirm the
current name on OpenAI's models page (they change often).
"""
from __future__ import annotations
import streamlit as st
from openai_service import OpenAIProjectClient

DEFAULT_MODEL = "gpt-5.6-terra"   # confirm current name; use a 'sol' tier for hard questions


def _project_context(row, signals_df=None) -> str:
    def gv(k, d=""):
        v = row.get(k, d)
        return "" if v is None or (isinstance(v, float) and v != v) else str(v)
    lines = [
        "You are an M&A analyst screening distressed/underperforming solar-PV, storage and",
        "wind projects across the SERC (non-ISO) Southeast for acquisition. Be concrete, cite",
        "your sources (documents and web), separate fact from inference, and flag what cannot",
        "be verified. Frame every avoided-cost or valuation remark as back-of-the-envelope and",
        "recommend an external specialist for anything binding.",
        "",
        f"PROJECT: {gv('Power Project Name')}  ({gv('Generator ID')})",
        f"Type/Tech: {gv('Power Project Type')}{gv('Technology')} | Capacity: {gv('Capacity (MW)')} MW",
        f"Status: {gv('Detailed Status')} | Owner: {gv('Owner')} | Parent: {gv('Parent Company')}",
        f"BA: {gv('Balancing Authority Code')} | {gv('County')} County, {gv('State')}",
        f"Queue ID: {gv('Queue ID')} | POI: {gv('Point of Interconnection')} | EIA Plant ID: {gv('EIA Plant ID')}",
    ]
    if signals_df is not None and len(signals_df):
        lines.append("\nEXTERNAL DISTRESS SIGNALS ALREADY MATCHED TO THIS PROJECT:")
        for _, s in signals_df.head(15).iterrows():
            lines.append(f"- [{s.get('match_type')}/{s.get('signal_type')}] "
                         f"{str(s.get('title',''))[:110]} ({s.get('source')}, {str(s.get('date',''))[:10]}) {s.get('url','')}")
    return "\n".join(lines)


def _ask(client: OpenAIProjectClient, instructions: str, prompt: str,
         previous_response_id=None, model=DEFAULT_MODEL):
    """Build a Responses body with web_search (+ file_search if docs exist) and post it
    through the client's retry-aware poster + parser."""
    vs_id = client.ensure_vector_store()
    tools = [{"type": "web_search"}]
    if client.project_file_ids():
        tools.append({"type": "file_search", "vector_store_ids": [vs_id], "max_num_results": 12})
    body = {
        "model": model, "instructions": instructions, "input": prompt,
        "tools": tools, "tool_choice": "auto",
        "include": ["file_search_call.results"],
        "reasoning": {"effort": "medium"}, "store": True,
    }
    if previous_response_id:
        body["previous_response_id"] = previous_response_id
    payload = client._post_response(body)          # reuse retry/backoff
    return client._parse_assistant_result(payload)  # reuse source/artifact parsing


def render_project_chat(row, signals_df=None, *, api_key=None, model=DEFAULT_MODEL):
    """Drop this inside the selected-target block of the Targets & Playbooks tab."""
    api_key = api_key or st.secrets.get("OPENAI_API_KEY")
    if not api_key:
        st.info("Añade OPENAI_API_KEY en Settings → Secrets para activar el chat de IA.")
        return

    gid = str(row.get("Generator ID", "project"))
    client = OpenAIProjectClient(api_key, project_slug=gid)
    hist_key, resp_key = f"chat_{gid}", f"respid_{gid}"
    st.session_state.setdefault(hist_key, [])

    st.markdown("#### 🤖 AI acquisition chat")
    with st.expander("Documentos del proyecto (VDR)"):
        up = st.file_uploader("Sube PDFs/Excel para este target", accept_multiple_files=True,
                              key=f"up_{gid}")
        if up and st.button("Indexar", key=f"idx_{gid}"):
            for f in up:
                client.upload_project_file(f.name, f.read())
            st.success(f"{len(up)} archivo(s) indexado(s).")

    for m in st.session_state[hist_key]:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])
            if m.get("sources"):
                st.caption("Fuentes: " + " · ".join(m["sources"][:8]))

    if q := st.chat_input("Pregunta sobre este target (docs + web)..."):
        st.session_state[hist_key].append({"role": "user", "content": q})
        with st.chat_message("assistant"):
            with st.spinner("Analizando..."):
                try:
                    res = _ask(client, _project_context(row, signals_df), q,
                               previous_response_id=st.session_state.get(resp_key), model=model)
                    st.markdown(res.text)
                    if res.sources:
                        st.caption("Fuentes: " + " · ".join(res.sources[:8]))
                    st.session_state[resp_key] = res.response_id
                    st.session_state[hist_key].append(
                        {"role": "assistant", "content": res.text, "sources": res.sources})
                except Exception as e:
                    st.error(f"Error: {e}")
