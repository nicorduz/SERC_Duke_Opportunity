"""
actions.py — Action Playbook generator.
For every opportunity, produce concrete, ordered diligence steps: WHERE to go
(exact link), WHAT to do there (filter/search terms), WHAT to verify, and an
explicit note of what our data already has vs. lacks. Fully deterministic.
"""
import pandas as pd
import urllib.parse

LINKS = {
    "ncuc": "https://starw1.ncuc.gov/NCUC/page/Dockets/portal.aspx",
    "scpsc": "https://dms.psc.sc.gov",
    "eia_plant": "https://www.eia.gov/electricity/data/browser/#/plant/{pid}",
    "eia860m": "https://www.eia.gov/electricity/data/eia860m/",
    "courtlistener": "https://www.courtlistener.com/?q={q}&type=r&order_by=dateFiled+desc",
    "nc_sos_ucc": "https://www.sosnc.gov/online_services/search/by_title/_UCC",
    "sc_sos": "https://sos.sc.gov",
    "duke_queue_page": "https://www.duke-energy.com/home/products/renewable-energy/generate-your-own/interconnection-queue",
    "duke_rfp": "https://www.dukeenergyrfpcarolinas.com",
    "oasis": "https://www.oasis.oati.com/duk",
    "gmaps": "https://www.google.com/maps/search/?api=1&query={lat},{lon}",
    "nc_deeds": "https://www.google.com/search?q={county}+county+NC+register+of+deeds+online+search",
    "sc_deeds": "https://www.google.com/search?q={county}+county+SC+register+of+deeds+online+search",
    "gsearch": "https://www.google.com/search?q={q}",
}

def _step(n, title, url, do, verify, have_lack):
    return {"step": n, "title": title, "link": url, "do": do, "verify": verify,
            "have_lack": have_lack}

def _q(s): return urllib.parse.quote_plus(str(s))

def generate_playbook(row, fired, ctx):
    """
    row   : Series from the generators table (one opportunity)
    fired : list of screen keys that fired for this row
    ctx   : dict with optional context dataframes/results:
            owner (str|None), in_red_zone (bool), county_restrictions (df rows),
            county_contested (df rows), queue_match (row|None), oasis_match (row|None)
    Returns ordered list of step dicts.
    """
    steps, n = [], 1
    name = row.get("Power Project Name", "")
    county = str(row.get("County", "") or "")
    state = str(row.get("State", "NC") or "NC")
    lat, lon = row.get("Latitude (Degrees)"), row.get("Longitude (Degrees)")
    pid = row.get("EIA Plant ID")
    owner = ctx.get("owner")

    # ---- 1. Ownership: always the first question in M&A
    if owner and str(owner) != "nan":
        steps.append(_step(n, f"Confirm current owner ({owner})",
            LINKS["eia_plant"].format(pid=int(pid)) if pd.notna(pid) else LINKS["eia860m"],
            f"Open the EIA plant page and confirm '{owner}' is still the reporting entity; then Google \"{owner}\" + \"{name}\" for any sale news.",
            "Owner unchanged; owner's portfolio size; any recent transaction chatter.",
            f"WE HAVE: owner from EIA-860M join ({owner}). WE LACK: parent/sponsor structure — check owner website + press releases."))
    else:
        steps.append(_step(n, "Identify the owner (unknown in our data)",
            LINKS["eia_plant"].format(pid=int(pid)) if pd.notna(pid) else LINKS["eia860m"],
            (f"Open the EIA plant browser page for plant ID {int(pid)} — the 'Utility/Owner' field names the reporting entity."
             if pd.notna(pid) else
             f"Download latest EIA-860M and search plant name '{name}' in the Operating sheet; owner is the Entity Name column."),
            "Exact legal entity name (usually an LLC named after the project).",
            "WE HAVE: project name, county, MW, coordinates. WE LACK: owner — Orennia export has no owner column; EIA is the free fix."))
    n += 1

    # ---- 2. Screen-specific steps
    if "contract_cliff" in fired or "qf_rollup" in fired:
        yrs = row.get("Yrs to Contract End")
        offtaker = row.get("Contract Offtaker")
        docket_link = LINKS["ncuc"] if state == "NC" else LINKS["scpsc"]
        steps.append(_step(n, "Verify PPA / avoided-cost contract status",
            docket_link,
            (f"In {'NCUC' if state=='NC' else 'SCPSC'} docket search, search the project name '{name}' and the owner entity. "
             f"For NC QFs also open docket E-100 Sub 207 (avoided cost) to confirm the current rate schedule the QF would reprice onto."),
            (f"Contract end date (our data: {yrs if pd.notna(yrs) else 'UNKNOWN'} yrs remaining"
             + (f", offtaker {offtaker}" if pd.notna(offtaker) else ", offtaker UNKNOWN") +
             "); filing evidence of renewal, amendment, or termination."),
            f"WE HAVE: contract price {row.get('Contract Price ($/MWh)')} $/MWh"
            + (f", termination {str(row.get('Contract Termination Date'))[:10]}" if pd.notna(row.get("Contract Termination Date")) else "")
            + ". WE LACK: renewal negotiations status — only dockets/owner contact reveal that."))
        n += 1

    if "underperf" in fired:
        steps.append(_step(n, "Diagnose the underperformance (degradation vs curtailment vs outage)",
            LINKS["eia_plant"].format(pid=int(pid)) if pd.notna(pid) else LINKS["eia860m"],
            f"Open EIA plant page → monthly generation chart. Compare shape: gradual multi-year decline = degradation; abrupt months at/near zero = outage; midday-clipped seasons = curtailment. Our data: CF 12m {round((row.get('CF (12m)') or 0)*100,1)}% vs prior {round((row.get('CF (prev 12m)') or 0)*100,1)}%.",
            "Which failure mode it is — degradation supports a repower thesis; outage supports a distressed-owner thesis.",
            "WE HAVE: monthly actuals + Orennia forward CF. WE LACK: inverter-level cause — ask for operating data in diligence."))
        n += 1

    if "dev_distress" in fired or "late_stage" in fired:
        qm = ctx.get("queue_match")
        steps.append(_step(n, "Confirm live queue status in Duke's own records",
            LINKS["duke_queue_page"],
            (f"Open Duke's interconnection queue page, select the {state} jurisdiction, and search queue ID '{qm['queue_id']}'." if qm is not None else
             f"Open Duke's queue page ({state} jurisdiction) and search the project name '{name}' and its county '{county}' — our Orennia record shows status '{row.get('Detailed Status')}' but no matched Duke queue ID."),
            "Current operational status; cluster phase; any 'Withdrawn' flag (our cluster file shows 249 withdrawals — check this project isn't one).",
            ("WE HAVE: matched Duke queue row (status " + str(qm["status"]) + ")." if qm is not None
             else "WE LACK: a confirmed Duke queue match — name-based search required.")))
        n += 1
        steps.append(_step(n, "Check owner solvency signals",
            LINKS["courtlistener"].format(q=_q(owner or name)),
            f"Run the CourtListener search (pre-filled for '{owner or name}'). Then run a UCC search on the same name: NC SOS UCC search"
            f" ({LINKS['nc_sos_ucc']})" + (f" / SC SOS ({LINKS['sc_sos']})" if state == "SC" else "") + ".",
            "Bankruptcy dockets, receiverships, or UCC filings by lenders against the entity.",
            "WE HAVE: status distress flag from Duke/Orennia. WE LACK: solvency evidence — these two searches provide it."))
        n += 1

    if ctx.get("in_red_zone"):
        steps.append(_step(n, "Constrained-zone (Red Zone) verification",
            LINKS["oasis"],
            f"This project's substation/POI matches Duke's DEP Red Zone list (constrained transmission). On Duke OASIS, check ATC on the relevant path, and open the latest DISIS cluster study report at {LINKS['duke_rfp']} for assigned upgrade costs in that zone.",
            "Whether upgrades are already funded by another cluster participant (good) or would fall on this project (bad, but = seller leverage for us).",
            "WE HAVE: red-zone match from Duke's own constrained list. WE LACK: current ATC and upgrade cost allocation — OASIS + cluster report give both."))
        n += 1

    if ctx.get("county_restrictions") is not None and len(ctx["county_restrictions"]) > 0:
        r0 = ctx["county_restrictions"].iloc[0]
        steps.append(_step(n, f"County ordinance check — {county} County has a recorded restriction",
            LINKS["gsearch"].format(q=_q(f"{county} county {state} solar ordinance planning department")),
            f"Sabin Center records: '{str(r0.get('content'))[:180]}...' (status: {r0.get('status')}, adopted {r0.get('year_adopted')}). Open the county planning department page and confirm the ordinance's current text and whether it grandfathers existing/queued projects.",
            "Whether the restriction affects this project (existing = usually grandfathered; expansion/repower = maybe not).",
            "WE HAVE: the restriction record + citation. WE LACK: grandfathering detail — county planning staff call resolves it."))
        n += 1

    if ctx.get("county_contested") is not None and len(ctx["county_contested"]) > 0:
        c0 = ctx["county_contested"].iloc[0]
        steps.append(_step(n, f"Local-opposition context — contested project history in {county} County",
            LINKS["gsearch"].format(q=_q(str(c0.get("title")))),
            f"A project in this county was contested: '{c0.get('title')}' (status {c0.get('status')}, litigation: {c0.get('litigation')}). Review what triggered opposition and whether it's site-specific or county-wide sentiment.",
            "Opposition drivers (viewshed, farmland, decommissioning) and whether they'd attach to our target.",
            "WE HAVE: the contested-project record. WE LACK: current sentiment — county news search + agenda minutes."))
        n += 1

    # ---- Always: site + land + final
    if pd.notna(lat) and pd.notna(lon):
        steps.append(_step(n, "Desktop site review",
            LINKS["gmaps"].format(lat=lat, lon=lon),
            "Open the pinned satellite view. Check: panel rows visible & condition, vegetation encroachment, adjacent expandable land, distance to visible substation.",
            "Site condition consistent with our CF data; expansion headroom on adjacent parcels.",
            "WE HAVE: exact coordinates + GHI. WE LACK: ground truth — schedule a drive-by if it survives this screen."))
        n += 1
    deeds = LINKS["nc_deeds"] if state == "NC" else LINKS["sc_deeds"]
    steps.append(_step(n, "Land control & liens",
        deeds.format(county=_q(county)),
        f"Open {county} County's register of deeds / land records search (first result). Search the owner entity and the project name. Also check the county GIS parcel viewer for the parcels at the coordinates.",
        "Recorded lease/easement vs fee ownership; any deeds of trust, assignments, or liens recorded against the project entity.",
        "WE HAVE: county + coordinates. WE LACK: everything land-side — this is the only free source for it."))
    n += 1
    steps.append(_step(n, "Log the outcome",
        "",
        "Record findings in the tracker: advance to outreach, watchlist, or dismiss (with reason). If advancing: pull Ascend PowerVAL valuation and check AEX comps for a $/MW anchor before any conversation.",
        "Decision + reason recorded (this feeds precision measurement).",
        "Paid layer (Orennia/Ascend) takes over from here for pricing."))
    return steps

def playbook_to_md(name, steps):
    out = [f"### Action playbook — {name}"]
    for s in steps:
        out.append(f"**Step {s['step']}: {s['title']}**")
        if s["link"]: out.append(f"- 🔗 Link: {s['link']}")
        out.append(f"- ▶️ Do: {s['do']}")
        out.append(f"- ✅ Verify: {s['verify']}")
        out.append(f"- 📊 {s['have_lack']}")
        out.append("")
    return "\n".join(out)
