# Nofar · SERC Deal Intelligence — Duke Carolinas MVP

Professional Streamlit web tool for solar PV + storage M&A deal-sourcing in DEC/DEP territory (NC & SC). Nofar-branded (indigo #4A2EE3 / gold #F4C843, diagonal-stripe signature), free sources only.

## Tabs
- **Dashboard** — composite opportunity ranking (progress-bar scores), signal distribution, contract-cliff chart, owner roll-up table
- **Targets & playbooks** — pick a target → dossier card (facts, badges, owner, mini-map, 36-month CF sparkline) + step-by-step action playbook (link → do → verify → have/lack)
- **Map** — full interactive asset map, size=MW, color=score, filters
- **Withdrawals** — 244 solar/battery positions withdrawn from Duke's queue, with county stress chart
- **Live signals** — media / bankruptcy / FERC cards
- **Data & updates** — one-click update buttons for the four LIVE sources (EIA-860M, CourtListener, FERC RSS, media RSS); everything else is static by design

## Deploy (Streamlit Community Cloud, free)
1. Push this folder to GitHub.
2. share.streamlit.io → New app → repo → `app.py` → Deploy.
Ships pre-loaded: Orennia (compacted), Duke cluster queue (incl. withdrawals), OASIS posting, Red Zone, Sabin restrictions/contested, NC+SC WARN.

## Refresh static data
Drop fresh raw files into `raw_files/`, run `python refresh_static.py`, commit — Streamlit Cloud redeploys automatically. (In-app updates cover only the four live sources; static files refresh through git by design, so the deployed app stays reproducible.)

## Run locally
```bash
pip install -r requirements.txt
streamlit run app.py
```
