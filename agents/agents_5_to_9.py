"""
agents/reference_citation.py
Agent 5: Validates and formats the reference list; inserts citation markers into HTML.
"""

import json
import logging
import re
from datetime import date
from utils.gemini_client import call_gemini
from utils.link_validator import validate_url_with_fallback

logger = logging.getLogger(__name__)


class ReferenceCitationAgent:
    def process(self, task: dict) -> dict:
        """
        Inserts superscript citation markers and appends a formatted reference section.
        Returns dict with updated html_body and references list.
        """
        research_brief = task["research_brief"]
        post_draft = task["post_draft"]
        html_body = post_draft["html_body"]

        # Build reference list from source URLs in research brief
        raw_sources = research_brief.get("source_urls", [])
        key_facts = research_brief.get("key_facts", [])
        expert_quotes = research_brief.get("expert_quotes", [])
        statistics = research_brief.get("statistics", [])

        # Collect all source URLs with metadata
        all_sources = {}
        counter = 1

        for item in key_facts + statistics:
            url = item.get("source_url", "")
            if url and url not in all_sources:
                validated_url = validate_url_with_fallback(url)
                all_sources[url] = {
                    "index": counter,
                    "source_name": item.get("source_name", "Source"),
                    "url": validated_url,
                    "year": item.get("year", date.today().year),
                    "accessed": str(date.today()),
                }
                counter += 1

        for item in expert_quotes:
            url = item.get("source_url", "")
            if url and url not in all_sources:
                validated_url = validate_url_with_fallback(url)
                all_sources[url] = {
                    "index": counter,
                    "source_name": f"{item.get('expert_name', 'Expert')}, {item.get('expert_title', '')}",
                    "url": validated_url,
                    "year": date.today().year,
                    "accessed": str(date.today()),
                }
                counter += 1

        # Add any remaining raw_sources not yet included
        for url in raw_sources:
            if url and url not in all_sources:
                validated_url = validate_url_with_fallback(url)
                all_sources[url] = {
                    "index": counter,
                    "source_name": url.split('/')[2] if '/' in url else url,
                    "url": validated_url,
                    "year": date.today().year,
                    "accessed": str(date.today()),
                }
                counter += 1

        references = sorted(all_sources.values(), key=lambda x: x["index"])

        # Build HTML reference section
        ref_html = self._build_reference_html(references)

        # Ask Gemini to insert citation markers into the existing HTML
        if references:
            html_body = self._insert_citations(html_body, research_brief, references)

        full_html = html_body + "\n" + ref_html

        return {
            "html_body": full_html,
            "references": references,
        }

    def _insert_citations(self, html: str, brief: dict, references: list) -> str:
        """Uses Gemini to insert ¹²³ citation markers after factual claims."""
        ref_summary = "\n".join(
            f"[{r['index']}] {r['source_name']} — {r['url']}"
            for r in references[:10]
        )

        prompt = f"""You are a copy editor. Add superscript citation markers to the HTML below.

REFERENCES AVAILABLE:
{ref_summary}

INSTRUCTIONS:
1. After each factual claim, statistic, or direct/paraphrased expert statement, add a superscript: <sup>[1]</sup>
2. Match claims to the most relevant reference number based on source name
3. Do NOT add citations where none are appropriate
4. Do NOT change the HTML structure, just insert <sup> tags
5. Return the complete HTML with citations inserted

HTML TO ANNOTATE:
{html[:6000]}

Return only the annotated HTML:"""

        try:
            annotated = call_gemini(prompt, max_tokens=8192, temperature=0.1)
            # Strip any markdown code fences
            annotated = re.sub(r'^```html?\n?|```$', '', annotated.strip())
            return annotated
        except Exception as e:
            logger.warning(f"Citation insertion failed: {e}. Returning original HTML.")
            return html

    def _build_reference_html(self, references: list) -> str:
        if not references:
            return ""

        items = ""
        for ref in references:
            items += f"""
    <li id="ref-{ref['index']}">
      [{ref['index']}] {ref['source_name']}.
      <a href="{ref['url']}" target="_blank" rel="noopener noreferrer nofollow">{ref['url']}</a>.
      Accessed {ref['accessed']}.
    </li>"""

        return f"""
<section class="references-section" aria-label="References">
  <h2>References</h2>
  <ol class="reference-list">
{items}
  </ol>
</section>"""


# ─────────────────────────────────────────────────────────────────────────────

"""
agents/seo.py
Agent 6: SEO — Generates JSON-LD schema, Open Graph tags, labels, and meta data.
"""

import json
import logging
import re
from datetime import datetime

logger = logging.getLogger(__name__)

SCHEMA_TYPES = {
    "latest-news": "NewsArticle",
    "research-articles": "ScholarlyArticle",
    "how-to-guides": "HowTo",
    "opinion-analysis": "OpinionNewsArticle",
    "case-studies": "Article",
    "interviews": "Article",
    "listicles": "ItemList",
    "reviews": "Review",
    "explainers": "Article",
}

AUTHOR_BYLINES = {
    "technology": "Alex Chen, Technology Correspondent",
    "health": "Dr. Maya Patel, Health & Wellness Editor",
    "finance": "Marcus Webb, Financial Analyst",
    "science": "Dr. Sarah Okonkwo, Science Journalist",
    "lifestyle": "Jordan Taylor, Lifestyle Editor",
    "business": "Daniel Park, Business Reporter",
    "education": "Emma Rossi, Education Writer",
    "environment": "Liam Torres, Environmental Correspondent",
    "society": "Aisha Williams, Society & Culture Editor",
    "entertainment": "Riley Johnson, Entertainment Editor",
}


class SEOAgent:
    def optimize(self, task: dict) -> dict:
        genre_id = task["genre_id"]
        genre_slug = task["genre_slug"]
        topic_slug = task["topic_slug"]
        layer_slug = task["layer_meta"]["slug"]
        slug = task["post_draft"]["slug"]
        title = task["post_draft"]["title"]
        meta_description = task["post_draft"]["meta_description"]
        keywords = task["topic_idea"]["keywords"]
        layer = task["layer"]
        genre_label = task["genre_label"]
        topic_label = task["topic_label"]
        layer_label = task["layer_meta"]["label"]
        genre_color = task["genre_color"]

        author = AUTHOR_BYLINES.get(genre_id, "Editorial Team")
        schema_type = SCHEMA_TYPES.get(layer, "Article")
        pub_date = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        canonical_url = f"https://yourblog.blogspot.com/{genre_slug}/{topic_slug}/{layer_slug}/{slug}"

        # Blogger labels: genre + topic + layer + keywords
        labels = [genre_label, topic_label, layer_label] + keywords[:3]

        # JSON-LD Schema
        json_ld = {
            "@context": "https://schema.org",
            "@type": schema_type,
            "headline": title,
            "description": meta_description,
            "author": {"@type": "Person", "name": author},
            "publisher": {
                "@type": "Organization",
                "name": "YourBlog",
                "url": "https://yourblog.blogspot.com",
            },
            "datePublished": pub_date,
            "dateModified": pub_date,
            "url": canonical_url,
            "keywords": ", ".join(keywords),
            "articleSection": genre_label,
            "inLanguage": "en-US",
        }

        schema_script = f'<script type="application/ld+json">\n{json.dumps(json_ld, indent=2)}\n</script>'

        # Open Graph + Twitter Card meta tags
        og_tags = f"""<!-- Open Graph -->
<meta property="og:title" content="{self._escape(title)}" />
<meta property="og:description" content="{self._escape(meta_description)}" />
<meta property="og:type" content="article" />
<meta property="og:url" content="{canonical_url}" />
<meta property="og:site_name" content="YourBlog" />
<meta property="article:section" content="{genre_label}" />
<meta property="article:tag" content="{', '.join(keywords)}" />
<meta property="article:published_time" content="{pub_date}" />

<!-- Twitter Card -->
<meta name="twitter:card" content="summary_large_image" />
<meta name="twitter:title" content="{self._escape(title)}" />
<meta name="twitter:description" content="{self._escape(meta_description)}" />

<!-- Canonical -->
<link rel="canonical" href="{canonical_url}" />

<!-- Meta -->
<meta name="description" content="{self._escape(meta_description)}" />
<meta name="keywords" content="{', '.join(keywords)}" />"""

        # Read time estimate
        word_count = task["post_draft"].get("estimated_word_count", 1200)
        read_time = max(1, math.ceil(word_count / 238))

        return {
            "canonical_url": canonical_url,
            "labels": labels,
            "author": author,
            "schema_script": schema_script,
            "og_tags": og_tags,
            "read_time_minutes": read_time,
            "pub_date": pub_date,
            "slug": slug,
        }

    def _escape(self, text: str) -> str:
        return text.replace('"', '&quot;').replace('<', '&lt;').replace('>', '&gt;')


import math  # add to top in real file


# ─────────────────────────────────────────────────────────────────────────────

"""
agents/image_agent.py
Agent 7: Finds and embeds images from free sources (Wikimedia, Unsplash, NASA, WHO).
Falls back to Pollinations.ai for AI-generated images.
"""

import logging
import re
import requests
from utils.gemini_client import call_gemini

logger = logging.getLogger(__name__)

WIKIMEDIA_API = "https://commons.wikimedia.org/w/api.php"
HEADERS = {"User-Agent": "AutonomousBlogger/1.0 (contact@yourblog.com)"}


class ImageAgent:
    def find_images(self, task: dict) -> list:
        """
        Returns list of image dicts: {url, alt, caption, attribution, position}
        """
        genre = task["genre_id"]
        topic = task["topic_label"]
        image_search_query = task["research_brief"].get("suggested_image_search", f"{topic} {genre}")
        title = task["post_draft"]["title"]

        images = []

        # Try Wikimedia Commons first (featured image)
        wm_image = self._search_wikimedia(image_search_query)
        if wm_image:
            wm_image["position"] = "featured"
            images.append(wm_image)
        
        # Try Unsplash for inline image
        unsplash_image = self._get_unsplash(image_search_query)
        if unsplash_image:
            unsplash_image["position"] = "inline-1"
            images.append(unsplash_image)

        # NASA images for science/space content
        if genre in ["science", "environment"] and len(images) < 2:
            nasa_image = self._search_nasa(image_search_query)
            if nasa_image:
                nasa_image["position"] = "inline-2"
                images.append(nasa_image)

        # Fallback to Pollinations.ai
        if not images:
            logger.info("No web images found. Using Pollinations.ai fallback.")
            poll_image = self._get_pollinations_image(title)
            if poll_image:
                poll_image["position"] = "featured"
                images.append(poll_image)

        logger.info(f"Images found: {len(images)}")
        return images[:3]

    def _search_wikimedia(self, query: str) -> dict | None:
        try:
            params = {
                "action": "query",
                "generator": "search",
                "gsrnamespace": "6",  # File namespace
                "gsrsearch": query,
                "gsrlimit": "5",
                "prop": "imageinfo",
                "iiprop": "url|extmetadata",
                "iiurlwidth": "800",
                "format": "json",
            }
            resp = requests.get(WIKIMEDIA_API, params=params, headers=HEADERS, timeout=15)
            data = resp.json()
            pages = data.get("query", {}).get("pages", {})
            
            for page in pages.values():
                info = page.get("imageinfo", [{}])[0]
                url = info.get("thumburl") or info.get("url", "")
                if not url or not url.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
                    continue
                meta = info.get("extmetadata", {})
                author = meta.get("Artist", {}).get("value", "Wikimedia Commons")
                author = re.sub(r'<[^>]+>', '', author)[:80]
                license_name = meta.get("LicenseShortName", {}).get("value", "CC BY-SA")
                return {
                    "url": url,
                    "alt": f"{query} image",
                    "caption": f"Image related to {query}.",
                    "attribution": f"Credit: {author} via Wikimedia Commons ({license_name})",
                    "source": "wikimedia",
                }
        except Exception as e:
            logger.warning(f"Wikimedia search failed: {e}")
        return None

    def _get_unsplash(self, query: str) -> dict | None:
        try:
            # Unsplash source embed (no API key needed for embed URLs)
            safe_query = re.sub(r'[^a-z0-9\s]', '', query.lower())[:50].strip().replace(' ', ',')
            url = f"https://source.unsplash.com/800x450/?{safe_query}"
            # Verify it resolves
            resp = requests.head(url, timeout=10, allow_redirects=True)
            if resp.status_code == 200:
                return {
                    "url": url,
                    "alt": query,
                    "caption": f"Photo via Unsplash.",
                    "attribution": "Photo via <a href='https://unsplash.com'>Unsplash</a>",
                    "source": "unsplash",
                }
        except Exception as e:
            logger.warning(f"Unsplash fetch failed: {e}")
        return None

    def _search_nasa(self, query: str) -> dict | None:
        try:
            resp = requests.get(
                "https://images-api.nasa.gov/search",
                params={"q": query, "media_type": "image", "page_size": 3},
                timeout=15,
            )
            items = resp.json().get("collection", {}).get("items", [])
            for item in items:
                links = item.get("links", [])
                data = item.get("data", [{}])[0]
                for link in links:
                    if link.get("rel") == "preview":
                        return {
                            "url": link["href"],
                            "alt": data.get("title", query),
                            "caption": data.get("description", "")[:120],
                            "attribution": f"Credit: NASA / {data.get('center', '')}",
                            "source": "nasa",
                        }
        except Exception as e:
            logger.warning(f"NASA image search failed: {e}")
        return None

    def _get_pollinations_image(self, prompt: str) -> dict | None:
        try:
            safe_prompt = re.sub(r'[^a-z0-9\s]', '', prompt.lower())[:100].replace(' ', '%20')
            url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width=800&height=450&nologo=true"
            return {
                "url": url,
                "alt": prompt,
                "caption": "AI-generated illustration.",
                "attribution": "Image generated via Pollinations.ai",
                "source": "pollinations",
            }
        except Exception as e:
            logger.warning(f"Pollinations fallback failed: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────

"""
agents/video_agent.py
Agent 8: Video — Decides if a video is necessary, then fetches from YouTube.
[J] Video necessity decision prompt included here.
"""

import logging
import json
import re
import os
import requests
from utils.gemini_client import call_gemini

logger = logging.getLogger(__name__)

YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"


class VideoAgent:
    def decide_and_fetch(self, task: dict) -> dict:
        """
        [J] Returns dict: {needed: bool, reason: str, embed_html: str | None}
        """
        layer = task["layer"]
        genre = task["genre_label"]
        topic = task["topic_label"]
        title = task["post_draft"]["title"]
        video_search_query = task["research_brief"].get("suggested_video_search", title)

        # [J] Video necessity decision prompt
        decision_prompt = f"""You are a content editor deciding whether a YouTube video embed is necessary for a blog post.

POST DETAILS:
- Title: {title}
- Genre: {genre}
- Topic: {topic}
- Content Layer: {layer}

DECISION RULES (apply strictly):
- "how-to-guides": Video IS needed if the process involves physical actions, UI navigation, or complex sequences
- "latest-news": Video is RARELY needed unless it's a video-first story (e.g., press conference)
- "explainers": Video is helpful if the concept is visual or mechanical
- "research-articles": Video is NOT needed; academic readers prefer text
- "opinion-analysis": Video is NOT needed
- "listicles": Video is NOT needed
- "reviews": Video is helpful for product demos only
- "interviews": Video is helpful if it is a filmed interview
- "case-studies": Video is helpful if it includes a demo or walkthrough

RESPOND in JSON only:
{{
  "needed": true or false,
  "reason": "One sentence explaining the decision",
  "search_query": "YouTube search query to find the best video (only if needed=true)"
}}"""

        response_text = call_gemini(decision_prompt, json_mode=True, temperature=0.1)

        try:
            decision = json.loads(response_text)
        except Exception:
            match = re.search(r'\{.*\}', response_text, re.DOTALL)
            decision = json.loads(match.group()) if match else {"needed": False, "reason": "Parse error"}

        logger.info(f"Video decision: needed={decision.get('needed')} — {decision.get('reason')}")

        result = {
            "needed": decision.get("needed", False),
            "reason": decision.get("reason", ""),
            "embed_html": None,
            "video_id": None,
            "video_title": None,
        }

        if decision.get("needed") and YOUTUBE_API_KEY:
            search_query = decision.get("search_query", video_search_query)
            video_data = self._fetch_youtube_video(search_query)
            if video_data:
                result.update(video_data)
                result["embed_html"] = self._build_embed(video_data["video_id"], video_data["video_title"])

        return result

    def _fetch_youtube_video(self, query: str) -> dict | None:
        try:
            resp = requests.get(YOUTUBE_SEARCH_URL, params={
                "key": YOUTUBE_API_KEY,
                "q": query,
                "type": "video",
                "part": "id,snippet",
                "maxResults": 5,
                "order": "relevance",
                "videoDuration": "medium",
                "videoEmbeddable": "true",
                "safeSearch": "strict",
            }, timeout=15)
            items = resp.json().get("items", [])
            if items:
                item = items[0]
                return {
                    "video_id": item["id"]["videoId"],
                    "video_title": item["snippet"]["title"],
                    "channel": item["snippet"]["channelTitle"],
                }
        except Exception as e:
            logger.warning(f"YouTube search failed: {e}")
        return None

    def _build_embed(self, video_id: str, title: str) -> str:
        return f"""<div class="video-embed-wrapper" style="position:relative;padding-bottom:56.25%;height:0;overflow:hidden;">
  <iframe
    src="https://www.youtube.com/embed/{video_id}?rel=0&modestbranding=1"
    title="{title}"
    allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
    allowfullscreen
    style="position:absolute;top:0;left:0;width:100%;height:100%;"
    loading="lazy">
  </iframe>
</div>
<p class="video-caption"><em>Video: {title}</em></p>"""


# ─────────────────────────────────────────────────────────────────────────────

"""
agents/publisher.py
Agent 9: Assembles the final HTML post and publishes via Blogger API v3.
"""

import json
import logging
import os
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
import requests
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

PUBLISHED_POSTS_PATH = Path("logs/published_posts.json")
BLOG_ID = os.environ["BLOGGER_BLOG_ID"]


class PublisherAgent:
    def __init__(self):
        self.service = self._build_blogger_service()

    def _build_blogger_service(self):
        creds_json = os.environ.get("BLOGGER_OAUTH_CREDENTIALS", "{}")
        creds_data = json.loads(creds_json)
        creds = Credentials(
            token=creds_data.get("token"),
            refresh_token=creds_data.get("refresh_token"),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=creds_data.get("client_id"),
            client_secret=creds_data.get("client_secret"),
            scopes=["https://www.googleapis.com/auth/blogger"],
        )
        if creds.expired and creds.refresh_token:
            creds.refresh(GoogleRequest())
        return build("blogger", "v3", credentials=creds)

    def _assemble_html(self, task: dict) -> str:
        """Assemble the complete post HTML from all agent outputs."""
        post_html = task["post_with_citations"]["html_body"]
        seo_data = task["seo_data"]
        images = task["images"]
        video_data = task["video_data"]
        genre_label = task["genre_label"]
        topic_label = task["topic_label"]
        layer_label = task["layer_meta"]["label"]
        layer_color = task["layer_meta"]["color"]
        genre_color = task["genre_color"]
        author = seo_data["author"]
        read_time = seo_data["read_time_minutes"]
        pub_date_display = datetime.utcnow().strftime("%B %d, %Y")

        # Build featured image HTML
        featured_img_html = ""
        inline_img_html = ""
        for img in images:
            img_html = f"""<figure class="post-image">
  <img src="{img['url']}" alt="{img['alt']}" loading="lazy" width="800" height="450" />
  <figcaption>{img['caption']} {img['attribution']}</figcaption>
</figure>"""
            if img["position"] == "featured":
                featured_img_html = img_html
            else:
                inline_img_html += img_html

        # Build video HTML if needed
        video_html = ""
        if video_data.get("needed") and video_data.get("embed_html"):
            video_html = f"""<div class="video-section">
  <h3>Watch: {video_data.get('video_title', 'Related Video')}</h3>
  {video_data['embed_html']}
</div>"""

        # Article meta block
        meta_block = f"""<div class="article-meta">
  <span class="badge genre-badge" style="background:{genre_color}">{genre_label}</span>
  <span class="badge layer-badge" style="background:{layer_color}">{layer_label}</span>
  <span class="meta-author">By {author}</span>
  <span class="meta-date">{pub_date_display}</span>
  <span class="meta-readtime">⏱ {read_time} min read</span>
</div>"""

        # Share buttons
        canonical_url = seo_data["canonical_url"]
        title = task["post_draft"]["title"]
        share_buttons = self._build_share_buttons(canonical_url, title)

        # Disqus embed
        disqus_html = self._build_disqus_embed()

        # Like button (Firebase)
        like_html = self._build_like_button()

        full_html = f"""{meta_block}

{featured_img_html}

{post_html}

{inline_img_html}

{video_html}

{share_buttons}

{like_html}

{disqus_html}

{seo_data['schema_script']}"""

        return full_html

    def _build_share_buttons(self, url: str, title: str) -> str:
        encoded_url = requests.utils.quote(url, safe='')
        encoded_title = requests.utils.quote(title, safe='')
        return f"""<div class="share-section">
  <h3>Share This Article</h3>
  <div class="share-buttons">
    <a href="https://twitter.com/intent/tweet?url={encoded_url}&text={encoded_title}" target="_blank" rel="noopener" class="share-btn share-twitter" aria-label="Share on Twitter">𝕏 Twitter</a>
    <a href="https://www.facebook.com/sharer/sharer.php?u={encoded_url}" target="_blank" rel="noopener" class="share-btn share-facebook" aria-label="Share on Facebook">Facebook</a>
    <a href="https://www.linkedin.com/shareArticle?mini=true&url={encoded_url}&title={encoded_title}" target="_blank" rel="noopener" class="share-btn share-linkedin" aria-label="Share on LinkedIn">LinkedIn</a>
    <a href="https://wa.me/?text={encoded_title}%20{encoded_url}" target="_blank" rel="noopener" class="share-btn share-whatsapp" aria-label="Share on WhatsApp">WhatsApp</a>
    <a href="https://t.me/share/url?url={encoded_url}&text={encoded_title}" target="_blank" rel="noopener" class="share-btn share-telegram" aria-label="Share on Telegram">Telegram</a>
    <a href="https://reddit.com/submit?url={encoded_url}&title={encoded_title}" target="_blank" rel="noopener" class="share-btn share-reddit" aria-label="Share on Reddit">Reddit</a>
    <a href="mailto:?subject={encoded_title}&body=Check%20this%20out%3A%20{encoded_url}" class="share-btn share-email" aria-label="Share via Email">Email</a>
    <button onclick="navigator.clipboard.writeText('{url}');this.textContent='Copied!';setTimeout(()=>this.textContent='Copy Link',2000)" class="share-btn share-copy" aria-label="Copy link">Copy Link</button>
  </div>
</div>"""

    def _build_like_button(self) -> str:
        return """<div class="reaction-section" id="post-reactions">
  <h3>Was this helpful?</h3>
  <div class="reaction-buttons">
    <button class="reaction-btn" data-reaction="like" onclick="handleReaction('like',this)">
      👍 Like <span class="reaction-count" id="count-like">0</span>
    </button>
    <button class="reaction-btn" data-reaction="insightful" onclick="handleReaction('insightful',this)">
      💡 Insightful <span class="reaction-count" id="count-insightful">0</span>
    </button>
    <button class="reaction-btn" data-reaction="helpful" onclick="handleReaction('helpful',this)">
      🙌 Helpful <span class="reaction-count" id="count-helpful">0</span>
    </button>
  </div>
</div>"""

    def _build_disqus_embed(self) -> str:
        disqus_shortname = os.environ.get("DISQUS_SHORTNAME", "yourblog")
        return f"""<div class="comments-section">
  <h2>Comments</h2>
  <div id="disqus_thread"></div>
  <script>
    var disqus_config = function () {{
      this.page.url = window.location.href;
      this.page.identifier = window.location.pathname;
    }};
    (function() {{
      var d = document, s = d.createElement('script');
      s.src = 'https://{disqus_shortname}.disqus.com/embed.js';
      s.setAttribute('data-timestamp', +new Date());
      (d.head || d.body).appendChild(s);
    }})();
  </script>
  <noscript>Please enable JavaScript to view the <a href="https://disqus.com/?ref_noscript">comments powered by Disqus.</a></noscript>
</div>"""

    def publish(self, task: dict) -> dict:
        """Publish the assembled post to Blogger."""
        html_content = self._assemble_html(task)
        seo_data = task["seo_data"]
        labels = seo_data["labels"]
        title = task["post_draft"]["title"]

        # Schedule publish time (stagger posts throughout the day)
        publish_time = (datetime.now(timezone.utc) + timedelta(minutes=5)).strftime(
            "%Y-%m-%dT%H:%M:%S+00:00"
        )

        post_body = {
            "title": title,
            "content": html_content,
            "labels": labels,
            "published": publish_time,
        }

        try:
            result = self.service.posts().insert(
                blogId=BLOG_ID,
                body=post_body,
                isDraft=False,
                fetchImages=False,
            ).execute()

            post_url = result.get("url", "")
            post_id = result.get("id", "")
            logger.info(f"Post published: {post_url}")

            metadata = {
                "post_id": post_id,
                "title": title,
                "url": post_url,
                "genre": task["genre_id"],
                "topic": task["topic_id"],
                "layer": task["layer"],
                "labels": labels,
                "slug": seo_data["slug"],
                "published_at": publish_time,
                "word_count": task["post_draft"].get("estimated_word_count", 0),
                "has_video": task["video_data"].get("needed", False),
                "image_count": len(task.get("images", [])),
                "reference_count": len(task["post_with_citations"].get("references", [])),
            }

            self._append_to_log(metadata)
            return metadata

        except Exception as e:
            logger.error(f"Blogger publish failed: {e}", exc_info=True)
            raise

    def _append_to_log(self, metadata: dict):
        PUBLISHED_POSTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        posts = []
        if PUBLISHED_POSTS_PATH.exists():
            with open(PUBLISHED_POSTS_PATH) as f:
                posts = json.load(f)
        posts.append(metadata)
        with open(PUBLISHED_POSTS_PATH, "w") as f:
            json.dump(posts, f, indent=2)
