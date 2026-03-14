"""Instagram client module – browser-based posting, comments, and analytics."""

__all__ = [
    "BrowserPoster",
    "BrowserCommenter",
    "InstagramAnalytics",
]


def __getattr__(name):
    """Lazy import to avoid heavy dependencies at module level."""
    if name == "BrowserPoster":
        from src.instagram.browser_poster import BrowserPoster
        return BrowserPoster
    if name == "BrowserCommenter":
        from src.instagram.commenter import BrowserCommenter
        return BrowserCommenter
    if name == "InstagramAnalytics":
        from src.instagram.analytics import InstagramAnalytics
        return InstagramAnalytics
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
