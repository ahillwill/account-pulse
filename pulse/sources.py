"""
Data collectors. Each returns a plain dict and never raises: if a source fails,
the record says so and the rest of the run continues.

  jobs     Greenhouse, Lever, Ashby public job boards (no key)
  news     GNews API (GNEWS_API_KEY)
  filings  SEC EDGAR submissions API (no key, needs SEC_CONTACT_EMAIL for the User-Agent)
"""

import datetime as dt
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "AccountPulse/1.0 (open-source account health agent)"


def http_get_json(url, headers=None, timeout=20):
    h = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def parse_date(value):
    if value in (None, ""):
        return None
    try:
        if isinstance(value, (int, float)):
            return dt.datetime.fromtimestamp(value / 1000, tz=dt.timezone.utc).date()
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except (ValueError, OverflowError, OSError):
        return None


def short_error(e):
    if isinstance(e, urllib.error.HTTPError):
        return f"HTTP {e.code}"
    return str(e)[:120]


# ----------------------------------------------------------------------------
# Jobs
# ----------------------------------------------------------------------------

def _greenhouse(token):
    data = http_get_json(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs")
    return [{
        "id": str(j.get("id")),
        "title": j.get("title", ""),
        "location": (j.get("location") or {}).get("name", ""),
        "url": j.get("absolute_url", ""),
        # first_published is the true post date; updated_at changes on edits, so we don't use it.
        "posted": parse_date(j.get("first_published")),
    } for j in data.get("jobs", [])]


def _lever(token):
    data = http_get_json(f"https://api.lever.co/v0/postings/{token}?mode=json")
    return [{
        "id": str(j.get("id")),
        "title": j.get("text", ""),
        "location": (j.get("categories") or {}).get("location", "") or "",
        "url": j.get("hostedUrl", ""),
        "posted": parse_date(j.get("createdAt")),
    } for j in (data if isinstance(data, list) else [])]


def _ashby(token):
    data = http_get_json(f"https://api.ashbyhq.com/posting-api/job-board/{token}")
    out = []
    for j in data.get("jobs", []):
        loc = j.get("location") or ""
        out.append({
            "id": str(j.get("id") or j.get("jobUrl")),
            "title": j.get("title", ""),
            "location": loc.get("name", "") if isinstance(loc, dict) else loc,
            "url": j.get("jobUrl", ""),
            "posted": parse_date(j.get("publishedAt") or j.get("publishedDate")),
        })
    return out


JOB_BOARDS = {"greenhouse": _greenhouse, "lever": _lever, "ashby": _ashby}


def collect_jobs(acct, today):
    ats, token = acct.get("ats", ""), acct.get("board_token", "")
    if not ats or not token:
        return {"available": False, "error": "no job board configured"}
    if ats not in JOB_BOARDS:
        return {"available": False, "error": f"unknown job board '{ats}'"}
    try:
        jobs = JOB_BOARDS[ats](token)
    except Exception as e:
        return {"available": False, "error": short_error(e)}

    dated = [j for j in jobs if j["posted"]]
    dated.sort(key=lambda j: j["posted"], reverse=True)
    return {
        "available": True,
        "open_roles": len(jobs),
        "role_ids": sorted(j["id"] for j in jobs),
        "has_post_dates": bool(dated),
        "new_7d": sum((today - j["posted"]).days <= 7 for j in dated),
        "new_30d": sum((today - j["posted"]).days <= 30 for j in dated),
        "recent_roles": [{
            "title": j["title"], "location": j["location"], "url": j["url"],
            "posted": j["posted"].isoformat(),
        } for j in dated[:15]] or [{"title": j["title"], "location": j["location"], "url": j["url"],
                                     "posted": None} for j in jobs[:15]],
    }


# ----------------------------------------------------------------------------
# News
# ----------------------------------------------------------------------------

SEVERE = ["layoff", "layoffs", "lays off", "laid off", "job cuts", "cuts jobs", "cut jobs", "bankruptcy",
          "data breach", "breach", "hacked", "fraud", "shuts down", "shutting down", "acquired by"]
NEGATIVE = ["lawsuit", "sued", "outage", "resigns", "steps down", "departs", "investigation", "probe",
            "downgrade", "misses", "slows", "decline", "restructuring", "hiring freeze", "cuts", "loss widens"]
POSITIVE = ["raises", "funding", "series a", "series b", "series c", "series d", "acquires", "expands",
            "expansion", "launches", "partnership", "partners with", "record", "beats", "hires", "appoints",
            "opens", "growth", "surges"]


def classify_headline(text):
    t = text.lower()
    if any(k in t for k in SEVERE):
        return "severe"
    if any(k in t for k in NEGATIVE):
        return "negative"
    if any(k in t for k in POSITIVE):
        return "positive"
    return "neutral"


NEWS_GAP_SECONDS = 1.5
_last_news_call = 0.0


def collect_news(acct, today, days=14):
    key = os.environ.get("GNEWS_API_KEY", "").strip()
    if not key:
        return {"available": False, "error": "GNEWS_API_KEY not set"}
    query = acct.get("news_query") or f'"{acct["company"]}"'
    since = (today - dt.timedelta(days=days)).isoformat() + "T00:00:00Z"
    params = urllib.parse.urlencode({"q": query, "lang": "en", "max": 10, "from": since,
                                     "sortby": "publishedAt", "apikey": key})
    # The free GNews plan allows about one request per second, so space calls out and retry once if limited.
    global _last_news_call
    data, error = None, None
    for attempt in range(3):
        wait = NEWS_GAP_SECONDS - (time.monotonic() - _last_news_call)
        if wait > 0:
            time.sleep(wait)
        _last_news_call = time.monotonic()
        try:
            data = http_get_json(f"https://gnews.io/api/v4/search?{params}")
            break
        except urllib.error.HTTPError as e:
            error = short_error(e)
            if e.code != 429:
                break
            time.sleep(3 * (attempt + 1))
        except Exception as e:
            error = short_error(e)
            break
    if data is None:
        return {"available": False, "error": error}

    articles = []
    for a in data.get("articles", []):
        text = f"{a.get('title', '')} {a.get('description', '')}"
        articles.append({
            "title": a.get("title", ""),
            "source": (a.get("source") or {}).get("name", ""),
            "url": a.get("url", ""),
            "published": (parse_date(a.get("publishedAt")) or today).isoformat(),
            "tone": classify_headline(text),
        })
    return {"available": True, "articles": articles}


# ----------------------------------------------------------------------------
# SEC filings
# ----------------------------------------------------------------------------

ITEM_LABELS = {
    "1.01": "New material agreement", "1.02": "Material agreement ended", "1.03": "Bankruptcy",
    "2.01": "Acquisition or sale of assets", "2.02": "Earnings results", "2.05": "Restructuring or layoffs",
    "2.06": "Asset impairment", "5.02": "Executive or director change", "5.07": "Shareholder vote",
    "7.01": "Regulation FD disclosure", "8.01": "Other material event",
}


def collect_filings(acct, today, days=30):
    cik = "".join(ch for ch in str(acct.get("cik", "")) if ch.isdigit())
    if not cik:
        return {"available": False, "error": "not a public company (no CIK)"}
    contact = os.environ.get("SEC_CONTACT_EMAIL", "").strip()
    if not contact:
        return {"available": False, "error": "SEC_CONTACT_EMAIL not set"}
    try:
        data = http_get_json(f"https://data.sec.gov/submissions/CIK{cik.zfill(10)}.json",
                             headers={"User-Agent": f"AccountPulse {contact}"})
    except Exception as e:
        return {"available": False, "error": short_error(e)}

    r = (data.get("filings") or {}).get("recent") or {}
    rows = zip(r.get("form", []), r.get("filingDate", []), r.get("items", []),
               r.get("accessionNumber", []), r.get("primaryDocument", []))
    filings = []
    for form, date_s, items, acc, doc in rows:
        d = parse_date(date_s)
        if form not in ("8-K", "10-Q", "10-K") or not d or (today - d).days > days:
            continue
        codes = [c.strip() for c in (items or "").split(",") if c.strip()]
        filings.append({
            "form": form, "date": d.isoformat(), "items": codes,
            "labels": [ITEM_LABELS.get(c, f"Item {c}") for c in codes] or [form],
            "url": f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/{doc}",
        })
    return {"available": True, "filings": filings[:10]}


def collect_account(acct, today):
    return {
        "company": acct["company"],
        "jobs": collect_jobs(acct, today),
        "news": collect_news(acct, today),
        "filings": collect_filings(acct, today),
        "crm": {k: acct.get(k, "") for k in ("renewal_date", "last_contact", "arr", "owner")},
        "meta": {k: acct.get(k, "") for k in ("domain", "ats", "board_token", "cik", "news_query")},
    }
