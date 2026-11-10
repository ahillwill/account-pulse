"""
Rule-based health scoring. Transparent on purpose: every point change comes with a reason.
The agent uses this score as its starting point and can override it with evidence.

Start at 70. Risks subtract, opportunities add. Clamp to 0-100.
  Critical < 45 <= Watch < 65 <= Healthy
"""

import datetime as dt

BASE = 70
CRITICAL_BELOW, WATCH_BELOW = 45, 65


def days_until(date_s, today):
    try:
        return (dt.date.fromisoformat(date_s) - today).days
    except (TypeError, ValueError):
        return None


def compare(record, previous):
    """Add day-over-day hiring changes using yesterday's snapshot (if any)."""
    jobs = record["jobs"]
    prev_jobs = (previous or {}).get("jobs") or {}
    if jobs.get("available") and prev_jobs.get("available"):
        before, now = prev_jobs["open_roles"], jobs["open_roles"]
        jobs["prev_open_roles"] = before
        jobs["change_pct"] = round((now - before) / before * 100, 1) if before else None
        prev_ids = set(prev_jobs.get("role_ids", []))
        jobs["new_since_last"] = len([i for i in jobs.get("role_ids", []) if i not in prev_ids])
        jobs["closed_since_last"] = len(prev_ids - set(jobs.get("role_ids", [])))
    return record


def status_for(score):
    return "Critical" if score < CRITICAL_BELOW else "Watch" if score < WATCH_BELOW else "Healthy"


def rule_score(record, today):
    flags = []

    def add(kind, points, text):
        flags.append({"kind": kind, "points": points, "text": text})

    # --- Hiring -------------------------------------------------------------
    jobs = record["jobs"]
    if jobs.get("available"):
        pct = jobs.get("change_pct")
        if pct is not None:
            if pct <= -40:
                add("risk", -25, f"Open roles fell {abs(pct):.0f}% since the last run (possible hiring freeze)")
            elif pct <= -20:
                add("risk", -10, f"Open roles fell {abs(pct):.0f}% since the last run")
            elif pct >= 20:
                add("opportunity", 10, f"Open roles up {pct:.0f}% since the last run")
        if jobs.get("new_7d", 0) >= 5:
            add("opportunity", 5, f"{jobs['new_7d']} new roles posted in the last 7 days")
        if jobs.get("open_roles", 0) == 0:
            add("risk", -10, "No open roles listed")

    # --- News ---------------------------------------------------------------
    news = record["news"]
    if news.get("available"):
        severe = [a for a in news["articles"] if a["tone"] == "severe"]
        negative = [a for a in news["articles"] if a["tone"] == "negative"]
        positive = [a for a in news["articles"] if a["tone"] == "positive"]
        if severe:
            add("risk", -30, f"Serious news: {severe[0]['title'][:90]}")
        if negative:
            add("risk", max(-20, -8 * len(negative)), f"{len(negative)} negative news item(s)")
        if positive:
            add("opportunity", min(15, 5 * len(positive)), f"{len(positive)} positive news item(s)")

    # --- SEC filings ----------------------------------------------------------
    filings = record["filings"]
    if filings.get("available"):
        codes = {c for f in filings["filings"] for c in f["items"]}
        if "1.03" in codes:
            add("risk", -40, "Bankruptcy filing")
        if "2.05" in codes:
            add("risk", -20, "Filed a restructuring or layoff disclosure (8-K Item 2.05)")
        if "5.02" in codes:
            add("risk", -10, "Executive or director change filed (8-K Item 5.02)")
        if "2.01" in codes:
            add("opportunity", 5, "Acquisition or sale of assets filed (8-K Item 2.01)")

    # --- Relationship (CRM) ---------------------------------------------------
    crm = record["crm"]
    renewal_in = days_until(crm.get("renewal_date"), today)
    since_contact = days_until(crm.get("last_contact"), today)
    since_contact = -since_contact if since_contact is not None else None
    if renewal_in is not None and 0 <= renewal_in <= 60:
        add("risk", -10, f"Renewal in {renewal_in} days")
        if since_contact is not None and since_contact > 30:
            add("risk", -15, f"Renewal is close and there's been no contact in {since_contact} days")
    elif since_contact is not None and since_contact > 45:
        add("risk", -10, f"No contact in {since_contact} days")

    risk = max(-55, sum(f["points"] for f in flags if f["points"] < 0))   # overlapping signals often describe one event
    gain = sum(f["points"] for f in flags if f["points"] > 0)
    score = max(0, min(100, BASE + risk + gain))
    flags.sort(key=lambda f: -abs(f["points"]))
    sources_ok = sum(bool(record[k].get("available")) for k in ("jobs", "news", "filings"))
    return {"score": score, "status": status_for(score), "flags": flags, "sources_ok": sources_ok,
            "renewal_in_days": renewal_in, "days_since_contact": since_contact}
