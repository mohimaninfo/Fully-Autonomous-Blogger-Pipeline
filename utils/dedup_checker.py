"""
dedup_checker.py — Duplicate post detection for the autonomous blogger pipeline.

Prevents publishing posts too similar to existing content by comparing:
1. Exact title match (caught immediately)
2. Normalized title similarity (fuzzy match)
3. URL slug similarity

Uses a simple, dependency-light approach: character n-gram similarity
(no heavy NLP libraries required in the free-tier environment).
"""

import json
import logging
import re
import unicodedata
from pathlib import Path

from config.settings import LOGS_DIR, PipelineConfig

logger = logging.getLogger(__name__)


def normalize_text(text: str) -> str:
    """
    Normalize a title for comparison:
    - Lowercase
    - Remove punctuation and special characters
    - Collapse whitespace
    - Remove stop words
    """
    STOP_WORDS = {
        "a", "an", "the", "and", "or", "but", "in", "on", "at", "to",
        "for", "of", "with", "by", "from", "is", "are", "was", "were",
        "be", "been", "being", "have", "has", "had", "do", "does", "did",
        "will", "would", "could", "should", "may", "might", "shall",
        "this", "that", "these", "those", "it", "its", "how", "what",
        "why", "when", "where", "who", "which",
    }

    # Unicode normalization → lowercase
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = text.lower()

    # Remove non-alphanumeric characters
    text = re.sub(r"[^a-z0-9\s]", " ", text)

    # Remove stop words
    words = text.split()
    words = [w for w in words if w not in STOP_WORDS and len(w) > 1]

    return " ".join(words)


def ngram_similarity(text1: str, text2: str, n: int = 3) -> float:
    """
    Compute character n-gram based similarity between two normalized texts.
    Returns a score between 0.0 (completely different) and 1.0 (identical).

    Character trigrams are more robust than word-level comparison for
    detecting paraphrased titles and near-duplicates.
    """
    if not text1 or not text2:
        return 0.0

    if text1 == text2:
        return 1.0

    def get_ngrams(text: str, n: int) -> set:
        # Pad text for edge n-grams
        padded = f"{'#' * (n-1)}{text}{'#' * (n-1)}"
        return set(padded[i:i+n] for i in range(len(padded) - n + 1))

    ngrams1 = get_ngrams(text1, n)
    ngrams2 = get_ngrams(text2, n)

    if not ngrams1 or not ngrams2:
        return 0.0

    # Dice coefficient
    intersection = len(ngrams1 & ngrams2)
    return (2.0 * intersection) / (len(ngrams1) + len(ngrams2))


def title_to_slug(title: str) -> str:
    """Convert a post title to a URL slug for comparison."""
    slug = title.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug.strip())
    slug = re.sub(r"-+", "-", slug)
    return slug


class DedupChecker:
    """
    Checks candidate post titles against the existing post log.

    Usage:
        checker = DedupChecker()
        result = checker.is_duplicate("How AI Models Learn From Human Feedback")
        if result.is_duplicate:
            print(f"Too similar to: {result.matched_title}")
    """

    def __init__(self, published_posts: list[dict] = None):
        """
        Args:
            published_posts: Pre-loaded list of post dicts. If None, loads
                             from the published_posts.json log file.
        """
        if published_posts is not None:
            self._posts = published_posts
        else:
            self._posts = self._load_published_posts()

        # Pre-compute normalized titles for efficiency
        self._normalized_titles = [
            (post, normalize_text(post.get("title", "")))
            for post in self._posts
        ]
        logger.debug(f"DedupChecker loaded {len(self._posts)} existing posts.")

    def _load_published_posts(self) -> list[dict]:
        """Load the published posts log from disk."""
        log_path = LOGS_DIR / "published_posts.json"
        if not log_path.exists():
            logger.debug("No published_posts.json found — starting fresh.")
            return []
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Failed to load published posts log: {e}")
            return []

    def check(self, candidate_title: str) -> "DedupResult":
        """
        Check if a candidate title is a duplicate of any existing post.

        Returns a DedupResult with:
        - is_duplicate: bool
        - similarity_score: float (0.0–1.0)
        - matched_title: str (the matching existing title, if any)
        - matched_url: str
        """
        if not candidate_title:
            return DedupResult(
                candidate=candidate_title,
                is_duplicate=False,
                similarity_score=0.0
            )

        norm_candidate = normalize_text(candidate_title)
        threshold = PipelineConfig.DEDUP_SIMILARITY_THRESHOLD

        best_score = 0.0
        best_match = None

        for post, norm_existing in self._normalized_titles:
            score = ngram_similarity(norm_candidate, norm_existing)
            if score > best_score:
                best_score = score
                best_match = post

        is_dup = best_score >= threshold

        if is_dup:
            logger.warning(
                f"Duplicate detected: '{candidate_title[:60]}' "
                f"(score={best_score:.3f}) matches "
                f"'{best_match.get('title', '')[:60]}'"
            )
        else:
            logger.debug(
                f"No duplicate: '{candidate_title[:60]}' "
                f"(best_score={best_score:.3f})"
            )

        return DedupResult(
            candidate=candidate_title,
            is_duplicate=is_dup,
            similarity_score=best_score,
            matched_title=best_match.get("title") if best_match else None,
            matched_url=best_match.get("url") if best_match else None,
        )

    def filter_candidates(self, candidates: list[str]) -> list[str]:
        """
        Filter a list of candidate titles, returning only non-duplicate ones.
        Logs how many were filtered.
        """
        unique = []
        for title in candidates:
            result = self.check(title)
            if not result.is_duplicate:
                unique.append(title)

        removed = len(candidates) - len(unique)
        if removed > 0:
            logger.info(f"Dedup filter removed {removed}/{len(candidates)} duplicate candidates.")

        return unique

    def add_post(self, title: str, url: str, metadata: dict = None) -> None:
        """
        Add a newly published post to the in-memory index.
        Call this after publishing to keep the checker current within a run.
        """
        new_post = {"title": title, "url": url, **(metadata or {})}
        self._posts.append(new_post)
        self._normalized_titles.append((new_post, normalize_text(title)))
        logger.debug(f"DedupChecker: added post '{title[:60]}' to index.")


class DedupResult:
    """Result object returned by DedupChecker.check()."""

    def __init__(
        self,
        candidate: str,
        is_duplicate: bool,
        similarity_score: float,
        matched_title: str = None,
        matched_url: str = None,
    ):
        self.candidate = candidate
        self.is_duplicate = is_duplicate
        self.similarity_score = similarity_score
        self.matched_title = matched_title
        self.matched_url = matched_url

    def __repr__(self):
        return (
            f"DedupResult(is_duplicate={self.is_duplicate}, "
            f"score={self.similarity_score:.3f}, "
            f"matched='{(self.matched_title or '')[:40]}')"
        )
