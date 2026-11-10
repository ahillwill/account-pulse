"""
The Account Pulse agent.

For each account, Claude gets the rule-based score as a starting point, then investigates
with tools (hiring, news, filings, CRM, score history) before submitting a structured
assessment: Healthy / Watch / Critical, a plain-English reason, and one next action.
It may override the rules, but must explain why, and may only use facts the tools return.

If no ANTHROPIC_API_KEY is set (or the API fails), a rules-only assessment is used so the
daily run never breaks.
"""

import json
import os
import urllib.error
import urllib.request

API_URL = "https://api.anthropic.com/v1/messages"
MAX_TURNS = 8

SYSTEM = """You are Account Pulse, an account health analyst for a B2B account management team.
Your job: decide whether each customer account is Healthy, Watch, or Critical today, explain why in
plain English, and recommend the single most useful next action for the account owner.

How to work:
- Start from the rule-based score, then investigate with the tools before deciding.
- Use ONLY facts returned by the tools. Never invent people, numbers, or events.
- Hiring growth, funding, and expansion news are opportunities. Layoffs, hiring freezes, executive
  departures, restructuring, a close renewal with little contact, and acquisitions BY another
  company are risks.
- Weigh how recent and how serious each signal is. One noisy headline should not outweigh clear data.
- You may override the rule-based status if the evidence supports it; say so in your reason.
- Keep it short and specific. The reader is a busy account manager reading on a phone.
When done, call submit_assessment exactly once."""

TOOLS = [
    {"name": "get_hiring_data",
     "description": "Open roles today, change vs. the last run, new roles in the last 7/30 days, and the most recent role titles.",
     "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "get_news",
     "description": "News headlines about the account from the last 14 days, each tagged severe/negative/positive/neutral by keyword rules (tags can be wrong; read the headline).",
     "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "get_sec_filings",
     "description": "SEC filings from the last 30 days (public companies only), with 8-K item meanings.",
     "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "get_crm_record",
     "description": "Relationship data: renewal date, days until renewal, last contact, days since contact, annual contract value, owner.",
     "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "get_score_history",
     "description": "This account's health score and status from recent daily runs, oldest first.",
     "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "submit_assessment",
     "description": "Submit the final assessment for this account.",
     "input_schema": {
         "type": "object",
         "properties": {
             "status": {"type": "string", "enum": ["Healthy", "Watch", "Critical"]},
             "health_score": {"type": "integer", "minimum": 0, "maximum": 100},
             "headline": {"type": "string", "description": "Under 12 words. What's happening."},
             "reason": {"type": "string", "description": "2 sentences max, citing the specific evidence."},
             "next_action": {"type": "string", "description": "One concrete action for the account owner this week."},
             "risks": {"type": "array", "items": {"type": "string"}},
             "opportunities": {"type": "array", "items": {"type": "string"}},
             "overrode_rules": {"type": "boolean"},
         },
         "required": ["status", "health_score", "headline", "reason", "next_action", "overrode_rules"],
     }},
]


def _tool_result(name, record, rules, history):
    jobs = dict(record["jobs"])
    jobs.pop("role_ids", None)
    if name == "get_hiring_data":
        return jobs
    if name == "get_news":
        return record["news"]
    if name == "get_sec_filings":
        return record["filings"]
    if name == "get_crm_record":
        return {**record["crm"], "renewal_in_days": rules["renewal_in_days"],
                "days_since_contact": rules["days_since_contact"]}
    if name == "get_score_history":
        return history or {"note": "No history yet. This is the first run."}
    return {"error": f"unknown tool {name}"}


def _call(messages, api_key, model, tools=None, system=SYSTEM, max_tokens=1200):
    body = {"model": model, "max_tokens": max_tokens, "system": system, "messages": messages}
    if tools:
        body["tools"] = tools
    req = urllib.request.Request(API_URL, data=json.dumps(body).encode("utf-8"), method="POST", headers={
        "x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as resp:
        return json.loads(resp.read().decode("utf-8"))


def assess_with_agent(record, rules, history, api_key, model):
    flags = "\n".join(f"- {f['text']} ({f['points']:+d})" for f in rules["flags"]) or "- No rule flags"
    messages = [{"role": "user", "content":
                 f"Account: {record['company']}\nRule-based score: {rules['score']} ({rules['status']})\n"
                 f"Rule flags:\n{flags}\n\nInvestigate with the tools, then submit your assessment."}]
    trace = []
    for _ in range(MAX_TURNS):
        resp = _call(messages, api_key, model, tools=TOOLS)
        messages.append({"role": "assistant", "content": resp["content"]})
        uses = [b for b in resp["content"] if b.get("type") == "tool_use"]
        if not uses:
            messages.append({"role": "user", "content": "Please call submit_assessment now."})
            continue
        results = []
        for use in uses:
            trace.append(use["name"])
            if use["name"] == "submit_assessment":
                out = dict(use["input"])
                out.setdefault("risks", [])
                out.setdefault("opportunities", [])
                out["source"] = "agent"
                out["tools_used"] = [t for t in trace if t != "submit_assessment"]
                return out
            results.append({"type": "tool_result", "tool_use_id": use["id"],
                            "content": json.dumps(_tool_result(use["name"], record, rules, history), default=str)})
        messages.append({"role": "user", "content": results})
    raise RuntimeError("agent did not submit an assessment")


def assess_with_rules(record, rules):
    risks = [f["text"] for f in rules["flags"] if f["kind"] == "risk"]
    opps = [f["text"] for f in rules["flags"] if f["kind"] == "opportunity"]
    status = rules["status"]
    if status == "Critical":
        action = "Contact your main stakeholder this week to confirm priorities and the renewal."
    elif status == "Watch":
        action = "Schedule a check-in and confirm nothing has changed on their side."
    elif opps:
        action = "Use the growth signals to propose an expansion conversation."
    else:
        action = "No action needed; keep the normal cadence."
    top = (risks or opps or ["No notable changes" if rules.get("sources_ok") else
                             "No outside data today; run --check to fix sources"])[0]
    return {
        "status": status, "health_score": rules["score"], "headline": top[:80],
        "reason": ("Also: " + "; ".join((risks + opps)[1:4]) + ".") if len(risks + opps) > 1
                  else "No other signals in today's data.",
        "next_action": action, "risks": risks, "opportunities": opps,
        "overrode_rules": False, "source": "rules", "tools_used": [],
    }


def assess(record, rules, history, use_ai=True):
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    model = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5")
    if use_ai and api_key:
        try:
            return assess_with_agent(record, rules, history, api_key, model)
        except urllib.error.HTTPError as e:
            print(f"    agent error (HTTP {e.code}): {e.read().decode('utf-8', 'ignore')[:160]}")
        except Exception as e:
            print(f"    agent error: {e}")
    return assess_with_rules(record, rules)


def portfolio_summary(results, use_ai=True):
    """One short paragraph across all accounts, written by Claude when available."""
    counts = {s: sum(r["assessment"]["status"] == s for r in results) for s in ("Critical", "Watch", "Healthy")}
    fallback = (f"{counts['Critical']} critical, {counts['Watch']} on watch, {counts['Healthy']} healthy. "
                + ("Start with " + ", ".join(r["company"] for r in results
                                             if r["assessment"]["status"] == "Critical")[:200] + "."
                   if counts["Critical"] else "No accounts need urgent attention today."))
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not (use_ai and api_key):
        return fallback
    lines = "\n".join(f"- {r['company']}: {r['assessment']['status']} ({r['assessment']['health_score']}). "
                      f"{r['assessment']['headline']}. Action: {r['assessment']['next_action']}" for r in results)
    try:
        resp = _call([{"role": "user", "content":
                       f"Today's account assessments:\n{lines}\n\nWrite a 2-3 sentence morning summary for the "
                       f"account manager: overall picture, then which accounts to focus on first and why. "
                       f"Plain text only, no lists, no greeting."}],
                     api_key, os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5"), max_tokens=300,
                     system="You are Account Pulse, a concise account health analyst.")
        text = "".join(b.get("text", "") for b in resp["content"] if b.get("type") == "text").strip()
        return text or fallback
    except Exception as e:
        print(f"    summary error: {e}")
        return fallback
