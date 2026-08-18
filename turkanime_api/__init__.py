"""TurkAnimu API - Anime streaming and downloading toolkit."""

from .objects import Anime, Bolum, Video
from .bypass import session
from . import animecix
from . import animedepo

__all__ = ["Anime", "Bolum", "Video", "animecix", "animedepo"]