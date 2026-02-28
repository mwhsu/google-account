import re

from bs4 import BeautifulSoup


ROLE_PREFIXES = ("SYSTEM", "USER", "ASSISTANT", "HUMAN", "CLAUDE")
TAG_NAMES = ("system", "instructions", "prompt", "tool_call", "function_call")
SPECIAL_TOKENS = {
    "system": "<|system|>",
    "user": "<|user|>",
    "assistant": "<|assistant|>",
    "im_start": "<|im_start|>",
    "im_end": "<|im_end|>",
}


def strip_html_tags(content: str) -> str:
    soup = BeautifulSoup(content, "html.parser")
    return soup.get_text("\n")


def neutralize_injections(content: str) -> str:
    sanitized = content
    for role in ROLE_PREFIXES:
        pattern = re.compile(rf"\b{role}\s*:", re.IGNORECASE)
        sanitized = pattern.sub(f"[REMOVED_ROLE_PREFIX: {role}]", sanitized)
    for tag_name in TAG_NAMES:
        pattern = re.compile(rf"</?\s*{tag_name}\s*>", re.IGNORECASE)
        sanitized = pattern.sub(f"[REMOVED_TAG: {tag_name}]", sanitized)
    for token_name, token_value in SPECIAL_TOKENS.items():
        pattern = re.compile(re.escape(token_value), re.IGNORECASE)
        sanitized = pattern.sub(f"[REMOVED_TOKEN: {token_name}]", sanitized)
    return sanitized


def truncate_and_wrap(content: str, content_type: str, max_chars: int) -> str:
    truncated = content[:max_chars]
    return f"[BEGIN {content_type}]\n{truncated}\n[END {content_type}]"


def sanitize(
    content: str,
    content_type: str,
    max_chars: int,
    strip_html: bool = True,
    neutralize: bool = True,
) -> str:
    sanitized = content
    if strip_html:
        sanitized = strip_html_tags(sanitized)
    if neutralize:
        sanitized = neutralize_injections(sanitized)
    return truncate_and_wrap(sanitized, content_type, max_chars)
