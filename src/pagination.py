from typing import Any, Callable


def paginate(
    fetch_page: Callable[[str | None], tuple[list[Any], str | None]],
    limit: int,
) -> tuple[list[Any], bool]:
    """Generic paginator for Google API list operations.

    Args:
        fetch_page: Callable that takes an optional page_token and returns
                    (items, next_page_token). Each API module provides its own
                    closure that handles API-specific token names and response shapes.
        limit: Maximum number of items to return.

    Returns:
        Tuple of (items, truncated) where truncated indicates more results exist.
    """
    items: list[Any] = []
    page_token: str | None = None
    next_token: str | None = None
    truncated = False

    while len(items) < limit:
        page_items, next_token = fetch_page(page_token)
        items.extend(page_items)
        if not next_token:
            break
        page_token = next_token

    if len(items) > limit:
        items = items[:limit]
        truncated = True
    elif next_token:
        truncated = True

    return items, truncated


def format_truncation_indicator(shown: int, truncated: bool) -> str:
    """Returns a truncation indicator string for CLI output."""
    if truncated:
        return f"(showing {shown} results — use --limit to see more)"
    return ""
