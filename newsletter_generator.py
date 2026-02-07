#!/usr/bin/env python3
"""
Newsletter Generator - Generates link-blog style newsletters from curated articles.
Uses AI to synthesize user notes into polished commentary.
"""
import os
import re
import time
from datetime import datetime
from typing import Optional

import requests

try:
    from google import genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

import config
import db


def synthesize_commentary(article: dict, user_notes: str) -> str:
    """
    Return curator notes only.
    LinkedIn copy prefers plain text with explicit URLs.
    """
    return user_notes or ""


def format_article_section(article: dict, commentary: str) -> str:
    """Format a single article for the newsletter (title, link, notes only)."""
    lines = []

    # Title and explicit URL on their own lines for reliable copy/paste
    lines.append(f"### {article['title']}")
    lines.append(article["url"])
    lines.append("")

    # Commentary (curator notes only)
    if commentary:
        lines.append(commentary)
        lines.append("")

    lines.append("---")
    lines.append("")

    return "\n".join(lines)


def generate_newsletter(week: Optional[str] = None, dry_run: bool = False) -> dict:
    """
    Generate a newsletter from current shortlisted (non-archived) articles.
    Returns dict with path and metadata.
    """
    if week is None:
        week = db.get_current_week()

    print(f"\nGenerating newsletter for {week}...")

    # Get current shortlisted articles (non-archived)
    articles = db.get_articles_by_status(status="shortlisted", include_archived=False)

    if not articles:
        return {
            "success": False,
            "error": "No shortlisted articles found",
            "week": week
        }

    print(f"  Found {len(articles)} shortlisted articles")

    # Parse week for display
    try:
        year, week_num = week.split("-W")
        week_display = f"Week {int(week_num)}, {year}"
    except ValueError:
        week_display = week

    # Start building newsletter
    lines = [
        f"# AI Newsletter - {week_display}",
        "",
        f"*Generated on {datetime.now().strftime('%Y-%m-%d %H:%M')}*",
        "",
    ]

    # Process each article
    top_picks = [a for a in articles if a.get("top_pick")]
    other_picks = [a for a in articles if not a.get("top_pick")]

    article_ids = []
    ordered_articles = top_picks + other_picks
    for i, article in enumerate(ordered_articles, 1):
        print(f"  [{i}/{len(ordered_articles)}] Processing: {article['title'][:50]}...")

        # Synthesize commentary
        user_notes = article.get("user_notes") or ""
        if dry_run:
            commentary = user_notes or "[Commentary would be generated here]"
        else:
            commentary = synthesize_commentary(article, user_notes)

        # Add to newsletter
        if top_picks and article == top_picks[0]:
            lines.extend([
                "## Top Picks",
                "",
            ])
        if other_picks and article == other_picks[0]:
            lines.extend([
                "## More Picks" if top_picks else "## Picks This Week",
                "",
            ])

        lines.append(format_article_section(article, commentary))
        article_ids.append(article["id"])

    # Footer
    lines.extend([
        "",
        "---",
        "",
        "*This newsletter was curated with help from AI.*",
    ])

    # Write to file with timestamp to preserve versions
    os.makedirs(config.NEWSLETTER_OUTPUT_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = os.path.join(config.NEWSLETTER_OUTPUT_DIR, f"newsletter_{week}_{timestamp}.md")

    content = "\n".join(lines)
    with open(output_path, "w") as f:
        f.write(content)

    print(f"  Newsletter saved to: {output_path}")

    # Save to database
    newsletter_id = db.save_newsletter(week, article_ids, output_path)

    return {
        "success": True,
        "week": week,
        "newsletter_id": newsletter_id,
        "output_path": output_path,
        "article_count": len(articles),
        "content": content
    }


def main():
    """CLI entry point for newsletter generation."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate newsletter from shortlisted articles."
    )
    parser.add_argument(
        "--week",
        type=str,
        default=None,
        help="Week identifier (e.g., '2026-W05'). Defaults to current week.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate without AI synthesis (uses raw notes).",
    )
    args = parser.parse_args()

    result = generate_newsletter(args.week, args.dry_run)

    if result["success"]:
        print(f"\nNewsletter generated successfully!")
        print(f"  Week: {result['week']}")
        print(f"  Articles: {result['article_count']}")
        print(f"  Output: {result['output_path']}")
    else:
        print(f"\nFailed to generate newsletter: {result.get('error')}")


if __name__ == "__main__":
    main()
