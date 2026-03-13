"""Instagram client module – authentication, posting, comments, and analytics."""

__all__ = [
    "InstagramAuth",
    "InstagramPoster",
    "CommentMonitor",
    "InstagramAnalytics",
]


def __getattr__(name):
    """Lazy import – instagrapi may not be installed in all environments."""
    if name == "InstagramAuth":
        from src.instagram.auth import InstagramAuth
        return InstagramAuth
    if name == "InstagramPoster":
        from src.instagram.poster import InstagramPoster
        return InstagramPoster
    if name == "CommentMonitor":
        from src.instagram.commenter import CommentMonitor
        return CommentMonitor
    if name == "InstagramAnalytics":
        from src.instagram.analytics import InstagramAnalytics
        return InstagramAnalytics
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
