"""
firebase_client.py — Firebase Realtime Database wrapper for post like/reaction counts.

Uses Firebase Admin SDK (server-side) for:
- Initializing per-post like counters when a post is published
- Reading current like counts for reporting
- The actual like/unlike logic runs client-side in the Blogger template JS

Firebase Spark (free) plan limits:
- 1 GB storage
- 10 GB/month download
- 100 simultaneous connections

Data structure in Firebase:
  /likes/{post_id}/
    total: int
    reactions:
      like: int
      insightful: int
      helpful: int
"""

import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Firebase Admin SDK — imported lazily to allow graceful degradation
_firebase_initialized = False
_db = None


def _init_firebase():
    """
    Initialize Firebase Admin SDK using the service account JSON stored
    in the FIREBASE_SERVICE_ACCOUNT_JSON GitHub secret.
    Safe to call multiple times — initializes only once.
    """
    global _firebase_initialized, _db

    if _firebase_initialized:
        return _db

    try:
        import firebase_admin
        from firebase_admin import credentials, db

        from config.settings import Secrets

        if not Secrets.FIREBASE_SERVICE_ACCOUNT_JSON:
            logger.warning("FIREBASE_SERVICE_ACCOUNT_JSON secret not set. Firebase disabled.")
            return None

        if not Secrets.FIREBASE_DATABASE_URL:
            logger.warning("FIREBASE_DATABASE_URL secret not set. Firebase disabled.")
            return None

        # Parse the service account JSON from the secret
        service_account_info = json.loads(Secrets.FIREBASE_SERVICE_ACCOUNT_JSON)
        cred = credentials.Certificate(service_account_info)

        # Only initialize if not already done (handles re-imports)
        if not firebase_admin._apps:
            firebase_admin.initialize_app(cred, {
                "databaseURL": Secrets.FIREBASE_DATABASE_URL
            })

        _db = db
        _firebase_initialized = True
        logger.info("Firebase Admin SDK initialized successfully.")
        return _db

    except ImportError:
        logger.error("firebase-admin package not installed. Run: pip install firebase-admin")
        return None
    except Exception as e:
        logger.error(f"Firebase initialization failed: {e}")
        return None


class FirebaseClient:
    """
    Manages like/reaction counters in Firebase Realtime Database.
    Designed to be called by Agent 9 (Publisher) when a post goes live.
    """

    def __init__(self):
        self.db = _init_firebase()

    @property
    def available(self) -> bool:
        """Check if Firebase is properly initialized."""
        return self.db is not None

    def initialize_post_counter(self, post_id: str, post_url: str, post_title: str) -> bool:
        """
        Create the initial like counter entry for a newly published post.
        Called by Agent 9 immediately after a post is published.

        Args:
            post_id: Blogger post ID (numeric string)
            post_url: Full URL of the published post
            post_title: Post title for reference

        Returns:
            True if successful, False if Firebase unavailable
        """
        if not self.available:
            logger.warning(f"Firebase unavailable — skipping counter init for post {post_id}")
            return False

        try:
            ref = self.db.reference(f"/likes/{post_id}")

            # Only create if it doesn't already exist
            existing = ref.get()
            if existing:
                logger.debug(f"Like counter already exists for post {post_id}")
                return True

            ref.set({
                "total": 0,
                "post_url": post_url,
                "post_title": post_title[:100],  # Truncate for storage efficiency
                "reactions": {
                    "like": 0,
                    "insightful": 0,
                    "helpful": 0,
                },
                "created_at": {".sv": "timestamp"},  # Firebase server timestamp
            })

            logger.info(f"Like counter initialized for post {post_id}: {post_title[:50]}")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize like counter for post {post_id}: {e}")
            return False

    def get_post_likes(self, post_id: str) -> dict:
        """
        Read the current like count for a post.

        Returns:
            Dict with 'total' and 'reactions' keys, or empty dict on failure
        """
        if not self.available:
            return {}

        try:
            ref = self.db.reference(f"/likes/{post_id}")
            data = ref.get()
            return data if data else {"total": 0, "reactions": {}}
        except Exception as e:
            logger.error(f"Failed to get likes for post {post_id}: {e}")
            return {}

    def get_all_post_likes(self) -> dict:
        """
        Read all post like counts — used by Self-Improvement Agent
        to correlate engagement with content types.

        Returns:
            Dict keyed by post_id
        """
        if not self.available:
            return {}

        try:
            ref = self.db.reference("/likes")
            return ref.get() or {}
        except Exception as e:
            logger.error(f"Failed to fetch all like counts: {e}")
            return {}

    def get_top_posts_by_likes(self, n: int = 10) -> list[dict]:
        """
        Return the top N posts sorted by total likes.
        Used by Self-Improvement Agent for performance analysis.
        """
        all_likes = self.get_all_post_likes()
        if not all_likes:
            return []

        posts = []
        for post_id, data in all_likes.items():
            if isinstance(data, dict):
                posts.append({
                    "post_id": post_id,
                    "total_likes": data.get("total", 0),
                    "post_title": data.get("post_title", ""),
                    "post_url": data.get("post_url", ""),
                    "reactions": data.get("reactions", {}),
                })

        posts.sort(key=lambda x: x["total_likes"], reverse=True)
        return posts[:n]


# ── Client-side Firebase JS for Blogger Template ─────────────────────────────
# This JS snippet is embedded in the Blogger XML template.
# It handles real-time like/reaction interactions in the browser.

FIREBASE_JS_SNIPPET = """
<!-- Firebase Like System -->
<script type="module">
  // Firebase SDK (loaded from CDN — free)
  import { initializeApp } from 'https://www.gstatic.com/firebasejs/10.12.0/firebase-app.js';
  import { getDatabase, ref, runTransaction, onValue, get }
    from 'https://www.gstatic.com/firebasejs/10.12.0/firebase-database.js';

  const firebaseConfig = {
    databaseURL: "__FIREBASE_DATABASE_URL__",
    // Note: projectId, apiKey etc. needed for client SDK
    // These are PUBLIC client keys — safe to embed
    apiKey: "__FIREBASE_API_KEY__",
    authDomain: "__FIREBASE_AUTH_DOMAIN__",
    projectId: "__FIREBASE_PROJECT_ID__",
    storageBucket: "__FIREBASE_STORAGE_BUCKET__",
    messagingSenderId: "__FIREBASE_MESSAGING_SENDER_ID__",
    appId: "__FIREBASE_APP_ID__"
  };

  const app = initializeApp(firebaseConfig);
  const db = getDatabase(app);

  // Get post ID from the current page's Blogger data
  const postId = document.querySelector('[data-post-id]')?.dataset?.postId;
  if (!postId) return;

  const likesRef = ref(db, `likes/${postId}`);
  const userKey = `liked_${postId}`;

  // ── Read current counts on page load ──────────────────────────────────────
  onValue(likesRef, (snapshot) => {
    const data = snapshot.val() || {};
    const total = data.total || 0;
    const reactions = data.reactions || {};

    // Update total display
    const totalEl = document.getElementById('like-count-total');
    if (totalEl) totalEl.textContent = total;

    // Update individual reaction counts
    ['like', 'insightful', 'helpful'].forEach(type => {
      const el = document.getElementById(`reaction-count-${type}`);
      if (el) el.textContent = reactions[type] || 0;
    });
  });

  // ── Like button click handler ─────────────────────────────────────────────
  window.handleReaction = function(reactionType) {
    const alreadyReacted = localStorage.getItem(`${userKey}_${reactionType}`);

    if (alreadyReacted) {
      // Unlike: remove reaction
      runTransaction(ref(db, `likes/${postId}/total`), (count) => (count || 0) - 1);
      runTransaction(ref(db, `likes/${postId}/reactions/${reactionType}`), (count) => Math.max((count || 0) - 1, 0));
      localStorage.removeItem(`${userKey}_${reactionType}`);
      document.getElementById(`btn-${reactionType}`)?.classList.remove('reacted');
    } else {
      // Like: add reaction
      runTransaction(ref(db, `likes/${postId}/total`), (count) => (count || 0) + 1);
      runTransaction(ref(db, `likes/${postId}/reactions/${reactionType}`), (count) => (count || 0) + 1);
      localStorage.setItem(`${userKey}_${reactionType}`, '1');
      document.getElementById(`btn-${reactionType}`)?.classList.add('reacted');

      // Animate
      const btn = document.getElementById(`btn-${reactionType}`);
      if (btn) {
        btn.classList.add('pop-animation');
        setTimeout(() => btn.classList.remove('pop-animation'), 400);
      }
    }
  };

  // ── Restore reaction states from localStorage on load ────────────────────
  ['like', 'insightful', 'helpful'].forEach(type => {
    if (localStorage.getItem(`${userKey}_${type}`)) {
      document.getElementById(`btn-${type}`)?.classList.add('reacted');
    }
  });
</script>
"""
