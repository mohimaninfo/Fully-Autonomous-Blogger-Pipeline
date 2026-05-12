"""
agents/orchestrator.py
Agent 1: Orchestrator — Reads taxonomy, schedules tasks, and drives the pipeline.
"""

import json
import logging
import random
from datetime import datetime
from pathlib import Path

from agents.topic_discovery import TopicDiscoveryAgent
from agents.research import ResearchAgent
from agents.content_generation import ContentGenerationAgent
from agents.reference_citation import ReferenceCitationAgent
from agents.seo import SEOAgent
from agents.image_agent import ImageAgent
from agents.video_agent import VideoAgent
from agents.publisher import PublisherAgent

logger = logging.getLogger(__name__)

TAXONOMY_PATH = Path("taxonomy/taxonomy.json")
LOGS_PATH = Path("logs/pipeline_runs.json")
PUBLISHED_POSTS_PATH = Path("logs/published_posts.json")


class OrchestratorAgent:
    def __init__(self):
        self.taxonomy = self._load_taxonomy()
        self.published_posts = self._load_published_posts()
        self.run_log = []

    def _load_taxonomy(self) -> dict:
        with open(TAXONOMY_PATH) as f:
            return json.load(f)

    def _load_published_posts(self) -> list:
        if PUBLISHED_POSTS_PATH.exists():
            with open(PUBLISHED_POSTS_PATH) as f:
                return json.load(f)
        return []

    def _save_run_log(self, run_data: dict):
        LOGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        logs = []
        if LOGS_PATH.exists():
            with open(LOGS_PATH) as f:
                logs = json.load(f)
        logs.append(run_data)
        with open(LOGS_PATH, "w") as f:
            json.dump(logs, f, indent=2)

    def _select_task(self) -> dict:
        """
        Selects genre/topic/layer based on rotation logic.
        Prioritizes least-recently-posted combinations.
        """
        genres = self.taxonomy["genres"]
        layers_meta = self.taxonomy["layers"]

        # Build a frequency map from published posts
        freq = {}
        for post in self.published_posts:
            key = f"{post.get('genre','')}/{post.get('topic','')}"
            freq[key] = freq.get(key, 0) + 1

        # Collect all valid genre/topic/layer combos
        candidates = []
        for genre in genres:
            for topic in genre["topics"]:
                key = f"{genre['id']}/{topic['id']}"
                weight = 1 / (freq.get(key, 0) + 1)  # inverse frequency
                for layer in topic["layers"]:
                    candidates.append({
                        "genre_id": genre["id"],
                        "genre_label": genre["label"],
                        "genre_slug": genre["slug"],
                        "genre_color": genre["color"],
                        "tone_profile": genre["tone_profile"],
                        "topic_id": topic["id"],
                        "topic_label": topic["label"],
                        "topic_slug": topic["slug"],
                        "layer": layer,
                        "layer_meta": layers_meta[layer],
                        "weight": weight,
                    })

        if not candidates:
            raise RuntimeError("No valid genre/topic/layer candidates found.")

        # Weighted random selection
        weights = [c["weight"] for c in candidates]
        selected = random.choices(candidates, weights=weights, k=1)[0]
        logger.info(
            f"Task selected: {selected['genre_label']} / {selected['topic_label']} / {selected['layer']}"
        )
        return selected

    def run(self, posts_per_run: int = 2) -> list:
        """
        Main pipeline run. Generates `posts_per_run` posts.
        Returns list of published post metadata dicts.
        """
        run_start = datetime.utcnow().isoformat()
        results = []

        for i in range(posts_per_run):
            logger.info(f"\n{'='*60}\nStarting post {i+1}/{posts_per_run}\n{'='*60}")
            try:
                result = self._run_single_post()
                results.append(result)
                logger.info(f"Post {i+1} published: {result.get('url', 'unknown')}")
            except Exception as e:
                logger.error(f"Post {i+1} failed: {e}", exc_info=True)
                results.append({"error": str(e), "post_index": i + 1})

        self._save_run_log({
            "run_start": run_start,
            "run_end": datetime.utcnow().isoformat(),
            "posts_attempted": posts_per_run,
            "posts_succeeded": sum(1 for r in results if "url" in r),
            "results": results,
        })

        return results

    def _run_single_post(self) -> dict:
        """Execute the full pipeline for one post."""

        # Step 1: Select task
        task = self._select_task()

        # Step 2: Topic Discovery
        logger.info("Agent 2: Topic Discovery")
        discovery_agent = TopicDiscoveryAgent(self.published_posts)
        topic_idea = discovery_agent.discover(
            genre=task["genre_id"],
            topic=task["topic_id"],
            layer=task["layer"],
        )
        task["topic_idea"] = topic_idea
        logger.info(f"Topic idea: {topic_idea['title']}")

        # Step 3: Research
        logger.info("Agent 3: Research")
        research_agent = ResearchAgent()
        research_brief = research_agent.research(task)
        task["research_brief"] = research_brief

        # Step 4: Content Generation
        logger.info("Agent 4: Content Generation")
        content_agent = ContentGenerationAgent()
        post_draft = content_agent.generate(task)
        task["post_draft"] = post_draft

        # Step 5: Reference & Citation
        logger.info("Agent 5: Reference & Citation")
        citation_agent = ReferenceCitationAgent()
        post_with_citations = citation_agent.process(task)
        task["post_with_citations"] = post_with_citations

        # Step 6: SEO
        logger.info("Agent 6: SEO")
        seo_agent = SEOAgent()
        seo_data = seo_agent.optimize(task)
        task["seo_data"] = seo_data

        # Step 7: Image
        logger.info("Agent 7: Image")
        image_agent = ImageAgent()
        images = image_agent.find_images(task)
        task["images"] = images

        # Step 8: Video
        logger.info("Agent 8: Video")
        video_agent = VideoAgent()
        video_data = video_agent.decide_and_fetch(task)
        task["video_data"] = video_data

        # Step 9: Publish
        logger.info("Agent 9: Publisher")
        publisher = PublisherAgent()
        published = publisher.publish(task)

        # Update local published posts log
        self.published_posts.append(published)

        return published
