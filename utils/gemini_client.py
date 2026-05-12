"""
utils/gemini_client.py
Gemini API wrapper with rate limiting, quota tracking, and fallback logic.
"""

import os
import json
import time
import random
import logging
from datetime import date
from pathlib import Path
import google.generativeai as genai

logger = logging.getLogger(__name__)

QUOTA_STATE_PATH = Path("config/quota_state.json")

# Daily free-tier limits (conservative estimates)
QUOTA_LIMITS = {
    "gemini-2.5-flash": {"rpm": 10, "rpd": 500, "tpd": 1_000_000},
    "gemini-1.5-flash": {"rpm": 15, "rpd": 1500, "tpd": 1_000_000},
}

PRIMARY_MODEL = "gemini-2.5-flash-preview-05-20"
FALLBACK_MODEL = "gemini-1.5-flash"


def _load_quota_state() -> dict:
    today = str(date.today())
    if QUOTA_STATE_PATH.exists():
        with open(QUOTA_STATE_PATH) as f:
            state = json.load(f)
        if state.get("date") != today:
            state = {"date": today, "gemini-2.5-flash": 0, "gemini-1.5-flash": 0}
    else:
        state = {"date": today, "gemini-2.5-flash": 0, "gemini-1.5-flash": 0}
    return state


def _save_quota_state(state: dict):
    QUOTA_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(QUOTA_STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)


def _increment_quota(model_key: str):
    state = _load_quota_state()
    state[model_key] = state.get(model_key, 0) + 1
    _save_quota_state(state)


def _quota_exhausted(model_key: str) -> bool:
    state = _load_quota_state()
    limit = QUOTA_LIMITS.get(model_key, {}).get("rpd", 500)
    return state.get(model_key, 0) >= limit


def call_gemini(
    prompt: str,
    system_instruction: str = "",
    max_tokens: int = 8192,
    temperature: float = 0.7,
    max_retries: int = 5,
    json_mode: bool = False,
) -> str:
    """
    Call Gemini API with automatic model fallback and exponential backoff.
    Returns the text response string.
    """
    genai.configure(api_key=os.environ["GEMINI_API_KEY"])

    # Select model based on quota
    if _quota_exhausted("gemini-2.5-flash"):
        logger.warning("Gemini 2.5 Flash quota exhausted. Falling back to 1.5 Flash.")
        model_name = FALLBACK_MODEL
        quota_key = "gemini-1.5-flash"
    else:
        model_name = PRIMARY_MODEL
        quota_key = "gemini-2.5-flash"

    if _quota_exhausted(quota_key):
        raise RuntimeError("All Gemini quotas exhausted for today. Aborting.")

    generation_config = genai.GenerationConfig(
        max_output_tokens=max_tokens,
        temperature=temperature,
    )

    if json_mode:
        generation_config = genai.GenerationConfig(
            max_output_tokens=max_tokens,
            temperature=temperature,
            response_mime_type="application/json",
        )

    model = genai.GenerativeModel(
        model_name=model_name,
        system_instruction=system_instruction if system_instruction else None,
        generation_config=generation_config,
    )

    for attempt in range(max_retries):
        try:
            response = model.generate_content(prompt)
            _increment_quota(quota_key)
            logger.info(f"Gemini call success [{model_name}] attempt {attempt+1}")
            return response.text

        except Exception as e:
            error_str = str(e).lower()
            if "quota" in error_str or "429" in error_str:
                # Mark this model quota as exhausted
                state = _load_quota_state()
                state[quota_key] = QUOTA_LIMITS[quota_key]["rpd"]
                _save_quota_state(state)

                if quota_key == "gemini-2.5-flash":
                    logger.warning("Switching to fallback model due to quota error.")
                    model_name = FALLBACK_MODEL
                    quota_key = "gemini-1.5-flash"
                    model = genai.GenerativeModel(
                        model_name=model_name,
                        system_instruction=system_instruction or None,
                        generation_config=generation_config,
                    )
                else:
                    raise RuntimeError("All Gemini quotas exhausted.") from e

            # Exponential backoff with jitter
            wait = (2 ** attempt) + random.uniform(0, 1)
            logger.warning(f"Gemini attempt {attempt+1} failed: {e}. Retrying in {wait:.1f}s")
            time.sleep(min(wait, 60))

    raise RuntimeError(f"Gemini call failed after {max_retries} retries.")
