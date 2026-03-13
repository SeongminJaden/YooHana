"""Trend analyzer module – scrape, analyse, and replicate trending content."""

__all__ = [
    "TrendScraper",
    "MediaAnalyzer",
    "TrendDetector",
    "ReelCreator",
]


def __getattr__(name: str):
    """Lazy imports so heavy dependencies are only loaded when needed."""
    if name == "TrendScraper":
        from src.trend_analyzer.scraper import TrendScraper
        return TrendScraper
    if name == "MediaAnalyzer":
        from src.trend_analyzer.media_analyzer import MediaAnalyzer
        return MediaAnalyzer
    if name == "TrendDetector":
        from src.trend_analyzer.trend_detector import TrendDetector
        return TrendDetector
    if name == "ReelCreator":
        from src.trend_analyzer.reel_creator import ReelCreator
        return ReelCreator
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
