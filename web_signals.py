"""web_signals.py — targeted distress search via Google News RSS (free, no key, no login).
NOT LinkedIn (blocked). Queries each NC/SC company against stress keywords."""
import pandas as pd, urllib.parse, feedparser, time

STRESS = ['layoffs', 'job cuts', 'bankruptcy', 'cancels solar', 'terminates PPA',
          'writedown', 'restructuring', 'default', 'sells solar', 'distressed']

def _companies_from(g, ownership=None, extra=None):
    names = set()
    if ownership is not None and "current_owner" in ownership:
        names |= set(ownership["current_owner"].dropna().tolist())
    # project names as fallback universe
    names |= set(g["Power Project Name"].dropna().tolist())
    if extra: names |= set(extra)
    # keep company-like names (drop pure "Duke:..." internal ids)
    return [n for n in names if isinstance(n, str) and len(n) > 4 and ":" not in n][:40]

def scan_web_signals(g, ownership=None, max_companies=25):
    rows = []
    comps = _companies_from(g, ownership)[:max_companies]
    for c in comps:
        q = f'"{c}" (layoffs OR bankruptcy OR "cancels" OR "terminates" OR distressed) solar'
        url = "https://news.google.com/rss/search?q=" + urllib.parse.quote(q) + "&hl=en-US&gl=US&ceid=US:en"
        try:
            fp = feedparser.parse(url)
            for e in fp.entries[:3]:
                title = e.get("title", "")
                hit = next((k for k in STRESS if k.split()[0] in title.lower()), "signal")
                rows.append({"company": c, "signal_type": hit, "title": title,
                             "published": e.get("published", "")[:16],
                             "source": e.get("source", {}).get("title", "Google News") if isinstance(e.get("source"), dict) else "Google News",
                             "link": e.get("link", "")})
        except Exception:
            pass
        time.sleep(0.3)  # be gentle
    return pd.DataFrame(rows)
