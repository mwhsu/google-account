import re
from html.parser import HTMLParser


ROLE_PREFIXES = ("SYSTEM", "USER", "ASSISTANT", "HUMAN", "CLAUDE")
TAG_NAMES = ("system", "instructions", "prompt", "tool_call", "function_call")
SPECIAL_TOKENS = {
    "system": "<|system|>",
    "user": "<|user|>",
    "assistant": "<|assistant|>",
    "im_start": "<|im_start|>",
    "im_end": "<|im_end|>",
}


class _HTMLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"p", "br", "div", "li", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"p", "br", "div", "li", "tr"}:
            self.parts.append("\n")


def strip_html_tags(content: str) -> str:
    parser = _HTMLStripper()
    parser.feed(content)
    text = "".join(parser.parts)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


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
