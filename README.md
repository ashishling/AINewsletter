# AI Newsletter

Curated AI newsletter pipeline: RSS feed sources → article links → DB → curation.

## Core Workflow

1. **RSS feed sources** — Domains are extracted from `browser_crawl_results.json` (bensbites.com crawl with outbound links).
2. **Feed discovery** — RSS feeds are discovered per domain and cached in `feeds_cache.json`.
3. **Article links** — Feeds are parsed; articles are stored in the DB (no scoring).
4. **Curation** — Articles are available in the DB for newsletter curation via the dashboard.

## Setup

```bash
pip install -r requirements.txt
```

## Usage

```bash
# Build curator UI assets (writes to output/assets)
npm install
npm run build:curator-ui

# Run the RSS sync (discover feeds, parse, store in DB)
python rss_feed_scorer.py

# Cron mode: fetch only articles since last run (for daily 6am cron)
python rss_feed_scorer.py --cron

# Skip feed discovery, use cached feeds only
python rss_feed_scorer.py --skip-discovery

# Start the curation dashboard
python curator_api.py
# Open http://localhost:5001
```

## Cron (daily morning sync)

Add to crontab to run every morning at 6am:

```bash
0 6 * * * cd /path/to/AINewsletter && python rss_feed_scorer.py --cron
```

First run fetches the last 1 day of articles. Subsequent runs fetch only since the last run.

## Key Files

| File | Purpose |
|------|---------|
| `browser_crawl_results.json` | Input: crawled bensbites.com posts + outbound links (domains become RSS sources) |
| `feeds_cache.json` | Cached RSS feed URLs per domain |
| `rss_feed_scorer.py` | Main pipeline: load domains → discover feeds → parse → DB |
| `config.py` | Configuration (excluded domains, CRON_FIRST_RUN_DAYS, etc.) |
