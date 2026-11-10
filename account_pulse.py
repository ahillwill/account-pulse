#!/usr/bin/env python3
"""
Account Pulse: an AI agent that checks every customer account each morning and flags
which are growing, which need watching, and which are critical.

Daily pipeline
  1. Load accounts            accounts.csv
  2. Collect                  hiring (job boards), news (GNews), filings (SEC EDGAR), CRM fields
  3. Compare                  today vs. the last snapshot
  4. Score                    transparent rules -> 0-100 + flags
  5. Agent review             Claude investigates each account with tools and makes the final call
  6. Summarize                one paragraph across the portfolio
  7. Save                     data/snapshots/<date>.json and data/history.json
  8. Publish                  docs/index.html (GitHub Pages dashboard)
  9. Alert                    email digest

Usage
  python3 account_pulse.py --demo --open     # fictional data, works offline
  python3 account_pulse.py --check           # test every data source
  python3 account_pulse.py                   # the real daily run
"""

import argparse
import csv
import datetime as dt
import json
import os
import sys
import time
import webbrowser
from pathlib import Path

from pulse import agent, health, notify, report, site, sources

ROOT = Path(__file__).resolve().parent
HISTORY_KEEP = 90


def now_et():
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        return dt.datetime.now(dt.timezone(dt.timedelta(hours=-5)))


def load_env():
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def load_accounts(path):
    with open(path, newline="", encoding="utf-8") as f:
        rows = [{k: (v or "").strip() for k, v in r.items()} for r in csv.DictReader(f)]
    rows = [r for r in rows if r.get("company")]
    for r in rows:
        r["ats"] = r.get("ats", "").lower()
    return rows


# ----------------------------------------------------------------------------
# Storage
# ----------------------------------------------------------------------------

def load_previous_snapshot(snap_dir, today):
    files = sorted(p for p in snap_dir.glob("*.json") if p.stem < today.isoformat())
    if not files:
        return {}
    return json.loads(files[-1].read_text()).get("records", {})


def load_history(path):
    return json.loads(path.read_text()) if path.exists() else {"runs": []}


def account_history(history, company, limit=14):
    out = []
    for run in history["runs"][-limit:]:
        if company in run["accounts"]:
            out.append({"date": run["date"], **run["accounts"][company]})
    return out


# ----------------------------------------------------------------------------
# Demo data (fictional)
# ----------------------------------------------------------------------------

def build_demo(today):
    data = json.loads((ROOT / "sample_data" / "demo_accounts.json").read_text())
    records, previous, history = {}, {}, {"runs": []}
    for a in data["accounts"]:
        name = a["company"]
        ids = [f"{name}-{i}" for i in range(a["open_roles"])]
        kept = ids[a["new_since_last"]:]
        closed = max(0, a["prev_open_roles"] - len(kept))
        prev_ids = kept + [f"{name}-old-{i}" for i in range(closed)]
        roles = [{"title": t, "location": "New York, NY", "url": "",
                  "posted": (today - dt.timedelta(days=d)).isoformat()} for t, d in a["roles"]]
        records[name] = {
            "company": name,
            "jobs": {"available": True, "open_roles": a["open_roles"], "role_ids": ids, "has_post_dates": True,
                     "new_7d": a["new_7d"], "new_30d": a["new_7d"] + 2, "recent_roles": roles},
            "news": {"available": True, "articles": [
                {"title": t, "source": s, "url": "", "published": (today - dt.timedelta(days=d)).isoformat(),
                 "tone": tone} for t, s, d, tone in a["news"]]},
            "filings": {"available": True, "filings": [
                {"form": f, "date": (today - dt.timedelta(days=d)).isoformat(), "items": items,
                 "labels": [sources.ITEM_LABELS.get(c, c) for c in items], "url": ""} for f, d, items in a["filings"]]}
            if a["filings"] else {"available": False, "error": "demo: private company"},
            "crm": {"renewal_date": (today + dt.timedelta(days=a["renewal_in_days"])).isoformat(),
                    "last_contact": (today - dt.timedelta(days=a["contact_days_ago"])).isoformat(),
                    "arr": str(a["arr"]), "owner": a["owner"]},
            "meta": {"domain": "", "ats": "", "board_token": "", "cik": "", "news_query": ""},
        }
        previous[name] = {"jobs": {"available": True, "open_roles": a["prev_open_roles"], "role_ids": prev_ids}}
        for i, score in enumerate(a["history"]):
            day = (today - dt.timedelta(days=len(a["history"]) - i)).isoformat()
            if len(history["runs"]) <= i:
                history["runs"].append({"date": day, "accounts": {}})
            history["runs"][i]["accounts"][name] = {"score": score, "status": health.status_for(score)}
    return records, previous, history


# ----------------------------------------------------------------------------
# Commands
# ----------------------------------------------------------------------------

def run_check(accounts_path):
    today = now_et().date()
    accounts = load_accounts(accounts_path)
    print(f"Checking data sources for {len(accounts)} accounts...\n")
    print(f"  {'Company':<20} {'Jobs':<22} {'News':<22} SEC filings")
    for acct in accounts:
        rec = sources.collect_account(acct, today)
        def show(part, ok_text):
            return ok_text if part.get("available") else "-- " + part.get("error", "")[:19]
        print(f"  {acct['company']:<20} "
              f"{show(rec['jobs'], str(rec['jobs'].get('open_roles')) + ' roles'):<22} "
              f"{show(rec['news'], str(len(rec['news'].get('articles', []))) + ' articles'):<22} "
              f"{show(rec['filings'], str(len(rec['filings'].get('filings', []))) + ' recent')}")
        time.sleep(0.3)
    print("\nFix or clear any '--' sources in accounts.csv you expected to work.")
    print("Job board tip: the careers page links show boards.greenhouse.io/<token>, jobs.lever.co/<token>,")
    print("or jobs.ashbyhq.com/<token>.")


def run(args):
    run_at = now_et()
    today = run_at.date()
    demo = args.demo
    data_dir = ROOT / ("output/demo_data" if demo else "data")
    site_dir = ROOT / ("output/demo" if demo else "docs")
    snap_dir = data_dir / "snapshots"
    for d in (snap_dir, site_dir):
        d.mkdir(parents=True, exist_ok=True)
    history_path = data_dir / "history.json"

    print(f"\nAccount Pulse · {run_at:%a %b %d, %Y %I:%M %p} ET" + (" · DEMO" if demo else ""))

    # 1-2. Load and collect
    if demo:
        records, previous, history = build_demo(today)
        print(f"  Loaded {len(records)} fictional demo accounts")
    else:
        accounts = load_accounts(args.accounts)
        previous = load_previous_snapshot(snap_dir, today)
        history = load_history(history_path)
        records = {}
        print(f"  Collecting data for {len(accounts)} accounts...")
        for acct in accounts:
            records[acct["company"]] = sources.collect_account(acct, today)
            r = records[acct["company"]]
            ok = [k for k in ("jobs", "news", "filings") if r[k].get("available")]
            print(f"    {acct['company']:<20} sources: {', '.join(ok) or 'none'}")
            time.sleep(0.3)

    for rec in records.values():
        rec["checked_at"] = run_at.isoformat()

    # 3-5. Compare, score, agent review
    use_ai = not args.no_ai
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())
    print(f"  Assessing accounts with {'the Claude agent' if use_ai and has_key else 'rules only'}...")
    results = []
    for name, rec in records.items():
        health.compare(rec, previous.get(name))
        rules = health.rule_score(rec, today)
        hist = account_history(history, name)
        assessment = agent.assess(rec, rules, hist, use_ai=use_ai)
        last = hist[-1]["score"] if hist else None
        delta = assessment["health_score"] - last if last is not None else None
        results.append({"company": name, "record": rec, "rules": rules, "assessment": assessment,
                        "delta": delta, "history": hist + [{"date": today.isoformat(),
                                                            "score": assessment["health_score"]}]})
        a = assessment
        print(f"    {name:<20} {a['status']:<8} {a['health_score']:>3}  {a['headline'][:60]}")

    # 6. Summary
    summary = agent.portfolio_summary(results, use_ai=use_ai)

    # 7. Save snapshot and history
    snapshot = {"date": today.isoformat(), "run_at": run_at.isoformat(),
                "records": records, "assessments": {r["company"]: r["assessment"] for r in results}}
    (snap_dir / f"{today.isoformat()}.json").write_text(json.dumps(snapshot, indent=1, default=str))
    history["runs"] = [r for r in history["runs"] if r["date"] != today.isoformat()]
    history["runs"].append({"date": today.isoformat(), "run_at": run_at.isoformat(), "summary": summary,
                            "accounts": {r["company"]: {"score": r["assessment"]["health_score"],
                                                        "status": r["assessment"]["status"],
                                                        "headline": r["assessment"]["headline"]} for r in results}})
    history["runs"] = history["runs"][-HISTORY_KEEP:]
    history_path.write_text(json.dumps(history, indent=1))

    # 8. Publish dashboard
    site.build_site(site_dir, data_dir, results, summary, run_at, history, demo=demo)
    subject, body_html, body_text = report.render_digest(results, summary, run_at,
                                                         os.environ.get("DASHBOARD_URL", ""))
    (site_dir / "digest.html").write_text(body_html)

    # 9. Email
    if args.no_email:
        sent, note = False, "skipped (--no-email)"
    else:
        sent, note = notify.send_digest(subject, body_html, body_text)

    print(f"\n  {summary}\n")
    print(f"  Dashboard: {site_dir / 'index.html'}  (5 pages + account pages)")
    print(f"  Digest:    {site_dir / 'digest.html'}  (email {note})\n")
    if args.open:
        webbrowser.open((site_dir / "index.html").as_uri())


def main():
    p = argparse.ArgumentParser(description="Daily account health agent.")
    p.add_argument("--accounts", default="accounts.csv")
    p.add_argument("--demo", action="store_true", help="Run on fictional sample accounts")
    p.add_argument("--check", action="store_true", help="Test every data source and exit")
    p.add_argument("--no-ai", action="store_true", help="Use rules only (no Claude calls)")
    p.add_argument("--no-email", action="store_true", help="Don't send the email digest")
    p.add_argument("--open", action="store_true", help="Open the dashboard when done")
    args = p.parse_args()

    os.chdir(ROOT)
    load_env()
    if args.check:
        run_check(args.accounts)
    else:
        run(args)


if __name__ == "__main__":
    sys.exit(main())
