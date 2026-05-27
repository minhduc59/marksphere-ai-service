"""Classify free-form user feedback into regeneration targets.

Given the user's rejection feedback and the current post, decide whether
the caption/hashtags/CTA need to be regenerated, the image needs to be
regenerated, or both. The output is consumed by `revision_runner` to
decide which post-generator nodes to re-run.
"""

import json

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from app.clients.openai_client import get_review_llm

logger = structlog.get_logger()


CLASSIFIER_SYSTEM_PROMPT = """\
You are a router for a social-media post regeneration pipeline. The user has
rejected a generated TikTok post with free-form feedback. Decide what needs to
be regenerated.

Return STRICT JSON only — no prose, no markdown — with this exact shape:
{
  "regenerate_content": <boolean>,
  "regenerate_image": <boolean>,
  "reasoning": "<one short sentence explaining the routing decision>"
}

Rules:
- "regenerate_content" covers caption, hashtags, hook, and CTA.
- "regenerate_image" covers the image_prompt and the rendered image.
- At least ONE of the two booleans MUST be true. If the feedback is generic
  ("not good", "redo this"), default to BOTH true.
- If feedback only mentions wording/tone/copy/hashtags/CTA/hook → content only.
- If feedback only mentions visuals/photo/picture/colors/composition/style → image only.
- If feedback covers both, or asks for a full redo → both true.

Examples:

Feedback: "Make the caption shorter and punchier"
→ {"regenerate_content": true, "regenerate_image": false, "reasoning": "Wording/tone only."}

Feedback: "The image is too dark, needs more vibrant colors"
→ {"regenerate_content": false, "regenerate_image": true, "reasoning": "Visual-only critique."}

Feedback: "Rewrite the hook and use a totally different photo style"
→ {"regenerate_content": true, "regenerate_image": true, "reasoning": "Both text and visual changes requested."}

Feedback: "Not good, try again"
→ {"regenerate_content": true, "regenerate_image": true, "reasoning": "Generic rejection — redo everything."}
"""


def _parse_json_response(content: str) -> dict:
    """Extract JSON from an LLM response, tolerating markdown fences."""
    text = content.strip()
    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0]
    elif "```" in text:
        text = text.split("```", 1)[1].split("```", 1)[0]
    return json.loads(text.strip())


def _safe_default(reason: str) -> dict:
    """Conservative fallback when the classifier output is unusable."""
    return {
        "regenerate_content": True,
        "regenerate_image": False,
        "reasoning": f"Fallback: {reason}",
    }


async def classify_feedback(feedback: str, post: dict) -> dict:
    """Ask the LLM to decide what to regenerate based on user feedback.

    Args:
        feedback: Free-form user feedback text (from the review request).
        post: The current ContentPost as a dict — used to give the classifier
              context about what's being critiqued. Keys: caption,
              image_prompt, hashtags, cta.

    Returns:
        Dict with keys ``regenerate_content`` (bool), ``regenerate_image``
        (bool), and ``reasoning`` (str). On any error returns the
        content-only fallback.
    """
    feedback_text = (feedback or "").strip()
    if not feedback_text:
        return _safe_default("empty feedback")

    image_prompt = post.get("image_prompt")
    image_prompt_text = (
        json.dumps(image_prompt, default=str)[:600]
        if image_prompt
        else "(none)"
    )
    user_payload = {
        "user_feedback": feedback_text,
        "current_post": {
            "caption": (post.get("caption") or "")[:600],
            "hashtags": post.get("hashtags") or [],
            "cta": post.get("cta") or "",
            "image_prompt_summary": image_prompt_text,
        },
    }

    llm = get_review_llm()
    try:
        response = await llm.ainvoke(
            [
                SystemMessage(content=CLASSIFIER_SYSTEM_PROMPT),
                HumanMessage(content=json.dumps(user_payload, default=str)),
            ]
        )
        parsed = _parse_json_response(response.content)
    except json.JSONDecodeError as exc:
        logger.warning("feedback_classifier: unparsable JSON", error=str(exc))
        return _safe_default("unparsable LLM output")
    except Exception as exc:  # noqa: BLE001 — defensive: LLM call may fail
        logger.error("feedback_classifier: LLM call failed", error=str(exc))
        return _safe_default("LLM call failed")

    content_flag = bool(parsed.get("regenerate_content"))
    image_flag = bool(parsed.get("regenerate_image"))

    # Invariant: at least one target must be true. If the classifier returns
    # both false, treat it as generic rejection → redo both.
    if not content_flag and not image_flag:
        logger.warning(
            "feedback_classifier: both targets false, defaulting to both true",
            raw=parsed,
        )
        content_flag = True
        image_flag = True

    result = {
        "regenerate_content": content_flag,
        "regenerate_image": image_flag,
        "reasoning": str(parsed.get("reasoning") or "")[:300],
    }
    logger.info(
        "feedback_classifier: classified",
        targets=result,
        feedback_preview=feedback_text[:120],
    )
    return result
