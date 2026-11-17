"""Guardrails around model input and output.

Pure functions, kept free of app.core.config imports so they stay testable
without a .env.
"""

import re

BLOCKED_ANSWER = (
    "I can't help with that request. I can answer questions about employment "
    "policy, such as leave, sick pay, working hours, redundancy and disciplinary procedures."
)

PROMPT_TAGS = re.compile(r"</?\s*(question|answer|policy_context)\s*>", re.IGNORECASE)
MARKDOWN_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
LABEL_NOISE = re.compile(r"[`'\"*\s]")


def neutralise_prompt_tags(text: str) -> str:
    """Remove the delimiter tags our prompts use, so user text cannot close a section early."""
    return PROMPT_TAGS.sub("", text or "")


def strip_markdown_images(text: str) -> str:
    """Drop markdown images. A rendered image can send data to another server, and answers never need one."""
    return MARKDOWN_IMAGE.sub("", text or "").strip()


def is_content_filtered(exc: Exception) -> bool:
    """True when Azure OpenAI refused the request because its content filter flagged the prompt."""
    text = f"{type(exc).__name__} {exc}".lower()
    return "content_filter" in text or "content management policy" in text


def normalise_label(text: str, valid: tuple, default: str) -> str:
    """Map a model reply to one of the valid labels, or the default when it does not clearly name one."""
    cleaned = LABEL_NOISE.sub("", text or "").lower()
    if cleaned in valid:
        return cleaned
    found = [label for label in valid if label in cleaned]
    return found[0] if len(found) == 1 else default


def normalise_review(text: str) -> str:
    """Approve only an exact 'approved' reply; anything else is a rejection."""
    return "approved" if LABEL_NOISE.sub("", text or "").lower() == "approved" else "rejected"
