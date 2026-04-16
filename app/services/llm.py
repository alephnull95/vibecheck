"""
services/llm.py – LLM façade: vibe profiling, query expansion, embeddings.

Supports OpenAI (default) and Google Gemini. The provider is chosen at
startup via config.LLM_PROVIDER. Embeddings always use OpenAI
text-embedding-3-small regardless of the chat provider, since pgvector
stores 1536-dim vectors.
"""

import json
import re
from typing import Optional

import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import get_settings

logger = structlog.get_logger(__name__)

# ── Lazy client initialisation ───────────────────────────────────────────────


def _openai_client():
    import openai  # noqa: PLC0415
    return openai.OpenAI(api_key=get_settings().openai_api_key)


def _gemini_model(model_name: str):
    import google.generativeai as genai  # noqa: PLC0415
    genai.configure(api_key=get_settings().gemini_api_key)
    return genai.GenerativeModel(model_name)


# ── Embedding ────────────────────────────────────────────────────────────────

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def embed_text(text: str) -> list[float]:
    """
    Return a 1536-dim embedding vector for *text* using OpenAI
    text-embedding-3-small. Embeddings always use OpenAI regardless of the
    configured chat LLM provider.
    """
    s = get_settings()
    client = _openai_client()
    response = client.embeddings.create(
        model=s.embedding_model,
        input=text,
        dimensions=s.embedding_dimensions,
    )
    return response.data[0].embedding


# ── System prompts ───────────────────────────────────────────────────────────

_VIBE_SYSTEM_PROMPT = """You are a film critic and cultural analyst specialising in mood, atmosphere, and sensory experience.
Given a movie title, year, overview, and genres, produce a structured Vibe Profile as valid JSON.

Return ONLY the JSON object — no markdown fences, no prose.

Schema:
{
  "atmosphere": "<2-3 sentences describing the sensory, visual, and spatial feel of the film>",
  "themes":     "<2-3 sentences on the socio-political, philosophical, or psychological themes>",
  "mood":       "<1-2 sentences on the dominant emotional impact on the viewer>",
  "keywords":   ["<5-10 single words or short phrases capturing the vibe>"]
}"""

_EXPANSION_SYSTEM_PROMPT = """You are an expert film curator. Your task is to expand an abstract, 
possibly poetic or emotional user query into a rich set of descriptive terms that capture the 
intended cinematic vibe.

Return ONLY a single paragraph of descriptive prose (150-250 words) — no bullet lists, no JSON.
Write as if describing a feeling, atmosphere, or setting: sensory details, textures, colours, 
emotional tones, themes. Avoid mentioning specific film titles."""


# ── Vibe profiling ────────────────────────────────────────────────────────────

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def generate_vibe_profile(
    title: str,
    year: Optional[int],
    overview: Optional[str],
    genres: Optional[list[str]],
) -> dict:
    """
    Call the configured LLM to generate a structured vibe profile for a film.
    Returns a dict with keys: atmosphere, themes, mood, keywords.
    """
    user_content = (
        f"Title: {title} ({year or 'unknown year'})\n"
        f"Genres: {', '.join(genres or []) or 'Unknown'}\n"
        f"Overview: {overview or 'No overview available.'}"
    )

    raw = _chat(system=_VIBE_SYSTEM_PROMPT, user=user_content)
    return _parse_json_response(raw, context=f"vibe_profile:{title}")


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def expand_query(
    query: str,
    liked_examples: Optional[list[dict]] = None,
) -> str:
    """
    Expand an abstract user query into rich descriptive prose suitable for
    embedding and vector retrieval.

    If *liked_examples* is provided (list of vibe_profile dicts from the
    user's thumbs-up feedback), they are injected as few-shot context so the
    expansion respects the user's personal taste.
    """
    few_shot_block = ""
    if liked_examples:
        examples_text = "\n\n".join(
            f"Example {i + 1}:\nAtmosphere: {ex.get('atmosphere', '')}\n"
            f"Themes: {ex.get('themes', '')}\nMood: {ex.get('mood', '')}"
            for i, ex in enumerate(liked_examples[:get_settings().feedback_few_shot_count])
        )
        few_shot_block = (
            "\n\nThe user has previously liked films with these vibes. "
            "Calibrate the expansion to lean toward a similar sensibility:\n\n"
            + examples_text
        )

    system = _EXPANSION_SYSTEM_PROMPT + few_shot_block
    return _chat(system=system, user=f'Expand this vibe query: "{query}"').strip()


# ── Private helpers ───────────────────────────────────────────────────────────

def _chat(system: str, user: str) -> str:
    """Dispatch to the configured LLM provider."""
    if get_settings().llm_provider == "openai":
        return _openai_chat(system, user)
    return _gemini_chat(system, user)


def _openai_chat(system: str, user: str) -> str:
    client = _openai_client()
    response = client.chat.completions.create(
        model=get_settings().openai_chat_model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.7,
        max_tokens=800,
    )
    return response.choices[0].message.content or ""


def _gemini_chat(system: str, user: str) -> str:
    model = _gemini_model(get_settings().gemini_chat_model)
    # Gemini doesn't have a separate system role in the basic API – prepend it.
    prompt = f"{system}\n\n{user}"
    response = model.generate_content(prompt)
    return response.text or ""


def _parse_json_response(raw: str, context: str = "") -> dict:
    """
    Attempt to parse the LLM response as JSON.
    Strips markdown code fences if present, then falls back to a best-effort
    regex extraction so a single malformed response doesn't kill a batch job.
    """
    text = raw.strip()
    # Strip ```json ... ``` fences
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning("LLM returned non-JSON; falling back to empty profile", context=context, raw=raw[:200])
        return {"atmosphere": raw[:300], "themes": "", "mood": "", "keywords": []}
