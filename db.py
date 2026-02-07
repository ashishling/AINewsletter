"""
Database layer for the Newsletter Curation Tool.
Manages SQLite storage for articles, curation state, and newsletters.
"""
import hashlib
import json
import sqlite3
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

import config


def get_connection() -> sqlite3.Connection:
    """Get a database connection with row factory."""
    conn = sqlite3.connect(config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create tables if they don't exist."""
    conn = get_connection()
    cursor = conn.cursor()

    # Articles table (from RSS ingestion)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS articles (
            id TEXT PRIMARY KEY,
            url TEXT UNIQUE,
            title TEXT,
            summary TEXT,
            source TEXT,
            published TEXT,
            topic TEXT,
            fetched_at TEXT,
            week TEXT
        )
    """)

    # Curation state (user actions)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS curation (
            article_id TEXT PRIMARY KEY,
            status TEXT DEFAULT 'pending',
            user_notes TEXT,
            curated_at TEXT,
            archived INTEGER DEFAULT 0,
            archived_at TEXT,
            top_pick INTEGER DEFAULT 0,
            FOREIGN KEY (article_id) REFERENCES articles(id)
        )
    """)

    # Migration: Add archived columns if they don't exist
    cursor.execute("PRAGMA table_info(curation)")
    columns = [col[1] for col in cursor.fetchall()]
    if "archived" not in columns:
        cursor.execute("ALTER TABLE curation ADD COLUMN archived INTEGER DEFAULT 0")
    if "archived_at" not in columns:
        cursor.execute("ALTER TABLE curation ADD COLUMN archived_at TEXT")
    if "top_pick" not in columns:
        cursor.execute("ALTER TABLE curation ADD COLUMN top_pick INTEGER DEFAULT 0")

    # Newsletters (generated outputs)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS newsletters (
            id TEXT PRIMARY KEY,
            week TEXT,
            generated_at TEXT,
            article_ids TEXT,
            output_path TEXT
        )
    """)

    # Cron state (for incremental RSS sync)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cron_state (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TEXT
        )
    """)

    # Migration: Drop score/reason columns if they exist
    cursor.execute("PRAGMA table_info(articles)")
    article_columns = [col[1] for col in cursor.fetchall()]
    if "score" in article_columns or "reason" in article_columns:
        cursor.execute("ALTER TABLE articles RENAME TO articles_old")
        cursor.execute("""
            CREATE TABLE articles (
                id TEXT PRIMARY KEY,
                url TEXT UNIQUE,
                title TEXT,
                summary TEXT,
                source TEXT,
                published TEXT,
                topic TEXT,
                fetched_at TEXT,
                week TEXT
            )
        """)
        cursor.execute("""
            INSERT INTO articles (id, url, title, summary, source, published, topic, fetched_at, week)
            SELECT id, url, title, summary, source, published, topic, fetched_at, week
            FROM articles_old
        """)
        cursor.execute("DROP TABLE articles_old")

    # Create indexes for common queries
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_articles_week ON articles(week)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_curation_status ON curation(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_articles_published ON articles(published)")

    conn.commit()
    conn.close()


def generate_article_id(url: str) -> str:
    """Generate a unique ID for an article based on its URL."""
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def _normalize_host(value: str) -> str:
    """Normalize a hostname/domain-like string for matching."""
    text = (value or "").strip().lower()
    if not text:
        return ""

    if text.startswith(("http://", "https://")):
        host = urlparse(text).netloc.lower()
    else:
        host = text.split("/")[0].strip().lower()

    if host.startswith("www."):
        host = host[4:]
    return host


def _subscription_match_hosts(domain: str, feed_url: str) -> set[str]:
    """Build normalized host candidates for a subscription."""
    hosts = set()
    for candidate in (domain, feed_url):
        host = _normalize_host(candidate)
        if host:
            hosts.add(host)
    return hosts


def _get_matching_article_ids_for_subscription(domain: str, feed_url: str) -> list[str]:
    """
    Find article IDs associated with a subscription by matching normalized hosts
    against both article source host and article URL host.
    """
    hosts = _subscription_match_hosts(domain, feed_url)
    if not hosts:
        return []

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, url, source FROM articles")
    rows = cursor.fetchall()
    conn.close()

    matched_ids = []
    for row in rows:
        source_host = _normalize_host(row["source"] or "")
        url_host = _normalize_host(row["url"] or "")

        if source_host in hosts or url_host in hosts:
            matched_ids.append(row["id"])

    return matched_ids


def get_current_week() -> str:
    """Get the current week in ISO format (e.g., '2026-W05')."""
    now = datetime.now()
    return now.strftime("%G-W%V")


def get_last_cron_run() -> Optional[datetime]:
    """Get the timestamp of the last successful cron run."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT value FROM cron_state WHERE key = 'last_run'"
    )
    row = cursor.fetchone()
    conn.close()
    if row and row["value"]:
        try:
            return datetime.fromisoformat(row["value"])
        except ValueError:
            return None
    return None


def set_last_cron_run() -> None:
    """Record the current time as the last successful cron run."""
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    cursor.execute("""
        INSERT INTO cron_state (key, value, updated_at)
        VALUES ('last_run', ?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
    """, (now, now))
    conn.commit()
    conn.close()


def add_manual_article(url: str, title: str, summary: str, topic: str = "",
                       notes: str = "", week: Optional[str] = None,
                       auto_shortlist: bool = True) -> str:
    """
    Add a manually submitted article directly to the database.
    Returns the article ID.
    """
    if week is None:
        week = get_current_week()

    source = urlparse(url).netloc

    article_id = generate_article_id(url)
    fetched_at = datetime.now().isoformat()

    conn = get_connection()
    cursor = conn.cursor()

    # Insert article
    cursor.execute("""
        INSERT INTO articles (id, url, title, summary, source, published, topic, fetched_at, week)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            title = excluded.title,
            summary = excluded.summary,
            topic = excluded.topic,
            fetched_at = excluded.fetched_at
    """, (
        article_id,
        url,
        title,
        summary,
        source,
        datetime.now().isoformat(),
        topic,
        fetched_at,
        week
    ))

    # Set curation status
    status = "shortlisted" if auto_shortlist else "pending"
    cursor.execute("""
        INSERT INTO curation (article_id, status, user_notes, curated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(article_id) DO UPDATE SET
            status = excluded.status,
            user_notes = excluded.user_notes,
            curated_at = excluded.curated_at
    """, (article_id, status, notes, fetched_at))

    conn.commit()
    conn.close()

    return article_id


def upsert_articles(items: list[dict], week: Optional[str] = None) -> int:
    """
    Insert or update articles.
    Returns the number of articles inserted/updated.
    """
    if week is None:
        week = get_current_week()

    conn = get_connection()
    cursor = conn.cursor()
    fetched_at = datetime.now().isoformat()
    count = 0

    for item in items:
        article_id = generate_article_id(item["url"])
        topic = item.get("topic", "")

        cursor.execute("""
            INSERT INTO articles (id, url, title, summary, source, published, topic, fetched_at, week)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title = excluded.title,
                summary = excluded.summary,
                topic = excluded.topic,
                fetched_at = excluded.fetched_at
        """, (
            article_id,
            item.get("url", ""),
            item.get("title", ""),
            item.get("summary", ""),
            item.get("source", ""),
            item.get("published", ""),
            topic,
            fetched_at,
            week
        ))

        # Initialize curation state if not exists
        cursor.execute("""
            INSERT OR IGNORE INTO curation (article_id, status, curated_at)
            VALUES (?, 'pending', ?)
        """, (article_id, fetched_at))

        count += 1

    conn.commit()
    conn.close()
    return count


def get_articles_for_week(week: str, include_archived: bool = False) -> list[dict]:
    """Get all articles for a specific week with their curation status."""
    conn = get_connection()
    cursor = conn.cursor()

    if include_archived:
        cursor.execute("""
            SELECT a.*, c.status, c.user_notes, c.curated_at, c.archived, c.archived_at, c.top_pick
            FROM articles a
            LEFT JOIN curation c ON a.id = c.article_id
            WHERE a.week = ?
            ORDER BY c.top_pick DESC, COALESCE(a.published, a.fetched_at) DESC
        """, (week,))
    else:
        cursor.execute("""
            SELECT a.*, c.status, c.user_notes, c.curated_at, c.archived, c.archived_at, c.top_pick
            FROM articles a
            LEFT JOIN curation c ON a.id = c.article_id
            WHERE a.week = ? AND (c.archived = 0 OR c.archived IS NULL)
            ORDER BY c.top_pick DESC, COALESCE(a.published, a.fetched_at) DESC
        """, (week,))

    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]


def get_current_articles() -> list[dict]:
    """Get all non-archived articles (the 'current' view)."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT a.*, c.status, c.user_notes, c.curated_at, c.archived, c.archived_at, c.top_pick
        FROM articles a
        LEFT JOIN curation c ON a.id = c.article_id
        WHERE c.archived = 0 OR c.archived IS NULL
        ORDER BY c.top_pick DESC, COALESCE(a.published, a.fetched_at) DESC
    """)

    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]


def get_subscription_article_count(domain: str, feed_url: str) -> int:
    """Count articles associated with a subscription."""
    return len(_get_matching_article_ids_for_subscription(domain, feed_url))


def delete_articles_for_subscription(domain: str, feed_url: str) -> int:
    """
    Delete all articles and curation rows associated with a subscription.
    Returns the number of deleted articles.
    """
    article_ids = _get_matching_article_ids_for_subscription(domain, feed_url)
    if not article_ids:
        return 0

    conn = get_connection()
    cursor = conn.cursor()

    placeholders = ",".join("?" for _ in article_ids)
    cursor.execute(f"DELETE FROM curation WHERE article_id IN ({placeholders})", article_ids)
    cursor.execute(f"DELETE FROM articles WHERE id IN ({placeholders})", article_ids)

    deleted_count = cursor.rowcount
    conn.commit()
    conn.close()

    return deleted_count


def get_archived_articles(week: Optional[str] = None) -> list[dict]:
    """Get archived articles, optionally filtered by week."""
    conn = get_connection()
    cursor = conn.cursor()

    if week:
        cursor.execute("""
            SELECT a.*, c.status, c.user_notes, c.curated_at, c.archived, c.archived_at, c.top_pick
            FROM articles a
            JOIN curation c ON a.id = c.article_id
            WHERE c.archived = 1 AND a.week = ?
            ORDER BY c.archived_at DESC, COALESCE(a.published, a.fetched_at) DESC
        """, (week,))
    else:
        cursor.execute("""
            SELECT a.*, c.status, c.user_notes, c.curated_at, c.archived, c.archived_at, c.top_pick
            FROM articles a
            JOIN curation c ON a.id = c.article_id
            WHERE c.archived = 1
            ORDER BY c.archived_at DESC, COALESCE(a.published, a.fetched_at) DESC
        """)

    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]


def archive_all_current() -> int:
    """Archive all non-archived articles. Returns count of archived articles."""
    conn = get_connection()
    cursor = conn.cursor()
    archived_at = datetime.now().isoformat()

    cursor.execute("""
        UPDATE curation
        SET archived = 1, archived_at = ?
        WHERE archived = 0 OR archived IS NULL
    """, (archived_at,))

    count = cursor.rowcount
    conn.commit()
    conn.close()

    return count


def archive_current_by_status(status: str) -> int:
    """Archive non-archived articles for a specific curation status."""
    if status not in ("pending", "shortlisted", "rejected"):
        return 0

    conn = get_connection()
    cursor = conn.cursor()
    archived_at = datetime.now().isoformat()

    cursor.execute("""
        UPDATE curation
        SET archived = 1, archived_at = ?
        WHERE (archived = 0 OR archived IS NULL) AND status = ?
    """, (archived_at, status))

    count = cursor.rowcount
    conn.commit()
    conn.close()
    return count


def unarchive_article(article_id: str) -> bool:
    """Unarchive a single article, bringing it back to current view."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE curation
        SET archived = 0, archived_at = NULL
        WHERE article_id = ?
    """, (article_id,))

    success = cursor.rowcount > 0
    conn.commit()
    conn.close()

    return success


def get_archived_weeks() -> list[dict]:
    """Get list of weeks that have archived articles with counts."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT a.week, COUNT(*) as count,
               SUM(CASE WHEN c.status = 'shortlisted' THEN 1 ELSE 0 END) as shortlisted,
               SUM(CASE WHEN c.status = 'rejected' THEN 1 ELSE 0 END) as rejected
        FROM articles a
        JOIN curation c ON a.id = c.article_id
        WHERE c.archived = 1
        GROUP BY a.week
        ORDER BY a.week DESC
    """)

    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]


def get_all_newsletters() -> list[dict]:
    """Get all generated newsletters."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM newsletters
        ORDER BY generated_at DESC
    """)

    rows = cursor.fetchall()
    conn.close()

    results = []
    for row in rows:
        r = dict(row)
        r["article_ids"] = json.loads(r["article_ids"])
        results.append(r)

    return results


def get_articles_by_status(week: Optional[str] = None, status: str = "pending",
                           include_archived: bool = False) -> list[dict]:
    """Get articles filtered by curation status."""
    conn = get_connection()
    cursor = conn.cursor()

    archive_filter = "" if include_archived else "AND (c.archived = 0 OR c.archived IS NULL)"

    if week:
        cursor.execute(f"""
            SELECT a.*, c.status, c.user_notes, c.curated_at, c.archived, c.archived_at, c.top_pick
            FROM articles a
            LEFT JOIN curation c ON a.id = c.article_id
            WHERE a.week = ? AND c.status = ? {archive_filter}
            ORDER BY c.top_pick DESC, COALESCE(a.published, a.fetched_at) DESC
        """, (week, status))
    else:
        cursor.execute(f"""
            SELECT a.*, c.status, c.user_notes, c.curated_at, c.archived, c.archived_at, c.top_pick
            FROM articles a
            LEFT JOIN curation c ON a.id = c.article_id
            WHERE c.status = ? {archive_filter}
            ORDER BY c.top_pick DESC, COALESCE(a.published, a.fetched_at) DESC
        """, (status,))

    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]


def get_pending_articles(week: Optional[str] = None) -> list[dict]:
    """Get articles needing curation."""
    return get_articles_by_status(week, "pending")


def get_shortlisted_articles(week: Optional[str] = None) -> list[dict]:
    """Get articles ready for newsletter."""
    return get_articles_by_status(week, "shortlisted")


def get_article_by_id(article_id: str) -> Optional[dict]:
    """Get a single article by ID."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT a.*, c.status, c.user_notes, c.curated_at, c.top_pick
        FROM articles a
        LEFT JOIN curation c ON a.id = c.article_id
        WHERE a.id = ?
    """, (article_id,))

    row = cursor.fetchone()
    conn.close()

    return dict(row) if row else None


def set_article_status(article_id: str, status: str, notes: Optional[str] = None) -> bool:
    """Update curation state for an article."""
    if status not in ("pending", "shortlisted", "rejected"):
        return False

    conn = get_connection()
    cursor = conn.cursor()
    curated_at = datetime.now().isoformat()

    clear_top_pick = status != "shortlisted"

    if notes is not None:
        if clear_top_pick:
            cursor.execute("""
                UPDATE curation
                SET status = ?, user_notes = ?, curated_at = ?, top_pick = 0
                WHERE article_id = ?
            """, (status, notes, curated_at, article_id))
        else:
            cursor.execute("""
                UPDATE curation
                SET status = ?, user_notes = ?, curated_at = ?
                WHERE article_id = ?
            """, (status, notes, curated_at, article_id))
    else:
        if clear_top_pick:
            cursor.execute("""
                UPDATE curation
                SET status = ?, curated_at = ?, top_pick = 0
                WHERE article_id = ?
            """, (status, curated_at, article_id))
        else:
            cursor.execute("""
                UPDATE curation
                SET status = ?, curated_at = ?
                WHERE article_id = ?
            """, (status, curated_at, article_id))

    success = cursor.rowcount > 0
    conn.commit()
    conn.close()

    return success


def update_article_notes(article_id: str, notes: str) -> bool:
    """Update just the notes for an article."""
    conn = get_connection()
    cursor = conn.cursor()
    curated_at = datetime.now().isoformat()

    cursor.execute("""
        UPDATE curation
        SET user_notes = ?, curated_at = ?
        WHERE article_id = ?
    """, (notes, curated_at, article_id))

    success = cursor.rowcount > 0
    conn.commit()
    conn.close()

    return success


def set_top_pick(article_id: str, top_pick: bool) -> bool:
    """Toggle top-pick status for a shortlisted article."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT status FROM curation WHERE article_id = ?
    """, (article_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return False

    if top_pick and row["status"] != "shortlisted":
        conn.close()
        return False

    cursor.execute("""
        UPDATE curation
        SET top_pick = ?
        WHERE article_id = ?
    """, (1 if top_pick else 0, article_id))

    success = cursor.rowcount > 0
    conn.commit()
    conn.close()

    return success


def get_available_weeks() -> list[str]:
    """Get list of weeks that have articles."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT DISTINCT week FROM articles
        ORDER BY week DESC
    """)

    rows = cursor.fetchall()
    conn.close()

    return [row["week"] for row in rows]


def get_week_stats(week: str) -> dict:
    """Get statistics for a week."""
    conn = get_connection()
    cursor = conn.cursor()

    # Total articles
    cursor.execute("SELECT COUNT(*) as count FROM articles WHERE week = ?", (week,))
    total = cursor.fetchone()["count"]

    # Status counts
    cursor.execute("""
        SELECT c.status, COUNT(*) as count
        FROM articles a
        JOIN curation c ON a.id = c.article_id
        WHERE a.week = ?
        GROUP BY c.status
    """, (week,))

    status_counts = {row["status"]: row["count"] for row in cursor.fetchall()}

    # Topic distribution
    cursor.execute("""
        SELECT topic, COUNT(*) as count
        FROM articles
        WHERE week = ?
        GROUP BY topic
        ORDER BY count DESC
    """, (week,))

    topics = {row["topic"]: row["count"] for row in cursor.fetchall()}

    conn.close()

    return {
        "total": total,
        "pending": status_counts.get("pending", 0),
        "shortlisted": status_counts.get("shortlisted", 0),
        "rejected": status_counts.get("rejected", 0),
        "topics": topics
    }


def get_current_stats() -> dict:
    """Get statistics for current (non-archived) articles."""
    conn = get_connection()
    cursor = conn.cursor()

    # Total current articles
    cursor.execute("""
        SELECT COUNT(*) as count FROM curation
        WHERE archived = 0 OR archived IS NULL
    """)
    total = cursor.fetchone()["count"]

    # Status counts
    cursor.execute("""
        SELECT c.status, COUNT(*) as count
        FROM curation c
        WHERE c.archived = 0 OR c.archived IS NULL
        GROUP BY c.status
    """)
    status_counts = {row["status"]: row["count"] for row in cursor.fetchall()}

    # Topic distribution for current articles
    cursor.execute("""
        SELECT a.topic, COUNT(*) as count
        FROM articles a
        JOIN curation c ON a.id = c.article_id
        WHERE c.archived = 0 OR c.archived IS NULL
        GROUP BY a.topic
        ORDER BY count DESC
    """)
    topics = {row["topic"]: row["count"] for row in cursor.fetchall()}

    conn.close()

    return {
        "total": total,
        "pending": status_counts.get("pending", 0),
        "shortlisted": status_counts.get("shortlisted", 0),
        "rejected": status_counts.get("rejected", 0),
        "topics": topics
    }


def save_newsletter(week: str, article_ids: list[str], output_path: str) -> str:
    """Save newsletter record to database."""
    conn = get_connection()
    cursor = conn.cursor()

    newsletter_id = hashlib.sha256(f"{week}-{datetime.now().isoformat()}".encode()).hexdigest()[:16]
    generated_at = datetime.now().isoformat()

    cursor.execute("""
        INSERT INTO newsletters (id, week, generated_at, article_ids, output_path)
        VALUES (?, ?, ?, ?, ?)
    """, (newsletter_id, week, generated_at, json.dumps(article_ids), output_path))

    conn.commit()
    conn.close()

    return newsletter_id


def get_curated_examples(limit_per_status: int = 10) -> dict:
    """
    Get examples of previously curated articles for use in scoring prompts.
    Returns shortlisted and rejected articles with their metadata.
    """
    conn = get_connection()
    cursor = conn.cursor()

    result = {"shortlisted": [], "rejected": []}

    for status in ["shortlisted", "rejected"]:
        cursor.execute("""
            SELECT a.title, a.summary, a.source, a.topic, c.user_notes
            FROM articles a
            JOIN curation c ON a.id = c.article_id
            WHERE c.status = ?
            ORDER BY c.curated_at DESC
            LIMIT ?
        """, (status, limit_per_status))

        rows = cursor.fetchall()
        result[status] = [dict(row) for row in rows]

    conn.close()
    return result


def get_curation_stats() -> dict:
    """Get overall curation statistics for pattern analysis."""
    conn = get_connection()
    cursor = conn.cursor()

    # Topic preferences
    cursor.execute("""
        SELECT a.topic, c.status, COUNT(*) as count
        FROM articles a
        JOIN curation c ON a.id = c.article_id
        WHERE c.status IN ('shortlisted', 'rejected')
        GROUP BY a.topic, c.status
    """)

    topic_stats = {}
    for row in cursor.fetchall():
        topic = row["topic"] or "Unknown"
        if topic not in topic_stats:
            topic_stats[topic] = {"shortlisted": 0, "rejected": 0}
        topic_stats[topic][row["status"]] = row["count"]

    # Source preferences
    cursor.execute("""
        SELECT a.source, c.status, COUNT(*) as count
        FROM articles a
        JOIN curation c ON a.id = c.article_id
        WHERE c.status IN ('shortlisted', 'rejected')
        GROUP BY a.source, c.status
    """)

    source_stats = {}
    for row in cursor.fetchall():
        source = row["source"]
        if source not in source_stats:
            source_stats[source] = {"shortlisted": 0, "rejected": 0}
        source_stats[source][row["status"]] = row["count"]

    conn.close()

    return {
        "topics": topic_stats,
        "sources": source_stats
    }


def get_newsletter(week: str) -> Optional[dict]:
    """Get the most recent newsletter for a week."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM newsletters
        WHERE week = ?
        ORDER BY generated_at DESC
        LIMIT 1
    """, (week,))

    row = cursor.fetchone()
    conn.close()

    if row:
        result = dict(row)
        result["article_ids"] = json.loads(result["article_ids"])
        return result
    return None


def get_newsletter_by_id(newsletter_id: str) -> Optional[dict]:
    """Get a newsletter by its ID."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM newsletters WHERE id = ?", (newsletter_id,))

    row = cursor.fetchone()
    conn.close()

    if row:
        result = dict(row)
        result["article_ids"] = json.loads(result["article_ids"])
        return result
    return None


def migrate_from_json(json_path: str, week: Optional[str] = None) -> int:
    """
    Migrate existing digest_data.json to SQLite.
    Returns number of articles migrated.
    """
    import os

    if not os.path.exists(json_path):
        return 0

    with open(json_path, "r") as f:
        data = json.load(f)

    items = data.get("items", [])
    if not items:
        return 0

    # Use provided week or derive from generated_at
    if week is None:
        generated_at = data.get("generated_at", "")
        if generated_at:
            try:
                dt = datetime.fromisoformat(generated_at)
                week = dt.strftime("%G-W%V")
            except ValueError:
                week = get_current_week()
        else:
            week = get_current_week()

    return upsert_articles(items, week)


# Initialize database on import
init_db()
