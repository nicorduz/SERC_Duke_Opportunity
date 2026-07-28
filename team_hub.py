"""team_hub.py — Team Hub: Memo, Conferences, Benchmark, Research.
Editable trackers backed by CSV/JSON in team_data/. Uses st.data_editor so every
table is add-row / edit-in-place, preserving all original columns."""
import os, json, datetime as dt, urllib.parse
import pandas as pd
import streamlit as st

TD = "team_data"
OWNERS = {"Nicolas": "nicolas.orduz@blueskyutility.com",
          "Giacomo": "giacomo.cernjul@blueskyutility.com"}

def _load_csv(name):
    p = os.path.join(TD, name)
    return pd.read_csv(p).fillna("") if os.path.exists(p) else pd.DataFrame()

def _save_csv(df, name):
    df.to_csv(os.path.join(TD, name), index=False)

def _mailto(action, owner_email):
    subj = urllib.parse.quote("New SERC action item assigned to you")
    body = urllib.parse.quote(f"You have a new action item:\n\n{action}\n\n— SERC Deal Intelligence")
    return f"mailto:{owner_email}?subject={subj}&body={body}"

def render(brand):
    INDIGO, GOLD, DEEP, INK = brand["INDIGO"], brand["GOLD"], brand["DEEP"], brand["INK"]
    sub = st.tabs(["📝 Weekly Memo", "🎤 Conferences", "📊 Benchmark", "📚 Research"])

    # ═══════════════════════ MEMO
    with sub[0]:
        memo = json.load(open(f"{TD}/memo.json")) if os.path.exists(f"{TD}/memo.json") else []
        st.markdown('<div class="sect">Weekly progress & action items</div>'
                    '<div class="sub">Living record. Edit past weeks, add progress, create action items with an owner (they get an email link).</div>',
                    unsafe_allow_html=True)

        with st.expander("➕ New action item", expanded=False):
            c1, c2, c3 = st.columns([3, 1, 1])
            new_item = c1.text_input("Action", key="ni_item")
            new_owner = c2.selectbox("Owner", list(OWNERS), key="ni_owner")
            new_week = c3.selectbox("Week", [w["week"] for w in memo] if memo else ["Week 1"], key="ni_week")
            if st.button("Create & notify owner", type="primary"):
                for w in memo:
                    if w["week"] == new_week:
                        w["actions"].append({"item": new_item, "owner": new_owner, "status": "Not started"})
                json.dump(memo, open(f"{TD}/memo.json", "w"), indent=1)
                st.success("Action item created.")
                st.markdown(f'<a href="{_mailto(new_item, OWNERS[new_owner])}" target="_blank" '
                            f'style="background:{INDIGO};color:#fff;padding:8px 16px;border-radius:8px;'
                            f'text-decoration:none">✉️ Send email to {new_owner}</a>', unsafe_allow_html=True)

        for wi, w in enumerate(memo):
            with st.expander(w["week"], expanded=(wi == 0)):
                st.markdown(f'<b style="color:{DEEP}">Progress made</b>', unsafe_allow_html=True)
                prog = st.text_area("Progress (one per line)", "\n".join(w["progress"]),
                                    key=f"prog_{wi}", height=120, label_visibility="collapsed")
                st.markdown(f'<b style="color:{DEEP}">Action items</b>', unsafe_allow_html=True)
                adf = pd.DataFrame(w["actions"]) if w["actions"] else pd.DataFrame(columns=["item", "owner", "status"])
                edited = st.data_editor(adf, key=f"ai_{wi}", num_rows="dynamic", use_container_width=True,
                    column_config={"owner": st.column_config.SelectboxColumn("owner", options=list(OWNERS)),
                                   "status": st.column_config.SelectboxColumn("status",
                                       options=["Not started", "Started", "Finish"])})
                if st.button("Save week", key=f"sw_{wi}"):
                    w["progress"] = [l for l in prog.split("\n") if l.strip()]
                    w["actions"] = edited.to_dict("records")
                    json.dump(memo, open(f"{TD}/memo.json", "w"), indent=1)
                    st.success("Saved.")

    # ═══════════════════════ CONFERENCES
    with sub[1]:
        st.markdown('<div class="sect">Priority conferences (Tier 1)</div>'
                    '<div class="sub">The events we are actively considering. Edit in place or add rows — new rows highlight until saved.</div>',
                    unsafe_allow_html=True)
        t1 = _load_csv("conf_tier1.csv")
        e1 = st.data_editor(t1, key="t1", num_rows="dynamic", use_container_width=True, height=280)
        if st.button("Save Tier-1", key="save_t1"): _save_csv(e1, "conf_tier1.csv"); st.success("Saved.")

        if st.button("🔎 Find upcoming SERC energy events (web)"):
            with st.spinner("Searching Google News for SERC-region energy conferences..."):
                import feedparser
                today = dt.date.today()
                terms = ["solar", "battery storage", "natural gas", "electric vehicle", "data center"]
                serc_geo = "(North Carolina OR South Carolina OR Georgia OR Tennessee OR Alabama OR Mississippi OR Southeast)"
                rows = []
                for t in terms:
                    q = f'{t} energy conference 2026 {serc_geo}'
                    url = "https://news.google.com/rss/search?q=" + urllib.parse.quote(q) + "&hl=en-US&gl=US&ceid=US:en"
                    for e in feedparser.parse(url).entries[:5]:
                        rows.append({"Conference Name": e.get("title", ""), "Category / Type": t,
                                     "Notes": e.get("link", ""), "Start Date": e.get("published", "")[:16]})
                found = pd.DataFrame(rows)
                found.to_csv(f"{TD}/conf_found.csv", index=False)
            st.success(f"Found {len(found)} candidate events. Review below and copy good ones into Tier-1.")
        if os.path.exists(f"{TD}/conf_found.csv"):
            st.markdown('<div class="sub">Web-found candidates (verify before adding — headlines, not confirmations):</div>', unsafe_allow_html=True)
            st.dataframe(pd.read_csv(f"{TD}/conf_found.csv"), use_container_width=True, height=200)

        st.markdown('<div class="sect" style="margin-top:14px">All events</div>', unsafe_allow_html=True)
        allc = _load_csv("conf_all.csv")
        ea = st.data_editor(allc, key="allc", num_rows="dynamic", use_container_width=True, height=320)
        if st.button("Save all events", key="save_all"): _save_csv(ea, "conf_all.csv"); st.success("Saved.")

    # ═══════════════════════ BENCHMARK
    with sub[2]:
        st.markdown('<div class="sect">SERC stakeholder benchmark</div>'
                    '<div class="sub">Our vetted players by category. Filter, edit in place, or add rows — all original columns preserved.</div>',
                    unsafe_allow_html=True)
        bm = _load_csv("benchmark.csv")
        cats = ["(all)"] + sorted([c for c in bm["Category / Player Type"].unique() if c])
        pick = st.selectbox("Category", cats)
        view = bm if pick == "(all)" else bm[bm["Category / Player Type"] == pick]
        eb = st.data_editor(view, key="bm", num_rows="dynamic", use_container_width=True, height=460,
            column_config={"Source / Link": st.column_config.LinkColumn("Source / Link")})
        if st.button("Save benchmark", key="save_bm"):
            if pick == "(all)": _save_csv(eb, "benchmark.csv")
            else:
                rest = bm[bm["Category / Player Type"] != pick]
                _save_csv(pd.concat([rest, eb], ignore_index=True), "benchmark.csv")
            st.success("Saved.")

    # ═══════════════════════ RESEARCH
    with sub[3]:
        st.markdown('<div class="sect">Research library</div>'
                    '<div class="sub">Reports we are reading. Set status, add comments, keep links. Add rows for new files.</div>',
                    unsafe_allow_html=True)
        rf = _load_csv("research.csv")
        done = (rf["Status"] == "Read").sum() if "Status" in rf else 0
        st.markdown(f'<span class="badge b-sig">{len(rf)} files</span>'
                    f'<span class="badge b-hot">{done} read</span>'
                    f'<span class="badge b-sig">{len(rf)-done} pending</span>', unsafe_allow_html=True)
        er = st.data_editor(rf, key="rf", num_rows="dynamic", use_container_width=True, height=460,
            column_config={"Link": st.column_config.LinkColumn("Link"),
                           "Status": st.column_config.SelectboxColumn("Status",
                               options=["Not started", "Reading", "Read"])})
        if st.button("Save research", key="save_rf"): _save_csv(er, "research.csv"); st.success("Saved.")
