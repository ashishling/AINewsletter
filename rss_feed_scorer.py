#!/usr/bin/env python3
"""
RSS Feed Sync - Cron-friendly newsletter article pipeline.

Discovers RSS feeds from browser_crawl_results.json, parses them, and stores
articles in the database for curation. Designed to run daily (e.g. 6am cron)
fetching articles since the last run. Duplicates are avoided by URL-based dedup.
"""
import argparse
import json
import sys
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urljoin, urlparse

import feedparser
import requests
from bs4 import BeautifulSoup

import config
import db


def load_crawl_results() -> dict:
    """Load the browser crawl results JSON file."""
    try:
        with open(config.CRAWL_RESULTS_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Error: {config.CRAWL_RESULTS_FILE} not found")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error parsing {config.CRAWL_RESULTS_FILE}: {e}")
        sys.exit(1)


def extract_domains_from_crawl(crawl_data: dict) -> set[str]:
    """Extract unique domains from crawl results."""
    domains = set()

    for post in crawl_data.get("posts", []):
        # Extract domain from post URL
        post_url = post.get("url", "")
        if post_url:
            parsed = urlparse(post_url)
            if parsed.netloc:
                domains.add(parsed.netloc)

        # Extract domains from outbound links
        for link in post.get("outbound_links", []):
            parsed = urlparse(link)
            if parsed.netloc:
                domains.add(parsed.netloc)

    return domains


def load_feeds_cache() -> dict:
    """Load the feeds cache file."""
    try:
        with open(config.FEEDS_CACHE_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_feeds_cache(cache: dict) -> None:
    """Save the feeds cache file."""
    with open(config.FEEDS_CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)


def discover_rss_from_html(url: str) -> Optional[str]:
    """
    Try to discover RSS feed URL from HTML page by looking for
    <link rel="alternate" type="application/rss+xml"> or similar.
    """
    try:
        headers = {"User-Agent": config.USER_AGENT}
        response = requests.get(url, headers=headers, timeout=config.REQUEST_TIMEOUT)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        # Look for RSS/Atom link tags
        for link_type in ["application/rss+xml", "application/atom+xml", "application/xml"]:
            link = soup.find("link", {"rel": "alternate", "type": link_type})
            if link and link.get("href"):
                feed_url = link["href"]
                # Handle relative URLs
                if not feed_url.startswith("http"):
                    feed_url = urljoin(url, feed_url)
                return feed_url

        return None
    except Exception:
        return None


def try_rss_patterns(domain: str) -> Optional[str]:
    """Try common RSS URL patterns for a domain."""
    base_urls = [f"https://{domain}", f"https://www.{domain}"]

    for base_url in base_urls:
        for pattern in config.RSS_PATTERNS:
            feed_url = base_url + pattern
            try:
                headers = {"User-Agent": config.USER_AGENT}
                response = requests.get(
                    feed_url,
                    headers=headers,
                    timeout=config.REQUEST_TIMEOUT,
                    allow_redirects=True
                )

                if response.status_code == 200:
                    # Verify it's actually a feed
                    content_type = response.headers.get("content-type", "").lower()
                    content_start = response.text[:500].lower()

                    if any(x in content_type for x in ["xml", "rss", "atom"]) or \
                       any(x in content_start for x in ["<rss", "<feed", "<atom", "<?xml"]):
                        return feed_url
            except Exception:
                continue

    return None


def discover_rss_feed(domain: str, cache: dict) -> Optional[str]:
    """
    Discover RSS feed URL for a domain.
    Uses cache if available, otherwise tries discovery methods.
    """
    # Check cache first
    if domain in cache:
        cached = cache[domain]
        if cached.get("feed_url"):
            return cached["feed_url"]
        elif cached.get("no_feed"):
            return None

    print(f"  Discovering feed for {domain}...")

    # Try HTML discovery first (more reliable)
    base_url = f"https://{domain}"
    feed_url = discover_rss_from_html(base_url)

    if not feed_url:
        # Try with www prefix
        feed_url = discover_rss_from_html(f"https://www.{domain}")

    if not feed_url:
        # Try common patterns
        feed_url = try_rss_patterns(domain)

    # Update cache
    if feed_url:
        cache[domain] = {"feed_url": feed_url, "discovered_at": datetime.now().isoformat()}
    else:
        cache[domain] = {"no_feed": True, "checked_at": datetime.now().isoformat()}

    return feed_url


def parse_feed(feed_url: str, cutoff_date: Optional[datetime] = None) -> list[dict]:
    """Parse an RSS feed and return items published on or after cutoff_date."""
    try:
        # Use requests with timeout so a single slow feed cannot hang manual sync.
        headers = {"User-Agent": config.USER_AGENT}
        response = requests.get(feed_url, headers=headers, timeout=config.REQUEST_TIMEOUT)
        response.raise_for_status()
        feed = feedparser.parse(response.content)

        if feed.bozo and not feed.entries:
            return []

        if cutoff_date is None:
            cutoff_date = datetime.now() - timedelta(days=config.DAYS_LOOKBACK)

        items = []

        for entry in feed.entries[:config.MAX_FEED_ITEMS]:
            # Parse publication date
            pub_date = None
            for date_field in ["published_parsed", "updated_parsed", "created_parsed"]:
                if hasattr(entry, date_field) and getattr(entry, date_field):
                    try:
                        pub_date = datetime(*getattr(entry, date_field)[:6])
                        break
                    except Exception:
                        continue

            # Skip old items (include items with no date to avoid missing content)
            if pub_date is not None and pub_date < cutoff_date:
                continue

            # Extract summary/description
            summary = ""
            if hasattr(entry, "summary"):
                summary = entry.summary
            elif hasattr(entry, "description"):
                summary = entry.description
            elif hasattr(entry, "content") and entry.content:
                summary = entry.content[0].get("value", "")

            # Clean HTML from summary
            if summary:
                soup = BeautifulSoup(summary, "html.parser")
                summary = soup.get_text(separator=" ", strip=True)[:500]

            items.append({
                "title": getattr(entry, "title", "Untitled"),
                "url": getattr(entry, "link", ""),
                "summary": summary,
                "published": pub_date.isoformat() if pub_date else None,
                "source": urlparse(feed_url).netloc,
            })

        return items
    except Exception as e:
        print(f"  Error parsing feed {feed_url}: {e}")
        return []


def run_sync(cron_mode: bool = False, skip_discovery: bool = False,
             limit_domains: int = 0, verbose: bool = True) -> int:
    """
    Run the RSS sync: load feeds, parse, store in DB.
    Returns the number of articles stored.
    """
    week = db.get_current_week()

    # Determine cutoff date
    if cron_mode:
        last_run = db.get_last_cron_run()
        if last_run:
            cutoff_date = last_run
            if verbose:
                print(f"Fetching articles since last run: {last_run.isoformat()}")
        else:
            # First run: use last N days
            cutoff_date = datetime.now() - timedelta(days=config.CRON_FIRST_RUN_DAYS)
            if verbose:
                print(f"First run: fetching articles from last {config.CRON_FIRST_RUN_DAYS} day(s)")
    else:
        cutoff_date = datetime.now() - timedelta(days=config.DAYS_LOOKBACK)
        if verbose:
            print(f"Full sync: fetching articles from last {config.DAYS_LOOKBACK} days")

    if verbose:
        print("=" * 60)
        print("RSS Feed Sync - AI Newsletter")
        print(f"Week: {week} | Cutoff: {cutoff_date.date()}")
        print("=" * 60)

    # Load crawl results
    if verbose:
        print("\n[1/4] Loading crawl results...")
    crawl_data = load_crawl_results()
    if verbose:
        print(f"  Loaded {len(crawl_data.get('posts', []))} posts")

    # Extract domains
    if verbose:
        print("\n[2/4] Extracting domains...")
    domains = extract_domains_from_crawl(crawl_data)

    # Filter out common non-blog domains and excluded news sources
    skip_domains = {
        "github.com", "x.com", "twitter.com", "youtube.com",
        "apps.apple.com", "play.google.com", "linkedin.com",
        "facebook.com", "instagram.com", "tiktok.com",
        *config.EXCLUDED_RSS_DOMAINS,
    }
    domains = {d for d in domains if not any(skip in d for skip in skip_domains)}
    if verbose:
        print(f"  Found {len(domains)} domains after filtering")

    if limit_domains > 0:
        domains = set(list(domains)[:limit_domains])
        if verbose:
            print(f"  Limited to {len(domains)} domains")

    # Load/update feeds cache
    if verbose:
        print("\n[3/4] Discovering RSS feeds...")
    cache = load_feeds_cache()
    feed_urls = {}

    for domain in sorted(domains):
        if skip_discovery and domain not in cache:
            continue

        feed_url = discover_rss_feed(domain, cache)
        if feed_url:
            feed_urls[domain] = feed_url
            if verbose:
                print(f"  + {domain}: {feed_url}")

    save_feeds_cache(cache)
    if verbose:
        print(f"  Found {len(feed_urls)} feeds")

    if not feed_urls:
        if verbose:
            print("\nNo RSS feeds found. Exiting.")
        return 0

    # Parse feeds and collect items
    if verbose:
        print("\n[4/4] Parsing feeds...")
    all_items = []

    for domain, feed_url in feed_urls.items():
        items = parse_feed(feed_url, cutoff_date=cutoff_date)
        if verbose:
            print(f"  {domain}: {len(items)} items")
        all_items.extend(items)

    # Deduplicate by URL (same article may appear in multiple feeds)
    seen_urls = set()
    unique_items = []
    for item in all_items:
        url = item.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique_items.append(item)

    if verbose:
        print(f"\n  Total items to store: {len(unique_items)} (after dedup)")

    if not unique_items:
        if verbose:
            print("  No new articles to store.")
        if cron_mode:
            db.set_last_cron_run()
        return 0

    # Store in database
    count = db.upsert_articles(unique_items, week)

    if cron_mode:
        db.set_last_cron_run()

    if verbose:
        print(f"\n  Stored {count} articles in database")
        stats = db.get_current_stats()
        print(f"\nDone! Current dashboard: {stats['total']} articles, "
              f"{stats['pending']} pending curation")
        print(f"\n  Run: python curator_api.py && open http://localhost:5001")
        print("=" * 60)

    return count


def main():
    parser = argparse.ArgumentParser(
        description="Sync RSS feeds to newsletter database. Run daily via cron."
    )
    parser.add_argument(
        "--cron",
        action="store_true",
        help="Cron mode: fetch only since last run, minimal output",
    )
    parser.add_argument(
        "--skip-discovery",
        action="store_true",
        help="Skip feed discovery, use only cached feeds",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limit number of domains to process (0 = no limit)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Minimal output (for cron)",
    )
    args = parser.parse_args()

    verbose = not (args.cron or args.quiet)
    run_sync(
        cron_mode=args.cron,
        skip_discovery=args.skip_discovery,
        limit_domains=args.limit,
        verbose=verbose,
    )


if __name__ == "__main__":
    main()
