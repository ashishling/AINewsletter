#!/usr/bin/env python3
"""
Curator API - REST API for Newsletter Curation Tool.
Provides endpoints for browsing, curating articles, and generating newsletters.
"""
import os
import json
import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify, request, send_from_directory
from urllib.parse import unquote
from datetime import datetime

import config
import db
from newsletter_generator import generate_newsletter


def fetch_url_metadata(url: str) -> dict:
    """Fetch title and description from a URL."""
    try:
        headers = {"User-Agent": config.USER_AGENT}
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        # Get title
        title = ""
        if soup.title:
            title = soup.title.string or ""
        if not title:
            og_title = soup.find("meta", property="og:title")
            if og_title:
                title = og_title.get("content", "")

        # Get description
        description = ""
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc:
            description = meta_desc.get("content", "")
        if not description:
            og_desc = soup.find("meta", property="og:description")
            if og_desc:
                description = og_desc.get("content", "")

        return {
            "success": True,
            "title": title.strip(),
            "summary": description.strip()[:500]
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "title": "",
            "summary": ""
        }

app = Flask(__name__, static_folder="output")


def load_feeds_cache_data() -> dict:
    """Load feeds cache JSON data."""
    try:
        with open(config.FEEDS_CACHE_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_feeds_cache_data(cache_data: dict) -> None:
    """Persist feeds cache JSON data."""
    with open(config.FEEDS_CACHE_FILE, "w") as f:
        json.dump(cache_data, f, indent=2)


@app.route("/")
def index():
    """Serve the curator UI."""
    return send_from_directory("output", "curator.html")


@app.route("/viewer.html")
def viewer():
    """Serve the original viewer."""
    return send_from_directory("output", "viewer.html")


@app.route("/api/weeks", methods=["GET"])
def get_weeks():
    """Get list of available weeks."""
    weeks = db.get_available_weeks()
    current = db.get_current_week()

    # Ensure current week is in list
    if current not in weeks:
        weeks.insert(0, current)

    return jsonify({
        "weeks": weeks,
        "current": current
    })


@app.route("/api/articles", methods=["GET"])
def get_articles():
    """
    Get current (non-archived) articles with optional filters.
    Query params:
      - status: Filter by status ('pending', 'shortlisted', 'rejected', or 'all')
    """
    status = request.args.get("status", "all")

    if status == "all":
        articles = db.get_current_articles()
    else:
        articles = db.get_articles_by_status(status=status, include_archived=False)

    return jsonify({
        "articles": articles,
        "count": len(articles)
    })


@app.route("/api/articles/<article_id>", methods=["GET"])
def get_article(article_id):
    """Get a single article by ID."""
    article = db.get_article_by_id(article_id)
    if article:
        return jsonify(article)
    return jsonify({"error": "Article not found"}), 404


@app.route("/api/articles/<article_id>/curate", methods=["POST"])
def curate_article(article_id):
    """
    Update curation status for an article.
    Body: { "status": "pending|shortlisted|rejected", "notes": "optional notes" }
    """
    data = request.get_json() or {}
    status = data.get("status")
    notes = data.get("notes")

    if status and status not in ("pending", "shortlisted", "rejected"):
        return jsonify({"error": "Invalid status"}), 400

    if status:
        success = db.set_article_status(article_id, status, notes)
    elif notes is not None:
        success = db.update_article_notes(article_id, notes)
    else:
        return jsonify({"error": "No status or notes provided"}), 400

    if success:
        article = db.get_article_by_id(article_id)
        return jsonify({"success": True, "article": article})

    return jsonify({"error": "Article not found"}), 404


@app.route("/api/articles/<article_id>/top-pick", methods=["POST"])
def toggle_top_pick(article_id):
    """
    Toggle top-pick status for a shortlisted article.
    Body: { "top_pick": true|false }
    """
    data = request.get_json() or {}
    top_pick = data.get("top_pick")

    if top_pick is None or not isinstance(top_pick, bool):
        return jsonify({"error": "top_pick boolean is required"}), 400

    success = db.set_top_pick(article_id, top_pick)
    if success:
        article = db.get_article_by_id(article_id)
        return jsonify({"success": True, "article": article})

    return jsonify({"error": "Article not found or not shortlisted"}), 404


@app.route("/api/stats", methods=["GET"])
def get_current_stats():
    """Get statistics for current (non-archived) articles."""
    stats = db.get_current_stats()
    return jsonify(stats)


@app.route("/api/stats/<week>", methods=["GET"])
def get_stats(week):
    """Get statistics for a specific week."""
    stats = db.get_week_stats(week)
    return jsonify(stats)


@app.route("/api/generate-newsletter", methods=["POST"])
def api_generate_newsletter():
    """
    Generate newsletter from shortlisted articles.
    Body: { "week": "2026-W05" }
    """
    data = request.get_json() or {}
    week = data.get("week") or db.get_current_week()

    try:
        result = generate_newsletter(week)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/newsletter/<newsletter_id>", methods=["GET"])
def get_newsletter(newsletter_id):
    """Get generated newsletter by ID."""
    newsletter = db.get_newsletter_by_id(newsletter_id)
    if newsletter:
        # Read the markdown content
        if os.path.exists(newsletter["output_path"]):
            with open(newsletter["output_path"], "r") as f:
                newsletter["content"] = f.read()
        else:
            newsletter["content"] = "*Newsletter file not found. It may have been deleted or overwritten.*"
        return jsonify(newsletter)

    return jsonify({"error": "Newsletter not found"}), 404


@app.route("/api/archive-all", methods=["POST"])
def archive_all():
    """Archive all current (non-archived) articles."""
    count = db.archive_all_current()
    return jsonify({
        "success": True,
        "archived_count": count
    })


@app.route("/api/archive-status", methods=["POST"])
def archive_status():
    """Archive all current articles for a specific status."""
    data = request.get_json() or {}
    status = (data.get("status") or "").strip().lower()
    if status not in ("pending", "shortlisted", "rejected"):
        return jsonify({"error": "Invalid status"}), 400

    count = db.archive_current_by_status(status)
    return jsonify({
        "success": True,
        "status": status,
        "archived_count": count
    })


@app.route("/api/articles/<article_id>/unarchive", methods=["POST"])
def unarchive_article(article_id):
    """Unarchive a single article, bringing it back to current view."""
    success = db.unarchive_article(article_id)
    if success:
        article = db.get_article_by_id(article_id)
        return jsonify({"success": True, "article": article})
    return jsonify({"error": "Article not found"}), 404


@app.route("/api/archived", methods=["GET"])
def get_archived():
    """
    Get archived articles.
    Query params:
      - week: Filter by week (optional)
    """
    week = request.args.get("week")
    articles = db.get_archived_articles(week)
    return jsonify({
        "articles": articles,
        "count": len(articles)
    })


@app.route("/api/archived/weeks", methods=["GET"])
def get_archived_weeks():
    """Get list of weeks with archived articles and their counts."""
    weeks = db.get_archived_weeks()
    return jsonify({"weeks": weeks})


@app.route("/api/newsletters", methods=["GET"])
def get_all_newsletters():
    """Get list of all generated newsletters."""
    newsletters = db.get_all_newsletters()
    return jsonify({"newsletters": newsletters})


@app.route("/api/rss-subscriptions", methods=["GET"])
def get_rss_subscriptions():
    """List all RSS subscriptions from feeds cache."""
    cache_data = load_feeds_cache_data()
    subscriptions = []

    for domain, meta in cache_data.items():
        feed_url = (meta or {}).get("feed_url")
        if not feed_url:
            continue

        subscriptions.append({
            "domain": domain,
            "feed_url": feed_url,
            "discovered_at": (meta or {}).get("discovered_at"),
            "updated_at": (meta or {}).get("updated_at"),
            "article_count": db.get_subscription_article_count(domain, feed_url),
        })

    subscriptions.sort(key=lambda item: item["domain"])
    return jsonify({
        "subscriptions": subscriptions,
        "count": len(subscriptions)
    })


@app.route("/api/rss-subscriptions/<path:domain>", methods=["PUT"])
def update_rss_subscription(domain):
    """Update RSS feed URL for a subscription domain."""
    domain = unquote(domain).strip().lower()
    if not domain:
        return jsonify({"error": "Domain is required"}), 400

    data = request.get_json() or {}
    feed_url = (data.get("feed_url") or "").strip()
    if not feed_url:
        return jsonify({"error": "feed_url is required"}), 400

    if not feed_url.startswith(("http://", "https://")):
        feed_url = "https://" + feed_url

    cache_data = load_feeds_cache_data()
    now = datetime.now().isoformat()
    current = cache_data.get(domain, {})

    current["feed_url"] = feed_url
    current.pop("no_feed", None)
    if not current.get("discovered_at"):
        current["discovered_at"] = now
    current["updated_at"] = now
    cache_data[domain] = current

    save_feeds_cache_data(cache_data)

    return jsonify({
        "success": True,
        "subscription": {
            "domain": domain,
            "feed_url": feed_url,
            "discovered_at": current.get("discovered_at"),
            "updated_at": current.get("updated_at"),
            "article_count": db.get_subscription_article_count(domain, feed_url),
        }
    })


@app.route("/api/rss-subscriptions/<path:domain>", methods=["DELETE"])
def delete_rss_subscription(domain):
    """
    Remove a subscription.
    Optional query param: delete_articles=true to also remove related articles.
    """
    domain = unquote(domain).strip().lower()
    if not domain:
        return jsonify({"error": "Domain is required"}), 400

    delete_articles = request.args.get("delete_articles", "false").lower() in ("1", "true", "yes")

    cache_data = load_feeds_cache_data()
    existing = cache_data.get(domain, {})
    feed_url = (existing or {}).get("feed_url", "")

    removed = domain in cache_data
    if removed:
        del cache_data[domain]
        save_feeds_cache_data(cache_data)

    deleted_articles = 0
    if delete_articles:
        deleted_articles = db.delete_articles_for_subscription(domain, feed_url)

    return jsonify({
        "success": True,
        "removed_subscription": removed,
        "deleted_articles": deleted_articles
    })


@app.route("/api/fetch-url", methods=["POST"])
def fetch_url():
    """
    Fetch metadata from a URL.
    Body: { "url": "https://..." }
    """
    data = request.get_json() or {}
    url = data.get("url", "").strip()

    if not url:
        return jsonify({"error": "URL is required"}), 400

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    result = fetch_url_metadata(url)
    result["url"] = url
    return jsonify(result)


@app.route("/api/articles/manual", methods=["POST"])
def add_manual_article():
    """
    Manually add an article.
    Body: {
        "url": "https://...",
        "title": "Article Title",
        "summary": "Optional summary",
        "topic": "AI Applications",
        "notes": "Your take on this article",
        "auto_shortlist": true
    }
    """
    data = request.get_json() or {}
    url = data.get("url", "").strip()
    title = data.get("title", "").strip()

    if not url:
        return jsonify({"error": "URL is required"}), 400

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    # If no title provided, try to fetch it
    if not title:
        metadata = fetch_url_metadata(url)
        title = metadata.get("title", "")
        if not title:
            return jsonify({"error": "Could not fetch title. Please provide one."}), 400

    summary = data.get("summary", "")
    if not summary:
        metadata = fetch_url_metadata(url)
        summary = metadata.get("summary", "")

    article_id = db.add_manual_article(
        url=url,
        title=title,
        summary=summary,
        topic=data.get("topic", ""),
        notes=data.get("notes", ""),
        auto_shortlist=data.get("auto_shortlist", True)
    )

    article = db.get_article_by_id(article_id)
    return jsonify({
        "success": True,
        "article_id": article_id,
        "article": article
    })


@app.route("/api/curation-patterns", methods=["GET"])
def get_curation_patterns():
    """Get curation patterns and preferences learned from past decisions."""
    examples = db.get_curated_examples(limit_per_status=10)
    stats = db.get_curation_stats()

    return jsonify({
        "examples": examples,
        "stats": stats,
        "total_curated": len(examples["shortlisted"]) + len(examples["rejected"])
    })


@app.route("/api/migrate", methods=["POST"])
def migrate_json():
    """Migrate existing digest_data.json to database."""
    json_path = os.path.join(config.OUTPUT_DIR, "digest_data.json")
    count = db.migrate_from_json(json_path)
    return jsonify({
        "success": True,
        "migrated": count
    })


# Serve static files from output directory
@app.route("/output/<path:filename>")
def serve_output(filename):
    """Serve files from output directory."""
    return send_from_directory("output", filename)


if __name__ == "__main__":
    # Ensure output directories exist
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    os.makedirs(config.NEWSLETTER_OUTPUT_DIR, exist_ok=True)

    print("=" * 60)
    print("Newsletter Curator API")
    print("=" * 60)
    print(f"\nStarting server at http://0.0.0.0:5001")
    print(f"Access locally: http://localhost:5001")
    print(f"Access from network: http://192.168.50.9:5001\n")

    app.run(debug=True, host='0.0.0.0', port=5001)
