"""
Outputs: the live dashboard (docs/index.html, served by GitHub Pages) and the daily email digest.
"""

import datetime as dt
import html

E = html.escape
ORDER = {"Critical": 0, "Watch": 1, "Healthy": 2}
COLORS = {"Critical": "#d33a2c", "Watch": "#d98a00", "Healthy": "#2f8a57"}
DOT = {"Critical": "🔴", "Watch": "🟡", "Healthy": "🟢"}


def sort_results(results):
    return sorted(results, key=lambda r: (ORDER[r["assessment"]["status"]],
                                         r["assessment"]["health_score"] * (-1 if r["assessment"]["status"] == "Healthy" else 1)))


def money(v):
    try:
        return f"${float(v):,.0f}"
    except (TypeError, ValueError):
        return ""


def arr_at_risk(results):
    total = 0.0
    for r in results:
        if r["assessment"]["status"] != "Healthy":
            try:
                total += float(r["record"]["crm"].get("arr") or 0)
            except ValueError:
                pass
    return total


def trend_text(delta):
    if delta is None:
        return ""
    if delta > 0:
        return f"▲ {delta}"
    if delta < 0:
        return f"▼ {abs(delta)}"
    return "– 0"


def sparkline(points, color, w=120, h=28):
    if len(points) < 2:
        return ""
    lo, hi = 0, 100
    step = w / (len(points) - 1)
    coords = " ".join(f"{i * step:.1f},{h - (p - lo) / (hi - lo) * h:.1f}" for i, p in enumerate(points))
    return (f'<svg class="spark" viewBox="0 0 {w} {h}" width="{w}" height="{h}" aria-hidden="true">'
            f'<polyline points="{coords}" fill="none" stroke="{color}" stroke-width="2" '
            f'stroke-linejoin="round" stroke-linecap="round"/></svg>')


# ----------------------------------------------------------------------------
# Dashboard
# ----------------------------------------------------------------------------

def evidence_html(rec):
    parts = []
    jobs = rec["jobs"]
    if jobs.get("available"):
        change = ""
        if jobs.get("change_pct") is not None:
            change = f" · {jobs['change_pct']:+.0f}% vs last run"
        roles = "".join(
            f'<li>{"<a href=" + chr(34) + E(j["url"]) + chr(34) + " target=_blank rel=noopener>" if j["url"] else ""}'
            f'{E(j["title"])}{"</a>" if j["url"] else ""}'
            f'{"<span class=muted> · " + E(j["posted"]) + "</span>" if j.get("posted") else ""}</li>'
            for j in jobs.get("recent_roles", [])[:5])
        parts.append(f"<h4>Hiring</h4><p class=muted>{jobs['open_roles']} open roles{change} · "
                     f"{jobs.get('new_7d', 0)} posted in last 7 days</p><ul>{roles}</ul>")
    else:
        parts.append(f"<h4>Hiring</h4><p class=muted>Unavailable: {E(jobs.get('error', ''))}</p>")

    news = rec["news"]
    if news.get("available"):
        items = "".join(
            f'<li><span class="tone t-{a["tone"]}">{a["tone"]}</span> '
            f'<a href="{E(a["url"])}" target=_blank rel=noopener>{E(a["title"])}</a>'
            f'<span class=muted> · {E(a["source"])} · {E(a["published"])}</span></li>'
            for a in news["articles"][:5]) or "<li class=muted>No news in the last 14 days</li>"
        parts.append(f"<h4>News</h4><ul>{items}</ul>")
    else:
        parts.append(f"<h4>News</h4><p class=muted>Unavailable: {E(news.get('error', ''))}</p>")

    filings = rec["filings"]
    if filings.get("available"):
        items = "".join(
            f'<li><a href="{E(f["url"])}" target=_blank rel=noopener>{E(f["form"])}</a> · {E(f["date"])} · '
            f'{E(", ".join(f["labels"]))}</li>' for f in filings["filings"][:5]) \
            or "<li class=muted>No filings in the last 30 days</li>"
        parts.append(f"<h4>SEC filings</h4><ul>{items}</ul>")

    crm = rec["crm"]
    if any(crm.values()):
        parts.append(f"<h4>Relationship</h4><p class=muted>Renewal {E(crm.get('renewal_date') or 'n/a')} · "
                     f"Last contact {E(crm.get('last_contact') or 'n/a')} · {money(crm.get('arr'))} ARR"
                     f"{' · Owner ' + E(crm['owner']) if crm.get('owner') else ''}</p>")
    return "".join(parts)


def render_dashboard(results, summary, run_at, history_dates, demo=False):
    results = sort_results(results)
    counts = {s: sum(r["assessment"]["status"] == s for r in results) for s in ORDER}
    rows = []
    for r in results:
        a = r["assessment"]
        color = COLORS[a["status"]]
        source = "AI agent" if a["source"] == "agent" else "Rules"
        tools = f' · checked {len(set(a["tools_used"]))} sources' if a.get("tools_used") else ""
        override = " · overrode rules" if a.get("overrode_rules") else ""
        rows.append(f"""
<article class="acct">
  <div class="top">
    <span class="pill" style="background:{color}">{a['status']}</span>
    <h3>{E(r['company'])}</h3>
    <div class="score"><b>{a['health_score']}</b><span class="trend">{trend_text(r.get('delta'))}</span></div>
  </div>
  <div class="mid">
    <div><p class="headline">{E(a['headline'])}</p><p>{E(a['reason'])}</p>
    <p class="action"><b>Next action:</b> {E(a['next_action'])}</p></div>
    {sparkline([h['score'] for h in r.get('history', [])], color)}
  </div>
  <details><summary>Evidence <span class="muted">· {source}{tools}{override}</span></summary>
    <div class="evidence">{evidence_html(r['record'])}</div></details>
</article>""")

    runs = "".join(f"<li>{E(d)}</li>" for d in reversed(history_dates[-10:]))
    banner = ('<div class="banner">Demo mode: fictional companies and sample data.</div>' if demo else
              '<div class="banner subtle">Renewal dates, last contact, and ARR are sample CRM values for '
              'demonstration. Hiring, news, and filings are live.</div>')
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Account Pulse</title>
<style>
:root {{ --bg:#f5f4f0; --card:#fff; --ink:#18181b; --muted:#6b6b73; --line:#e3e1db; --accent:#2b59c3; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#121214; --card:#1c1c20; --ink:#ededf0;
  --muted:#9b9ba6; --line:#2d2d33; --accent:#7d9cff; }} }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--ink);
  font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,sans-serif; }}
main {{ max-width:980px; margin:0 auto; padding:28px 16px 64px; }}
.brand {{ display:flex; align-items:center; gap:10px; }}
.brand .dot {{ width:12px; height:12px; border-radius:50%; background:#2f8a57;
  box-shadow:0 0 0 0 rgba(47,138,87,.6); animation:p 2s infinite; }}
@keyframes p {{ 70% {{ box-shadow:0 0 0 10px rgba(47,138,87,0); }} 100% {{ box-shadow:0 0 0 0 rgba(47,138,87,0); }} }}
h1 {{ margin:0; font-size:26px; letter-spacing:-.01em; }}
.updated {{ color:var(--muted); margin:6px 0 18px; }}
.updated b {{ color:var(--ink); }}
.banner {{ background:#fff3d1; color:#5f4700; border-radius:10px; padding:9px 14px; margin-bottom:16px; font-size:14px; }}
.banner.subtle {{ background:var(--card); color:var(--muted); border:1px solid var(--line); }}
.kpis {{ display:grid; grid-template-columns:repeat(5,1fr); gap:10px; margin-bottom:16px; }}
.kpi {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:12px 14px; }}
.kpi b {{ display:block; font-size:24px; }} .kpi span {{ color:var(--muted); font-size:13px; }}
.summary {{ background:var(--card); border:1px solid var(--line); border-left:4px solid var(--accent);
  border-radius:12px; padding:14px 16px; margin-bottom:20px; }}
.summary .label, h4 {{ font-size:12px; text-transform:uppercase; letter-spacing:.07em; color:var(--muted); margin:0 0 4px; }}
.acct {{ background:var(--card); border:1px solid var(--line); border-radius:14px; padding:16px 18px; margin-bottom:12px; }}
.top {{ display:flex; align-items:center; gap:10px; }}
.top h3 {{ margin:0; font-size:18px; flex:1; }}
.pill {{ color:#fff; font-size:12px; font-weight:700; padding:3px 10px; border-radius:999px; }}
.score {{ text-align:right; }} .score b {{ font-size:22px; }}
.trend {{ display:block; font-size:12px; color:var(--muted); }}
.mid {{ display:flex; gap:16px; align-items:flex-start; justify-content:space-between; }}
.mid p {{ margin:6px 0; }} .headline {{ font-weight:600; }}
.action {{ background:var(--bg); border-radius:8px; padding:8px 10px; }}
.spark {{ flex-shrink:0; margin-top:10px; }}
details summary {{ cursor:pointer; color:var(--accent); font-weight:600; margin-top:6px; }}
.evidence {{ display:grid; grid-template-columns:1fr 1fr; gap:4px 20px; margin-top:8px; }}
.evidence h4 {{ margin-top:10px; }}
.evidence ul {{ margin:0; padding-left:18px; }} .evidence a {{ color:var(--ink); }}
.muted {{ color:var(--muted); }}
.tone {{ font-size:11px; padding:1px 7px; border-radius:999px; border:1px solid var(--line); }}
.t-severe {{ color:#d33a2c; border-color:#d33a2c; }} .t-negative {{ color:#d98a00; border-color:#d98a00; }}
.t-positive {{ color:#2f8a57; border-color:#2f8a57; }}
footer {{ margin-top:28px; color:var(--muted); font-size:13px; }}
footer ul {{ padding-left:18px; columns:2; }}
@media (max-width:640px) {{ .kpis {{ grid-template-columns:repeat(2,1fr); }} .evidence {{ grid-template-columns:1fr; }}
  .spark {{ display:none; }} }}
</style></head><body><main>
<div class="brand"><span class="dot"></span><h1>Account Pulse</h1></div>
<p class="updated">Last updated <b>{run_at:%A, %B %d, %Y at %I:%M %p} ET</b> · runs automatically every morning</p>
{banner}
<div class="kpis">
  <div class="kpi"><b>{len(results)}</b><span>Accounts monitored</span></div>
  <div class="kpi"><b style="color:{COLORS['Critical']}">{counts['Critical']}</b><span>Critical</span></div>
  <div class="kpi"><b style="color:{COLORS['Watch']}">{counts['Watch']}</b><span>Watch</span></div>
  <div class="kpi"><b style="color:{COLORS['Healthy']}">{counts['Healthy']}</b><span>Healthy</span></div>
  <div class="kpi"><b>{money(arr_at_risk(results)) or '$0'}</b><span>ARR not healthy</span></div>
</div>
<div class="summary"><p class="label">Agent summary</p><p style="margin:0">{E(summary)}</p></div>
{''.join(rows)}
<footer>
  <p>How it works: every morning Account Pulse pulls hiring, news, and SEC filings for each account, compares them to
  the previous run, scores health with transparent rules, and then a Claude agent investigates each account and
  makes the final call.</p>
  <p>Recent runs:</p><ul>{runs}</ul>
</footer>
</main></body></html>"""


# ----------------------------------------------------------------------------
# Email digest
# ----------------------------------------------------------------------------

def render_digest(results, summary, run_at, dashboard_url=""):
    results = sort_results(results)
    counts = {s: sum(r["assessment"]["status"] == s for r in results) for s in ORDER}
    subject = (f"Account Pulse · {run_at:%b %d} · {counts['Critical']} critical, "
               f"{counts['Watch']} watch, {counts['Healthy']} healthy")

    changed = [r for r in results if r["assessment"]["status"] != "Healthy"
               or (r.get("delta") or 0) >= 10 or r["assessment"]["opportunities"]]
    quiet = [r for r in results if r not in changed]

    blocks_html, blocks_text = [], []
    for r in changed:
        a = r["assessment"]
        trend = f" ({trend_text(r['delta'])})" if r.get("delta") else ""
        blocks_html.append(f"""
<tr><td style="padding:14px 0;border-bottom:1px solid #eee;">
  <div style="font-size:16px;font-weight:700;">{DOT[a['status']]} {a['status']}: {E(r['company'])}
    <span style="color:#777;font-weight:400;">· {a['health_score']}{E(trend)}</span></div>
  <div style="margin:6px 0;color:#222;">{E(a['reason'])}</div>
  <div style="background:#f4f4f1;border-radius:6px;padding:8px 10px;"><b>Next action:</b> {E(a['next_action'])}</div>
</td></tr>""")
        blocks_text.append(f"{DOT[a['status']]} {a['status']}: {r['company']} · {a['health_score']}{trend}\n"
                           f"{a['reason']}\nNext action: {a['next_action']}\n")

    link_html = (f'<p><a href="{E(dashboard_url)}" style="color:#2b59c3;">Open the full dashboard</a></p>'
                 if dashboard_url else "")
    quiet_line = f"{len(quiet)} other account(s): no notable changes." if quiet else ""
    body_html = f"""<!doctype html><html><body style="margin:0;background:#fff;">
<table role="presentation" width="100%" style="max-width:620px;margin:0 auto;font-family:-apple-system,Segoe UI,Arial,sans-serif;font-size:15px;line-height:1.5;color:#18181b;">
<tr><td style="padding:20px 0 6px;"><div style="font-size:20px;font-weight:700;">Account Pulse</div>
<div style="color:#777;">{run_at:%A, %B %d, %Y}</div></td></tr>
<tr><td style="padding:10px 14px;background:#f1f4fb;border-radius:8px;">{E(summary)}</td></tr>
{''.join(blocks_html)}
<tr><td style="padding:14px 0;color:#777;">{E(quiet_line)}{link_html}</td></tr>
</table></body></html>"""
    body_text = (f"Account Pulse · {run_at:%A, %B %d, %Y}\n\n{summary}\n\n" + "\n".join(blocks_text)
                 + (f"\n{quiet_line}\n" if quiet_line else "") + (f"\nDashboard: {dashboard_url}\n" if dashboard_url else ""))
    return subject, body_html, body_text
