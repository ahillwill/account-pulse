# Account Pulse

**An AI agent that checks every customer account each morning and tells your account team which accounts are growing, which need watching, and which are critical, with the evidence and one next action for each.**

Account teams usually learn a customer is in trouble when the renewal is already slipping, and spot expansion after a competitor has. Most customer-health tools only look *inside* the product (logins, usage, tickets). Account Pulse looks *outside*: is the customer hiring or freezing, laying people off, losing executives, raising money, being acquired? Those signals show up weeks or months before they show up in usage or revenue.

🟢 **Healthy** · 🟡 **Watch** · 🔴 **Critical**, updated automatically every day.

## How it works

Every morning at about 7am ET, a GitHub Actions workflow runs the full pipeline and commits the results, so the repo history doubles as a daily log.

| # | Step | What happens |
|---|---|---|
| 1 | Load accounts | `accounts.csv`: company, job board, news query, SEC CIK, CRM fields |
| 2 | Collect | Open job postings (Greenhouse, Lever, Ashby), 14 days of news (GNews API), 30 days of SEC filings (EDGAR) |
| 3 | Compare | Today vs. the last snapshot: roles added, roles closed, % change |
| 4 | Score | Transparent rules produce a 0–100 score and a list of flags |
| 5 | Agent review | A Claude agent investigates each account with tools and makes the final call |
| 6 | Summarize | The agent writes a short morning briefing across all accounts |
| 7 | Save | `data/snapshots/<date>.json` and `data/history.json` |
| 8 | Publish | `docs/index.html`, the live dashboard on GitHub Pages |
| 9 | Alert | An email digest: critical accounts first, only what changed |

### The dashboard (5 pages, rebuilt every run)

| Page | What it shows |
|---|---|
| **Overview** | KPIs, portfolio health chart, grading scale, every account from Critical to Healthy |
| **Accounts** | Filterable table with 1-day and 7-day change, momentum, 14-day trend, renewal, ARR |
| **Account pages** | Interactive score chart (7D/14D/30D/All), the score breakdown point by point, agent reasoning, and every piece of evidence linked to its source |
| **Signals** | All hiring, news, and SEC evidence across accounts, newest first, each with a "Verify" link |
| **Timeline** | Every daily run: status changes, biggest moves, and the raw data file |
| **How it works** | Grading scale, scoring rules, data sources, and the agent |

Hover any chart to see the date, score, status, and what drove it.

### The agent

The agent isn't a single prompt. For each account it gets the rule-based score as a starting point, then decides which tools to call before deciding:

| Tool | Returns |
|---|---|
| `get_hiring_data` | Open roles, change since last run, newest roles |
| `get_news` | Recent headlines with tone tags |
| `get_sec_filings` | Recent 8-K, 10-Q, 10-K filings with plain-English item meanings |
| `get_crm_record` | Renewal date, last contact, contract value, owner |
| `get_score_history` | Recent daily scores and statuses |
| `submit_assessment` | Final status, score, reason, next action, risks, opportunities |

It may override the rules when the evidence supports it, and it must say so. It may only use facts the tools return. If the API is unavailable, the run falls back to rules-only so the daily update never breaks.

### Scoring rules (starting point for the agent)

Each account starts at 70. Examples:

| Signal | Points |
|---|---|
| Serious news (layoffs, breach, acquired by another company) | −30 |
| Open roles down 40%+ since last run | −25 |
| 8-K Item 2.05 (restructuring or layoffs) | −20 |
| Renewal within 60 days and no contact in 30+ days | −10 and −15 |
| 8-K Item 5.02 (executive change) | −10 |
| Open roles up 20%+ | +10 |
| Positive news (funding, expansion, launches) | +5 each, up to +15 |

Total risk is capped at −55 because overlapping signals often describe one event (a layoff shows up in news, filings, and hiring). Below 45 is **Critical**, below 65 is **Watch**, otherwise **Healthy**. All rules live in `pulse/health.py`.

## Quickstart

Requires Python 3.9+. No packages to install.

```bash
# See it work with fictional accounts (no keys needed)
python3 account_pulse.py --demo --open

# Add your keys
cp .env.example .env

# Test every data source for every account
python3 account_pulse.py --check

# Run the real thing
python3 account_pulse.py --open
```

| Flag | What it does |
|---|---|
| `--demo` | Fictional accounts with a two-week score history |
| `--check` | Tests jobs, news, and SEC sources for each account |
| `--no-ai` | Rules only, no Claude calls |
| `--no-email` | Skip sending the digest |
| `--open` | Open the dashboard when done |

## Keys

| Key | Where to get it | Used for |
|---|---|---|
| `ANTHROPIC_API_KEY` | console.anthropic.com | The agent |
| `GNEWS_API_KEY` | gnews.io (free tier) | News |
| `SEC_CONTACT_EMAIL` | Your email | SEC requires a contact in the User-Agent |
| `SMTP_USER`, `SMTP_PASSWORD`, `DIGEST_TO` | Gmail App Password | Email digest |

## Run it automatically every day

1. Push this repo to GitHub.
2. **Settings → Secrets and variables → Actions**: add each key above as a repository secret.
3. **Settings → Pages**: deploy from the `main` branch, `/docs` folder. Optionally add the Pages URL as a repository variable named `DASHBOARD_URL` so the email links to it.
4. **Actions → Daily Account Pulse → Run workflow** to test it once by hand. After that it runs every morning on its own.

## Limitations

- **Coverage:** Job data comes from Greenhouse, Lever, and Ashby, which are common at startups and growth-stage tech companies. Many large enterprises use Workday or their own sites, which aren't supported yet.
- **Sample CRM fields:** In this repo, renewal dates, last contact, and ARR for the listed companies are sample values for demonstration. A real deployment reads them from the customer's CRM.
- **Keyword tagging:** News tone tags are keyword-based; the agent reads the actual headlines and can disagree with them.
- **Outside-in only:** Account Pulse complements, not replaces, product usage and support data.

## Roadmap

- [ ] HubSpot and Salesforce integration for real renewal, contact, and deal data
- [ ] Slack alerts for accounts that turn Critical
- [ ] Champion tracking: alert when a key contact changes jobs
- [ ] Workday and custom careers-page support for enterprise accounts
- [ ] Feedback loop: account managers mark alerts useful or not, and the weights adapt
- [ ] Multi-customer hosted version

---
Built by Austin Hill-Williams · Python standard library · Claude API · GNews · SEC EDGAR · GitHub Actions
