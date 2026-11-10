"""
Static multi-page dashboard, rebuilt on every run and served by GitHub Pages.

  index.html          Overview: KPIs, portfolio trend, grading scale, every account critical -> healthy
  accounts.html       Sortable/filterable table of all accounts
  account/<slug>.html One page per account: chart, score breakdown, agent reasoning, linked evidence, timeline
  signals.html        Every piece of evidence across all accounts, newest first, each linked to its source
  timeline.html       Every daily run: what changed, status moves, raw data
  methodology.html    How scoring, grading, the agent, and the daily automation work
"""

import datetime as dt
import html
import json
import re
import shutil
from pathlib import Path

E = html.escape
ASSETS = Path(__file__).resolve().parent / "assets"
ORDER = {"Critical": 0, "Watch": 1, "Healthy": 2}
COLOR = {"Critical": "var(--crit)", "Watch": "var(--watch)", "Healthy": "var(--ok)"}
NAV = [("overview", "Overview", "index.html"), ("accounts", "Accounts", "accounts.html"),
       ("signals", "Signals", "signals.html"), ("timeline", "Timeline", "timeline.html"),
       ("method", "How it works", "methodology.html")]
BOARD_URLS = {"greenhouse": "https://boards.greenhouse.io/{}", "lever": "https://jobs.lever.co/{}",
              "ashby": "https://jobs.ashbyhq.com/{}"}
API_URLS = {"greenhouse": "https://boards-api.greenhouse.io/v1/boards/{}/jobs",
            "lever": "https://api.lever.co/v0/postings/{}?mode=json",
            "ashby": "https://api.ashbyhq.com/posting-api/job-board/{}"}
FILING_TONE = {"1.03": "severe", "2.05": "severe", "5.02": "negative", "2.06": "negative", "2.01": "positive"}


# ----------------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------------

def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def d_fmt(iso, year=False):
    try:
        d = dt.date.fromisoformat(str(iso)[:10])
    except ValueError:
        return str(iso)
    return f"{d:%b} {d.day}" + (f", {d.year}" if year else "")


def t_fmt(run_at):
    return f"{run_at:%b} {run_at.day}, {run_at.year} at {run_at:%I:%M %p}".replace(" 0", " ") + " ET"


def money(v):
    try:
        return f"${float(v):,.0f}"
    except (TypeError, ValueError):
        return "n/a"


def change_html(delta):
    if delta is None:
        return '<span class="muted">new</span>'
    if delta > 0:
        return f'<span class="up">▲ {delta}</span>'
    if delta < 0:
        return f'<span class="down">▼ {abs(delta)}</span>'
    return '<span class="muted">– 0</span>'


def logo(company, domain, size=36):
    initials = "".join(w[0] for w in re.findall(r"[A-Za-z0-9]+", company)[:2]).upper()
    hue = sum(map(ord, company)) * 37 % 360
    img = (f'<img src="https://icons.duckduckgo.com/ip3/{E(domain)}.ico" alt="" loading="lazy" '
           f'onerror="this.remove()">') if domain else ""
    return (f'<span class="logo" style="--h:{hue};width:{size}px;height:{size}px;font-size:{size * .36:.0f}px" '
            f'aria-hidden="true">{E(initials)}{img}</span>')


def ext(url, text="Source ↗"):
    if not url:
        return '<span class="muted" style="font-size:12.5px">sample, no link</span>'
    return f'<a class="src" href="{E(url)}" target="_blank" rel="noopener">{E(text)}</a>'


def chart(series, compact=False, chart_id=None):
    attrs = f' id="{chart_id}"' if chart_id else ""
    return (f'<div class="chart"{attrs} data-compact="{1 if compact else 0}" '
            f'data-series="{E(json.dumps(series))}"></div>')


# ----------------------------------------------------------------------------
# Derived data
# ----------------------------------------------------------------------------

def series_for(history, company):
    return [{"d": run["date"], "s": run["accounts"][company]["score"], "st": run["accounts"][company]["status"],
             "h": run["accounts"][company].get("headline", "")}
            for run in history["runs"] if company in run["accounts"]]


def status_since(series):
    if not series:
        return None
    since = series[-1]["d"]
    for p in reversed(series):
        if p["st"] != series[-1]["st"]:
            break
        since = p["d"]
    return since


def change_over(series, n):
    if len(series) <= 1:
        return None
    back = series[-1 - min(n, len(series) - 1)]
    return series[-1]["s"] - back["s"]


def momentum(series):
    c = change_over(series, 7)
    if c is None:
        return "New", "muted"
    if c >= 5:
        return "Improving", "up"
    if c <= -5:
        return "Declining", "down"
    return "Stable", "muted"


def latest_signal_date(rec):
    dates = [r.get("posted") for r in rec["jobs"].get("recent_roles", []) if r.get("posted")]
    dates += [a["published"] for a in rec["news"].get("articles", [])]
    dates += [f["date"] for f in rec["filings"].get("filings", [])]
    return max(dates) if dates else None


def signals_for(r):
    rec, meta, out = r["record"], r["record"].get("meta", {}), []
    for j in rec["jobs"].get("recent_roles", [])[:8]:
        if j.get("posted"):
            out.append({"date": j["posted"], "type": "Hiring", "tone": "neutral", "tag": "new role",
                        "title": f"{j['title']}" + (f" · {j['location']}" if j.get("location") else ""),
                        "url": j.get("url", "")})
    for a in rec["news"].get("articles", []):
        out.append({"date": a["published"], "type": "News", "tone": a["tone"], "tag": a["tone"],
                    "title": a["title"] + (f" ({a['source']})" if a.get("source") else ""), "url": a.get("url", "")})
    for f in rec["filings"].get("filings", []):
        tone = next((FILING_TONE[c] for c in f["items"] if c in FILING_TONE), "neutral")
        out.append({"date": f["date"], "type": "SEC filing", "tone": tone, "tag": f["form"],
                    "title": ", ".join(f["labels"]), "url": f.get("url", "")})
    return sorted(out, key=lambda s: s["date"], reverse=True)


# ----------------------------------------------------------------------------
# Page shell
# ----------------------------------------------------------------------------

def page(title, active, body, run_at, root=""):
    nav = "".join(f'<a href="{root}{href}" class="{"on" if key == active else ""}">{label}</a>'
                  for key, label, href in NAV)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{E(title)} · Account Pulse</title>
<link rel="stylesheet" href="{root}assets/style.css">
<script src="{root}assets/app.js" defer></script>
</head><body>
<header class="topbar"><div class="wrap">
  <a class="brand" href="{root}index.html"><span class="beat"></span>Account Pulse</a>
  <nav>{nav}</nav>
  <span class="stamp">Updated <b>{t_fmt(run_at)}</b></span>
</div></header>
<main class="wrap">{body}
<footer>Account Pulse checks every account each morning at about 7:00 AM ET: hiring, news, and SEC filings,
compared to the previous run, scored by transparent rules, then reviewed by an AI agent.
<a href="{root}methodology.html">How it works</a>.</footer>
</main></body></html>"""


def banner(demo):
    if demo:
        return '<div class="banner">Demo mode: fictional companies and sample data.</div>'
    return ('<div class="banner subtle">Hiring, news, and SEC filings are live data with source links. '
            'Renewal dates, last contact, and ARR are sample CRM values for demonstration.</div>')


def scale_html(marker_scores=None):
    markers = "".join(f'<span class="marker" style="left:{s}%;color:{COLOR[st]}">▼ {s}</span>'
                      for n, s, st in (marker_scores or []))
    return f"""
{'<div class="marker-row">' + markers + '</div>' if markers else ''}
<div class="scale"><div style="width:45%;background:var(--crit)"></div><div style="width:20%;background:var(--watch)"></div>
<div style="width:35%;background:var(--ok)"></div></div>
<div class="scale-labels">
  <div><b style="color:var(--crit)">0–44 · Critical</b><span class="muted">Serious risk to the renewal or relationship. Act this week.</span></div>
  <div><b style="color:var(--watch)">45–64 · Watch</b><span class="muted">Warning signs. Check in soon.</span></div>
  <div><b style="color:var(--ok)">65–100 · Healthy</b><span class="muted">Stable or growing. 80+ often means expansion potential.</span></div>
</div>"""


# ----------------------------------------------------------------------------
# Pages
# ----------------------------------------------------------------------------

def overview(results, summary, run_at, history, demo):
    counts = {s: sum(r["assessment"]["status"] == s for r in results) for s in ORDER}
    arr_risk = sum(float(r["record"]["crm"].get("arr") or 0) for r in results if r["assessment"]["status"] != "Healthy")
    avg = round(sum(r["assessment"]["health_score"] for r in results) / max(1, len(results)))
    portfolio = []
    for run in history["runs"]:
        scores = [a["score"] for a in run["accounts"].values()]
        if scores:
            v = round(sum(scores) / len(scores))
            portfolio.append({"d": run["date"], "s": v, "st": "Critical" if v < 45 else "Watch" if v < 65 else "Healthy",
                              "h": f"{sum(a['status'] == 'Critical' for a in run['accounts'].values())} critical, "
                                   f"{sum(a['status'] == 'Watch' for a in run['accounts'].values())} watch"})

    cards = []
    for r in results:
        a, rec, s = r["assessment"], r["record"], r["series"]
        st = a["status"]
        cards.append(f"""
<article class="acct" style="--c:{COLOR[st]}">
  <div>
    <div class="acct-head">{logo(r['company'], rec.get('meta', {}).get('domain'), 40)}
      <div><h3><a href="account/{slug(r['company'])}.html">{E(r['company'])}</a></h3>
      <div class="dates">Updated {d_fmt(run_at.date().isoformat())} · {st} since {d_fmt(status_since(s) or '')}</div></div>
      <span class="pill {st}" style="margin-left:auto">{st}</span></div>
    <p class="headline">{E(a['headline'])}</p>
    <p class="muted">{E(a['reason'])}</p>
    <div class="action"><b>Next action:</b> {E(a['next_action'])}</div>
  </div>
  <div class="acct-chart">
    <div class="scorerow"><div><span class="score-big {st}">{a['health_score']}</span>
      <span class="muted" style="font-size:13px"> / 100</span></div>
      <div class="chg">1-day {change_html(r['delta'])} · 7-day {change_html(change_over(s, 7))}</div></div>
    {chart(s, compact=True)}
    <div class="scorerow"><span class="dates">{len(s)} days tracked · hover the line</span>
      <a class="more" href="account/{slug(r['company'])}.html">Details &amp; evidence →</a></div>
  </div>
</article>""")

    markers = []
    body = f"""
<h1>Good morning. Here's where your accounts stand.</h1>
<p class="lead">Every account is ranked from most urgent to healthiest. Scores run from 0 to 100; hover any chart to see
how an account has moved day by day.</p>
{banner(demo)}
<div class="kpis">
  <div class="kpi"><b class="countup" data-value="{len(results)}">{len(results)}</b><span>Accounts monitored</span></div>
  <div class="kpi"><b class="countup" data-value="{counts['Critical']}" style="color:var(--crit)">{counts['Critical']}</b><span>Critical</span></div>
  <div class="kpi"><b class="countup" data-value="{counts['Watch']}" style="color:var(--watch)">{counts['Watch']}</b><span>Watch</span></div>
  <div class="kpi"><b class="countup" data-value="{counts['Healthy']}" style="color:var(--ok)">{counts['Healthy']}</b><span>Healthy</span></div>
  <div class="kpi"><b class="countup" data-value="{avg}">{avg}</b><span>Average health score</span></div>
  <div class="kpi"><b class="countup" data-prefix="$" data-value="{arr_risk:.0f}">{money(arr_risk)}</b><span>ARR not healthy</span></div>
</div>
<div class="grid2">
  <div class="card chart-card"><div class="scorerow"><p class="label">Portfolio health · average score</p>
    <div class="ranges"><button data-range-for="pchart" data-range="7">7D</button><button data-range-for="pchart" data-range="14">14D</button>
    <button data-range-for="pchart" data-range="0" class="on">All</button></div></div>
    {chart(portfolio, chart_id="pchart")}</div>
  <div class="card"><p class="label">Agent summary · {d_fmt(run_at.date().isoformat(), True)}</p>
    <p style="margin:0 0 18px">{E(summary)}</p>
    <p class="label">How to read the score</p>{scale_html(markers)}
    <p style="margin:12px 0 0"><a class="more" href="methodology.html">Full grading method →</a></p></div>
</div>
<div class="section"><h2>Accounts, most urgent first</h2>{''.join(cards)}</div>"""
    return page("Overview", "overview", body, run_at)


def accounts_page(results, run_at, demo):
    rows = []
    for r in results:
        a, rec, s = r["assessment"], r["record"], r["series"]
        crm = rec["crm"]
        mom, cls = momentum(s)
        url = f"account/{slug(r['company'])}.html"
        rows.append(f"""
<tr class="rowlink" data-status="{a['status']}" data-name="{E(r['company'])}" onclick="location.href='{url}'">
  <td><span class="namecell">{logo(r['company'], rec.get('meta', {}).get('domain'), 28)}<a href="{url}">{E(r['company'])}</a></span></td>
  <td><span class="pill {a['status']}">{a['status']}</span></td>
  <td class="num"><b>{a['health_score']}</b></td>
  <td class="num">{change_html(r['delta'])}</td>
  <td class="num">{change_html(change_over(s, 7))}</td>
  <td><span class="{cls}">{mom}</span></td>
  <td>{chart(s[-14:], compact=True)}</td>
  <td>{d_fmt(crm.get('renewal_date') or '') if crm.get('renewal_date') else 'n/a'}</td>
  <td>{d_fmt(crm.get('last_contact') or '') if crm.get('last_contact') else 'n/a'}</td>
  <td class="num">{money(crm.get('arr'))}</td>
  <td>{d_fmt(latest_signal_date(rec)) if latest_signal_date(rec) else 'n/a'}</td>
  <td>{d_fmt(status_since(s) or '')}</td>
</tr>""")
    body = f"""
<h1>Accounts</h1>
<p class="lead">All {len(results)} monitored accounts. Click any row for the full breakdown and evidence.</p>
{banner(demo)}
<div class="toolbar" data-filter-scope="tr.rowlink">
  <div class="seg" data-group="status"><button class="on" data-value="all">All</button><button data-value="Critical">Critical</button>
  <button data-value="Watch">Watch</button><button data-value="Healthy">Healthy</button></div>
  <input type="search" placeholder="Search accounts">
</div>
<div class="card table-wrap"><table>
<thead><tr><th>Account</th><th>Status</th><th class="num">Score</th><th class="num">1-day</th><th class="num">7-day</th>
<th>Momentum</th><th>Trend (14 days)</th><th>Renewal</th><th>Last contact</th><th class="num">ARR</th><th>Latest signal</th>
<th>Status since</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>"""
    return page("Accounts", "accounts", body, run_at)


def breakdown_html(r):
    rules, a = r["rules"], r["assessment"]
    items = ['<li><span>Starting score (every account)</span><span class="pts">70</span></li>']
    for f in rules["flags"]:
        cls = "up" if f["points"] > 0 else "down"
        items.append(f'<li><span>{E(f["text"])}</span><span class="pts {cls}">{f["points"]:+d}</span></li>')
    raw = 70 + sum(f["points"] for f in rules["flags"])
    if raw != rules["score"]:
        items.append(f'<li><span class="muted">Adjustment: overlapping risks capped at −55, score kept within 0–100</span>'
                     f'<span class="pts">{rules["score"] - raw:+d}</span></li>')
    items.append(f'<li class="total"><span>Rule score</span><span>{rules["score"]}</span></li>')
    if a["source"] == "agent":
        verdict = ("adjusted the score" if a["health_score"] != rules["score"] else "agreed with the rules")
        items.append(f'<li class="total"><span>Final score after AI agent review ({verdict})</span>'
                     f'<span>{a["health_score"]}</span></li>')
    return f'<ul class="bd">{"".join(items)}</ul>'


def evidence_html(r):
    rec, meta = r["record"], r["record"].get("meta", {})
    checked = d_fmt(rec.get("checked_at", "")[:10], True) if rec.get("checked_at") else ""
    jobs, news, filings, crm = rec["jobs"], rec["news"], rec["filings"], rec["crm"]
    blocks = []

    # Hiring
    links = []
    if meta.get("ats") in BOARD_URLS and meta.get("board_token"):
        links.append(ext(BOARD_URLS[meta["ats"]].format(meta["board_token"]), "Careers board ↗"))
        links.append(ext(API_URLS[meta["ats"]].format(meta["board_token"]), "Raw API data ↗"))
    if jobs.get("available"):
        chg = (f" · {jobs['prev_open_roles']} at last run ({jobs['change_pct']:+.0f}%)"
               if jobs.get("change_pct") is not None else "")
        roles = "".join(f'<li><span class="when">{d_fmt(j["posted"]) if j.get("posted") else "open"}</span>'
                        f'<span class="what">{E(j["title"])}<br><span class="muted" style="font-size:12.5px">'
                        f'{E(j.get("location", ""))}</span></span>{ext(j.get("url"), "Posting ↗")}</li>'
                        for j in jobs.get("recent_roles", [])[:8])
        blocks.append(f"""<div class="card"><p class="label">Hiring · checked {checked}</p>
<div class="sourcebar"><span><b>{jobs['open_roles']}</b> open roles{chg}</span><span><b>{jobs.get('new_7d', 0)}</b> posted in 7 days</span>{''.join(links)}</div>
<ul class="ev">{roles}</ul></div>""")
    else:
        blocks.append(f'<div class="card"><p class="label">Hiring</p><p class="muted">Not available: {E(jobs.get("error", ""))}</p></div>')

    # News
    if news.get("available"):
        q = meta.get("news_query")
        items = "".join(f'<li><span class="when">{d_fmt(n["published"])}</span><span class="what">'
                        f'<span class="tag {n["tone"]}">{n["tone"]}</span> {E(n["title"])}<br>'
                        f'<span class="muted" style="font-size:12.5px">{E(n.get("source", ""))}</span></span>'
                        f'{ext(n.get("url"), "Article ↗")}</li>' for n in news["articles"]) \
            or '<li class="muted">No news in the last 14 days.</li>'
        blocks.append(f"""<div class="card"><p class="label">News · last 14 days · checked {checked}</p>
<div class="sourcebar">{'<span class="muted">Search: ' + E(q) + '</span>' if q else ''}</div><ul class="ev">{items}</ul></div>""")
    else:
        blocks.append(f'<div class="card"><p class="label">News</p><p class="muted">Not available: {E(news.get("error", ""))}</p></div>')

    # Filings
    cik = "".join(ch for ch in str(meta.get("cik", "")) if ch.isdigit())
    edgar = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=8-K" if cik else ""
    if filings.get("available"):
        items = "".join(f'<li><span class="when">{d_fmt(f["date"])}</span><span class="what"><span class="tag">{E(f["form"])}</span> '
                        f'{E(", ".join(f["labels"]))}</span>{ext(f.get("url"), "Filing ↗")}</li>'
                        for f in filings["filings"]) or '<li class="muted">No filings in the last 30 days.</li>'
        blocks.append(f"""<div class="card"><p class="label">SEC filings · last 30 days · checked {checked}</p>
<div class="sourcebar">{ext(edgar, "All filings on SEC EDGAR ↗") if edgar else ''}</div><ul class="ev">{items}</ul></div>""")
    else:
        blocks.append(f'<div class="card"><p class="label">SEC filings</p><p class="muted">{E(filings.get("error", ""))}</p></div>')

    # CRM
    rules = r["rules"]
    blocks.append(f"""<div class="card"><p class="label">Relationship (CRM)</p><ul class="ev">
<li><span class="what">Renewal date</span><b>{d_fmt(crm.get('renewal_date'), True) if crm.get('renewal_date') else 'n/a'}</b></li>
<li><span class="what">Days until renewal</span><b>{rules.get('renewal_in_days') if rules.get('renewal_in_days') is not None else 'n/a'}</b></li>
<li><span class="what">Last contact</span><b>{d_fmt(crm.get('last_contact'), True) if crm.get('last_contact') else 'n/a'}</b></li>
<li><span class="what">Days since contact</span><b>{rules.get('days_since_contact') if rules.get('days_since_contact') is not None else 'n/a'}</b></li>
<li><span class="what">Annual contract value</span><b>{money(crm.get('arr'))}</b></li>
<li><span class="what">Owner</span><b>{E(crm.get('owner') or 'n/a')}</b></li></ul>
<p class="muted" style="font-size:12.5px;margin:8px 0 0">Sample values until a CRM is connected.</p></div>""")
    return "".join(blocks)


def account_page(r, run_at, demo):
    a, rec, s = r["assessment"], r["record"], r["series"]
    st = a["status"]
    mom, cls = momentum(s)
    risks = "".join(f"<li>{E(x)}</li>" for x in a.get("risks", [])) or "<li class=muted>None noted</li>"
    opps = "".join(f"<li>{E(x)}</li>" for x in a.get("opportunities", [])) or "<li class=muted>None noted</li>"
    who = ("AI agent" + (f" · checked {', '.join(t.replace('get_', '').replace('_', ' ') for t in dict.fromkeys(a['tools_used']))}"
                         if a.get("tools_used") else "")) if a["source"] == "agent" else "Rules (AI agent not used on this run)"

    tl = []
    for i in range(len(s) - 1, -1, -1):
        p, prev = s[i], (s[i - 1] if i > 0 else None)
        moved = ("" if not prev or prev["st"] == p["st"] else
                 f' <span class="chip">{prev["st"]} → {p["st"]}</span>')
        tl.append(f'<tr><td>{d_fmt(p["d"], True)}</td><td><span class="pill {p["st"]}">{p["st"]}</span>{moved}</td>'
                  f'<td class="num"><b>{p["s"]}</b></td><td class="num">{change_html(p["s"] - prev["s"] if prev else None)}</td>'
                  f'<td>{E(p.get("h") or "")}</td></tr>')

    body = f"""
<p><a class="more" href="../index.html">← Overview</a> &nbsp; <a class="more" href="../accounts.html">All accounts</a></p>
{banner(demo)}
<div class="acct-head" style="margin-bottom:6px">{logo(r['company'], rec.get('meta', {}).get('domain'), 52)}
  <div><h1 style="margin:0">{E(r['company'])}</h1>
  <div class="dates">Last updated {t_fmt(run_at)} · {st} since {d_fmt(status_since(s) or '', True)} ·
  Momentum <span class="{cls}">{mom}</span>{' · ' + E(rec['meta']['domain']) if rec.get('meta', {}).get('domain') else ''}</div></div>
  <div style="margin-left:auto;text-align:right"><span class="score-big {st}">{a['health_score']}</span>
  <div><span class="pill {st}">{st}</span></div></div>
</div>
<div class="grid2 section">
  <div class="card chart-card"><div class="scorerow"><p class="label">Health score history</p>
    <div class="ranges"><button data-range-for="achart" data-range="7">7D</button><button data-range-for="achart" data-range="14">14D</button>
    <button data-range-for="achart" data-range="30">30D</button><button data-range-for="achart" data-range="0" class="on">All</button></div></div>
    {chart(s, chart_id="achart")}
    <div class="chg">1-day {change_html(r['delta'])} · 7-day {change_html(change_over(s, 7))} · {len(s)} days tracked</div></div>
  <div class="card"><p class="label">Agent assessment</p>
    <p style="font-weight:650;margin:0 0 6px">{E(a['headline'])}</p><p style="margin:0">{E(a['reason'])}</p>
    <div class="action"><b>Next action:</b> {E(a['next_action'])}</div>
    <p class="muted" style="font-size:12.5px;margin:10px 0 0">Decided by: {E(who)}{' · overrode the rules' if a.get('overrode_rules') else ''}</p></div>
</div>
<div class="grid2e section">
  <div class="card"><p class="label">Why the score is {a['health_score']}</p>{breakdown_html(r)}
    <p style="margin:14px 0 0">{scale_html([(r['company'][:10], a['health_score'], st)])}</p></div>
  <div class="card"><p class="label">Risks</p><ul>{risks}</ul><p class="label">Opportunities</p><ul>{opps}</ul></div>
</div>
<div class="section"><h2>Evidence, with links to every source</h2><div class="grid2e">{evidence_html(r)}</div></div>
<div class="section"><h2>Update timeline</h2>
<div class="card table-wrap"><table><thead><tr><th>Date</th><th>Status</th><th class="num">Score</th><th class="num">Change</th>
<th>What drove it</th></tr></thead><tbody>{''.join(tl)}</tbody></table></div></div>"""
    return page(r["company"], "accounts", body, run_at, root="../")


def signals_page(results, run_at, demo):
    items = []
    for r in results:
        dom = r["record"].get("meta", {}).get("domain")
        for sig in signals_for(r):
            items.append((sig["date"], f"""
<li class="sig" data-type="{sig['type']}" data-tone="{sig['tone']}" data-name="{E(r['company'] + ' ' + sig['title'])}">
  <span class="when">{d_fmt(sig['date'])}</span>
  {logo(r['company'], dom, 28)}
  <span class="what"><a href="account/{slug(r['company'])}.html"><b>{E(r['company'])}</b></a> · {E(sig['type'])}
  <span class="tag {sig['tone']}">{E(sig['tag'])}</span><br>{E(sig['title'])}</span>
  {ext(sig['url'], 'Verify ↗')}
</li>"""))
    items.sort(key=lambda x: x[0], reverse=True)
    body = f"""
<h1>Signals</h1>
<p class="lead">Every piece of evidence the agent used today, newest first. Each one links to its original source so
you can double-check it. Collected {t_fmt(run_at)}.</p>
{banner(demo)}
<div class="toolbar" data-filter-scope="li.sig">
  <div class="seg" data-group="type"><button class="on" data-value="all">All</button><button data-value="Hiring">Hiring</button>
  <button data-value="News">News</button><button data-value="SEC filing">SEC filings</button></div>
  <div class="seg" data-group="tone"><button class="on" data-value="all">Any impact</button><button data-value="severe">Severe</button>
  <button data-value="negative">Negative</button><button data-value="positive">Positive</button></div>
  <input type="search" placeholder="Search signals">
</div>
<div class="card"><ul class="ev">{''.join(i for _, i in items) or '<li class="muted">No signals today.</li>'}</ul></div>"""
    return page("Signals", "signals", body, run_at)


def timeline_page(history, run_at, site_dir, demo):
    runs = history["runs"]
    hour_ok = run_at.hour < 7 or (run_at.hour == 7 and run_at.minute < 7)
    next_run = run_at.date() if hour_ok else run_at.date() + dt.timedelta(days=1)
    entries = []
    for i in range(len(runs) - 1, -1, -1):
        run, prev = runs[i], (runs[i - 1] if i > 0 else None)
        accts = run["accounts"]
        c = {s: sum(a["status"] == s for a in accts.values()) for s in ORDER}
        moves, movers = [], []
        if prev:
            for name, a in accts.items():
                b = prev["accounts"].get(name)
                if b and b["status"] != a["status"]:
                    moves.append(f'<span class="chip"><b>{E(name)}</b> {b["status"]} → {a["status"]}</span>')
                if b and abs(a["score"] - b["score"]) >= 5:
                    movers.append(f'<span class="chip">{E(name)} {change_html(a["score"] - b["score"])}</span>')
        raw = site_dir / "data" / "snapshots" / f"{run['date']}.json"
        raw_link = f' · <a class="src" href="data/snapshots/{run["date"]}.json">Raw data ↗</a>' if raw.exists() else ""
        when = (dt.datetime.fromisoformat(run["run_at"]).strftime("%I:%M %p ET").lstrip("0") if run.get("run_at") else "")
        entries.append(f"""<li class="{'latest' if i == len(runs) - 1 else ''}"><div class="card">
<div class="scorerow"><b>{d_fmt(run['date'], True)}</b><span class="dates">{when}{raw_link}</span></div>
<div class="mini" style="margin:8px 0"><span class="pill Critical">{c['Critical']} critical</span>
<span class="pill Watch">{c['Watch']} watch</span><span class="pill Healthy">{c['Healthy']} healthy</span></div>
{f'<p style="margin:6px 0">{E(run["summary"])}</p>' if run.get('summary') else ''}
{'<p class="label" style="margin-top:8px">Status changes</p><div class="mini">' + ''.join(moves) + '</div>' if moves else ''}
{'<p class="label" style="margin-top:8px">Biggest moves (5+ points)</p><div class="mini">' + ''.join(movers) + '</div>' if movers else ''}
{'' if moves or movers or not prev else '<p class="muted" style="margin:4px 0 0">No status changes.</p>'}
</div></li>""")

    steps = [("Trigger", "GitHub Actions starts the run at about 7:07 AM ET"),
             ("Load accounts", "Reads the account list and CRM fields"),
             ("Collect", "Job boards, news, and SEC filings for each account"),
             ("Compare", "Today vs. the previous run"),
             ("Score", "Transparent rules: 0 to 100"),
             ("Agent review", "Claude investigates each account and decides"),
             ("Save", "Snapshot and history committed to the repo"),
             ("Publish", "This website is rebuilt"),
             ("Alert", "Email digest, critical accounts first")]
    body = f"""
<h1>Timeline</h1>
<p class="lead">Every daily run, newest first: what changed, which accounts moved, and the raw data behind it.</p>
{banner(demo)}
<div class="grid2e">
  <div class="card"><p class="label">Automation status</p><ul class="ev">
    <li><span class="what">Last run</span><b>{t_fmt(run_at)}</b></li>
    <li><span class="what">Next scheduled run</span><b>{d_fmt(next_run.isoformat(), True)} at 7:07 AM ET</b></li>
    <li><span class="what">Schedule</span><b>Every day, automatically</b></li>
    <li><span class="what">Runs recorded</span><b>{len(runs)}</b></li></ul></div>
  <div class="card"><p class="label">What happens on every run</p><div class="steps">
    {''.join(f'<div class="step"><b>{E(t)}</b><span class="muted">{E(d)}</span></div>' for t, d in steps)}</div></div>
</div>
<div class="section"><h2>Run history</h2><ul class="tl">{''.join(entries)}</ul></div>"""
    return page("Timeline", "timeline", body, run_at)


def methodology_page(run_at):
    rules = [("Serious news: layoffs, breach, bankruptcy, acquired by another company", "−30"),
             ("Open roles down 40% or more since the last run (possible hiring freeze)", "−25"),
             ("SEC 8-K Item 2.05: restructuring or layoffs", "−20"),
             ("Renewal within 60 days and no contact in 30+ days", "−15"),
             ("Open roles down 20–39%", "−10"),
             ("Renewal within 60 days", "−10"),
             ("SEC 8-K Item 5.02: executive or director change", "−10"),
             ("No contact in 45+ days", "−10"),
             ("Negative news (lawsuit, outage, executive departure)", "−8 each, up to −20"),
             ("Open roles up 20% or more", "+10"),
             ("Positive news (funding, expansion, launch, partnership)", "+5 each, up to +15"),
             ("5+ new roles posted in the last 7 days", "+5"),
             ("SEC 8-K Item 2.01: acquisition", "+5")]
    rows = "".join(f'<tr><td>{E(t)}</td><td class="num"><b class="{"down" if p.startswith("−") else "up"}">{p}</b></td></tr>'
                   for t, p in rules)
    body = f"""
<h1>How it works</h1>
<p class="lead">Account Pulse gives every account a health score from 0 to 100 every morning. Rules do the math so the
score is explainable; an AI agent then reviews the evidence and makes the final call.</p>
<div class="card"><p class="label">The grading scale</p>{scale_html()}
<p class="muted" style="margin:12px 0 0">Every account starts at 70 (healthy, nothing notable). Risks lower the score and
opportunities raise it. Overlapping risks are capped at −55 in total, because one event (like a layoff) often shows up in
the news, an SEC filing, and the job board at once.</p></div>
<div class="grid2e section">
  <div class="card table-wrap"><p class="label">Scoring rules</p><table><thead><tr><th>Signal</th><th class="num">Points</th></tr></thead>
  <tbody>{rows}</tbody></table></div>
  <div class="card"><p class="label">What the numbers mean</p><ul class="ev">
    <li><span class="what"><b>Score</b><br><span class="muted">0 to 100. Higher is healthier.</span></span></li>
    <li><span class="what"><b>1-day and 7-day change</b><br><span class="muted">Points gained or lost since yesterday and a week ago.</span></span></li>
    <li><span class="what"><b>Momentum</b><br><span class="muted">Improving if up 5+ points over 7 days, Declining if down 5+, otherwise Stable.</span></span></li>
    <li><span class="what"><b>Status since</b><br><span class="muted">The first day of the account's current status.</span></span></li>
    <li><span class="what"><b>ARR not healthy</b><br><span class="muted">Annual contract value of all accounts in Watch or Critical.</span></span></li></ul>
  <p class="label" style="margin-top:14px">The AI agent</p>
  <p style="margin:0">For each account, a Claude agent starts from the rule score, decides which evidence to check (hiring, news,
  filings, CRM, score history), and submits a status, a reason, and one next action. It may override the rules only with
  evidence, and it may only use facts the data returned. If it's unavailable, the rule score is used.</p></div>
</div>
<div class="card section table-wrap"><p class="label">Data sources</p><table>
<thead><tr><th>Source</th><th>What it tells us</th><th>Updated</th><th>Link</th></tr></thead><tbody>
<tr><td>Greenhouse, Lever, Ashby job boards</td><td>Hiring growth, freezes, new teams</td><td>Daily</td><td>{ext('https://developers.greenhouse.io/job-board.html', 'Docs ↗')}</td></tr>
<tr><td>GNews API</td><td>Layoffs, funding, leadership, launches (last 14 days)</td><td>Daily</td><td>{ext('https://gnews.io/docs/v4', 'Docs ↗')}</td></tr>
<tr><td>SEC EDGAR</td><td>Official filings from public companies (last 30 days)</td><td>Daily</td><td>{ext('https://www.sec.gov/search-filings/edgar-application-programming-interfaces', 'Docs ↗')}</td></tr>
<tr><td>CRM fields</td><td>Renewal date, last contact, contract value</td><td>Daily</td><td><span class="muted">Sample values</span></td></tr>
<tr><td>Claude API</td><td>Agent review and summaries</td><td>Daily</td><td>{ext('https://docs.claude.com', 'Docs ↗')}</td></tr>
</tbody></table></div>"""
    return page("How it works", "method", body, run_at)


# ----------------------------------------------------------------------------
# Build
# ----------------------------------------------------------------------------

def build_site(site_dir, data_dir, results, summary, run_at, history, demo=False):
    site_dir = Path(site_dir)
    (site_dir / "assets").mkdir(parents=True, exist_ok=True)
    (site_dir / "account").mkdir(exist_ok=True)
    for f in ASSETS.iterdir():
        shutil.copy(f, site_dir / "assets" / f.name)

    # Publish raw data so every page can link to it
    raw_dir = site_dir / "data" / "snapshots"
    raw_dir.mkdir(parents=True, exist_ok=True)
    for snap in Path(data_dir, "snapshots").glob("*.json"):
        shutil.copy(snap, raw_dir / snap.name)
    if Path(data_dir, "history.json").exists():
        shutil.copy(Path(data_dir, "history.json"), site_dir / "data" / "history.json")

    for r in results:
        r["series"] = series_for(history, r["company"])
    results = sorted(results, key=lambda r: (ORDER[r["assessment"]["status"]],
                                             r["assessment"]["health_score"] * (-1 if r["assessment"]["status"] == "Healthy" else 1)))

    (site_dir / "index.html").write_text(overview(results, summary, run_at, history, demo))
    (site_dir / "accounts.html").write_text(accounts_page(results, run_at, demo))
    (site_dir / "signals.html").write_text(signals_page(results, run_at, demo))
    (site_dir / "timeline.html").write_text(timeline_page(history, run_at, site_dir, demo))
    (site_dir / "methodology.html").write_text(methodology_page(run_at))
    for r in results:
        (site_dir / "account" / f"{slug(r['company'])}.html").write_text(account_page(r, run_at, demo))
