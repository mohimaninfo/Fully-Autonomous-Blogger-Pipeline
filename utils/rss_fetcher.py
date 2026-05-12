"""
rss_fetcher.py — Fetches trending topics from Google Trends RSS and Reddit RSS.

Data sources (all free, no API key required):
- Google Trends RSS: https://trends.google.com/trends/trendingsearches/daily/rss?geo=US
- Reddit RSS: https://www.reddit.com/r/{subreddit}/hot.rss

Returns structured topic candidates for Agent 2 (Topic Discovery).
"""

import logging
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional
from urllib.parse import quote_plus

import requests

from config.settings import PipelineConfig

logger = logging.getLogger(__name__)


@dataclass
class TrendingItem:
    title: str
    source: str           # "google_trends" or "reddit_{subreddit}"
    url: str = ""
    score: int = 0        # Reddit upvotes, or Google trending rank
    published: Optional[datetime] = None
    genre_hint: str = ""  # Suggested genre mapping, if detectable
    raw_snippet: str = ""


# ── Genre → subreddit mapping ─────────────────────────────────────────────────
GENRE_SUBREDDITS: dict[str, list[str]] = {
    "technology": ["technology", "programming", "artificial", "MachineLearning", "cybersecurity"],
    "health": ["Health", "nutrition", "medicine", "mentalhealth"],
    "finance": ["personalfinance", "investing", "economics", "wallstreetbets"],
    "science": ["science", "Physics", "biology", "chemistry", "space"],
    "lifestyle": ["lifestyle", "selfimprovement", "productivity", "minimalism"],
    "education": ["learnprogramming", "GetStudying", "education", "todayilearned"],
    "business": ["Entrepreneur", "business", "startups", "marketing"],
    "entertainment": ["movies", "television", "gaming", "Music", "books"],
    "environment": ["environment", "climate", "sustainability", "renewable"],
    "society": ["worldnews", "news", "sociology", "dataisbeautiful"],
}

GOOGLE_TRENDS_URL = "https://trends.google.com/trends/trendingsearches/daily/rss"
REDDIT_HOT_URL = "https://www.reddit.com/r/{subreddit}/hot.rss"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; AutonomousBlogger/1.0; "
        "+https://github.com/your-username/autonomous-blogger)"
    )
}

REQUEST_TIMEOUT = 15
MAX_ITEMS_PER_SOURCE = 20
INTER_REQUEST_DELAY = 1.0  # Politeness delay between requests


def _parse_rss_date(date_str: str) -> Optional[datetime]:
    """Parse RFC 2822 date strings from RSS feeds."""
    if not date_str:
        return None
    formats = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S GMT",
        "%Y-%m-%dT%H:%M:%S%z",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue
    return None


def _is_recent(published: Optional[datetime], max_age_days: int) -> bool:
    """Check if an item is within the allowed age window."""
    if published is None:
        return True  # Can't determine age — include it
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    return published >= cutoff


def _clean_title(title: str) -> str:
    """Strip HTML tags, decode entities, and normalize whitespace."""
    if not title:
        return ""
    # Remove HTML tags
    title = re.sub(r"<[^>]+>", "", title)
    # Decode basic HTML entities
    entities = {"&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&#39;": "'"}
    for entity, char in entities.items():
        title = title.replace(entity, char)
    return " ".join(title.split()).strip()


# ── Google Trends ─────────────────────────────────────────────────────────────

def fetch_google_trends(geo: str = "US", max_age_days: int = None) -> list[TrendingItem]:
    """
    Fetch daily trending searches from Google Trends RSS.
    Returns up to MAX_ITEMS_PER_SOURCE items.

    Args:
        geo: Country code (US, GB, IN, etc.)
        max_age_days: Maximum age of trends to include
    """
    if max_age_days is None:
        max_age_days = PipelineConfig.RSS_MAX_AGE_DAYS

    url = f"{GOOGLE_TRENDS_URL}?geo={geo}"
    items = []

    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()

        root = ET.fromstring(resp.content)
        channel = root.find("channel")
        if channel is None:
            logger.warning("Google Trends RSS: no channel element found.")
            return []

        rank = 1
        for item_elem in channel.findall("item"):
            if len(items) >= MAX_ITEMS_PER_SOURCE:
                break

            title_el = item_elem.find("title")
            pubdate_el = item_elem.find("pubDate")
            link_el = item_elem.find("link")

            title = _clean_title(title_el.text if title_el is not None else "")
            if not title:
                continue

            published = _parse_rss_date(pubdate_el.text if pubdate_el is not None else "")
            if not _is_recent(published, max_age_days):
                continue

            items.append(TrendingItem(
                title=title,
                source="google_trends",
                url=link_el.text.strip() if link_el is not None and link_el.text else "",
                score=MAX_ITEMS_PER_SOURCE - rank + 1,  # Higher rank = higher score
                published=published,
            ))
            rank += 1

        logger.info(f"Google Trends: fetched {len(items)} trending items (geo={geo})")

    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch Google Trends RSS: {e}")
    except ET.ParseError as e:
        logger.error(f"Failed to parse Google Trends RSS XML: {e}")

    return items


# ── Reddit RSS ────────────────────────────────────────────────────────────────

def fetch_reddit_hot(subreddit: str, max_age_days: int = None) -> list[TrendingItem]:
    """
    Fetch hot posts from a subreddit's RSS feed.
    No API key required — uses the public JSON endpoint as fallback.

    Args:
        subreddit: Subreddit name (without r/)
        max_age_days: Maximum post age to include
    """
    if max_age_days is None:
        max_age_days = PipelineConfig.RSS_MAX_AGE_DAYS

    url = REDDIT_HOT_URL.format(subreddit=subreddit)
    items = []

    try:
        time.sleep(INTER_REQUEST_DELAY)
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)

        # Reddit returns 403 for some subreddits for bots
        if resp.status_code == 403:
            logger.debug(f"Reddit r/{subreddit}: access denied (403). Skipping.")
            return []

        resp.raise_for_status()

        root = ET.fromstring(resp.content)

        # Reddit RSS uses Atom format
        ns = {"atom": "http://www.w3.org/2005/Atom"}

        for entry in root.findall("atom:entry", ns)[:MAX_ITEMS_PER_SOURCE]:
            title_el = entry.find("atom:title", ns)
            link_el = entry.find("atom:link", ns)
            updated_el = entry.find("atom:updated", ns)
            content_el = entry.find("atom:content", ns)

            title = _clean_title(title_el.text if title_el is not None else "")
            if not title or len(title) < 10:
                continue

            published = _parse_rss_date(updated_el.text if updated_el is not None else "")
            if not _is_recent(published, max_age_days):
                continue

            link = ""
            if link_el is not None:
                link = link_el.get("href", "")

            snippet = ""
            if content_el is not None and content_el.text:
                snippet = re.sub(r"<[^>]+>", "", content_el.text)[:200]

            items.append(TrendingItem(
                title=title,
                source=f"reddit_r/{subreddit}",
                url=link,
                score=0,  # Reddit RSS doesn't expose vote counts
                published=published,
                raw_snippet=snippet,
            ))

        logger.debug(f"Reddit r/{subreddit}: fetched {len(items)} hot posts")

    except requests.exceptions.RequestException as e:
        logger.warning(f"Failed to fetch Reddit r/{subreddit} RSS: {e}")
    except ET.ParseError as e:
        logger.warning(f"Failed to parse Reddit r/{subreddit} RSS: {e}")

    return items


# ── Multi-genre fetch ─────────────────────────────────────────────────────────

def fetch_all_trends(genres: list[str] = None) -> dict[str, list[TrendingItem]]:
    """
    Fetch trending items for specified genres (or all genres if None).
    Returns a dict mapping genre → list of TrendingItems.

    Includes both Google Trends and relevant subreddits per genre.
    """
    if genres is None:
        genres = list(GENRE_SUBREDDITS.keys())

    results: dict[str, list[TrendingItem]] = {}

    # Google Trends applies broadly — add to all genres with genre hints later
    logger.info("Fetching Google Trends RSS...")
    global_trends = fetch_google_trends()

    for genre in genres:
        genre_items = []

        # Add relevant global trends (no genre filtering at this stage)
        genre_items.extend(global_trends)

        # Fetch genre-specific subreddits
        subreddits = GENRE_SUBREDDITS.get(genre, [])
        for subreddit in subreddits[:3]:  # Max 3 subreddits per genre
            reddit_items = fetch_reddit_hot(subreddit)
            for item in reddit_items:
                item.genre_hint = genre
            genre_items.extend(reddit_items)

        # Deduplicate by title within genre
        seen_titles = set()
        deduped = []
        for item in genre_items:
            norm_title = item.title.lower().strip()
            if norm_title not in seen_titles:
                seen_titles.add(norm_title)
                deduped.append(item)

        results[genre] = deduped
        logger.info(f"Genre '{genre}': {len(deduped)} trending items collected.")

    return results


def fetch_genre_trends(genre: str) -> list[TrendingItem]:
    """Convenience function to fetch trends for a single genre."""
    all_results = fetch_all_trends(genres=[genre])
    return all_results.get(genre, [])
