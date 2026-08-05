""" Multi-Source Provider Architecture for TurkAnime Downloader """
import re
from curl_cffi import requests


class BaseProvider:
    """Base provider class that provides common functionality."""

    def __init__(self, base_url):
        self.base_url = base_url.rstrip('/')
        if not hasattr(self, 'session'):
            self.session = None  # Lazy init in subclasses using bypass.fetch()


def get_anime_info(slug: str) -> dict | None:
    """Fetch anime info for all providers. Returns merged data."""

    results = {}

    try:
        from .turkanime import Anime as TurkAnime
        tani = TurkAnime(slug)
        results['turkanime'] = {'status': 'ok'}  # Basic placeholder
    except Exception as e:
        pass

    return results


def get_episode_videos(anime_slug: str, episode_slug: str):
    """Get all videos from a specific episode across all providers."""

    videos = []

    try:
        # Try TurkAnime main site first (existing)
        from . import bypass
        from .objects import Video as BaseVideo

        tani_src = bypass.fetch(f'/anime/{anime_slug}') if hasattr(bypass, 'fetch') else ""
