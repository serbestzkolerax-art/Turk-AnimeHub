"""Kaynaklar (TürkAnime, AnimeciX, Anizle, Animely, TRAnimeİzle, OpenAnime, AnimeDepo) için facade."""

from .animecix import CixAnime, search_animecix
from .anizle import AnizleAnime, search_anizle
from .animely import AnimelyAnime, search_animely
from .tranime import (
    TRAnimeAnime, TRAnimeEpisode, TRAnimeVideo,
    search_tranime, get_anime_by_slug as get_tranime_anime,
    get_anime_episodes as get_tranime_episodes,
    get_episode_details as get_tranime_episode_details,
    set_session_cookie as set_tranime_cookie
)
from .openani import OpenAniAdapter, OpenAniAnime, search_openani, get_anime_episodes as get_openani_episodes, get_episode_streams as get_openani_streams
from .animedepo import search_animedepo, get_anime_episodes as get_animedepo_episodes
from .tranimaci import search_tranimaci, get_anime_episodes as get_tranimaci_episodes, get_episode_streams as get_tranimaci_streams

# Mevcut sağlayıcılar
PROVIDERS = {
    "animecix": {
        "name": "AnimeciX",
        "adapter": None,
        "enabled": True,
        "priority": 1
    },
    "anizle": {
        "name": "Anizle",
        "adapter": None,
        "enabled": True,
        "priority": 2
    },
    "tranime": {
        "name": "TRAnimeİzle",
        "adapter": None,
        "enabled": True,
        "priority": 3
    },
    "animely": {
        "name": "Animely",
        "adapter": None,
        "enabled": True,
        "priority": 3.5
    },
    "openani": {
        "name": "OpenAnime",
        "adapter": OpenAniAdapter,
        "enabled": True,
        "priority": 4
    },
    "animedepo": {
        "name": "AnimeDepo",
        "adapter": None,
        "enabled": True,
        "priority": 5
    },
    "tranimaci": {
        "name": "Tranimaci",
        "adapter": None,
        "enabled": True,
        "priority": 6
    }
}

def register_provider(name: str, adapter_class, enabled: bool = True, priority: int = 5):
    """Yeni bir anime sağlayıcısı kaydet."""
    PROVIDERS[name] = {
        "name": name,
        "adapter": adapter_class,
        "enabled": enabled,
        "priority": priority
    }

def get_enabled_providers():
    """Etkin sağlayıcıları döndür."""
    return {name: data for name, data in PROVIDERS.items() if data["enabled"]}

def get_provider_by_priority():
    """Öncelik sırasına göre sağlayıcıları döndür."""
    enabled = get_enabled_providers()
    return sorted(enabled.items(), key=lambda x: x[1]["priority"])