from src.pagination import format_truncation_indicator, paginate


def test_paginate_single_page():
    """All items fit in one page, no truncation."""
    def fetch(token):
        return [1, 2, 3], None

    items, truncated = paginate(fetch, limit=10)
    assert items == [1, 2, 3]
    assert truncated is False


def test_paginate_multi_page():
    """Items span multiple pages."""
    pages = {
        None: ([1, 2], "page2"),
        "page2": ([3, 4], "page3"),
        "page3": ([5], None),
    }

    def fetch(token):
        return pages[token]

    items, truncated = paginate(fetch, limit=10)
    assert items == [1, 2, 3, 4, 5]
    assert truncated is False


def test_paginate_truncated_at_limit():
    """More items available than limit allows."""
    pages = {
        None: ([1, 2, 3], "page2"),
        "page2": ([4, 5, 6], "page3"),
    }

    def fetch(token):
        return pages[token]

    items, truncated = paginate(fetch, limit=5)
    assert items == [1, 2, 3, 4, 5]
    assert truncated is True


def test_paginate_exact_limit():
    """Exactly limit items with more pages available."""
    pages = {
        None: ([1, 2, 3], "page2"),
    }

    def fetch(token):
        return pages[token]

    items, truncated = paginate(fetch, limit=3)
    assert items == [1, 2, 3]
    assert truncated is True


def test_paginate_empty():
    """No items returned."""
    def fetch(token):
        return [], None

    items, truncated = paginate(fetch, limit=10)
    assert items == []
    assert truncated is False


def test_format_truncation_indicator_truncated():
    msg = format_truncation_indicator(10, truncated=True)
    assert "showing 10 results" in msg
    assert "--limit" in msg


def test_format_truncation_indicator_not_truncated():
    msg = format_truncation_indicator(5, truncated=False)
    assert msg == ""
