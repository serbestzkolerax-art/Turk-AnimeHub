"""Unified provider chain using the sources package."""
from typing import List, Tuple, Dict, Any, Optional
from . import tranime, anizle, animely, openani, animecix, animedepo, tranimaci
from . import PROVIDERS, get_provider_by_priority

# All live providers (TRAnime re‑enabled) + AnimeDepo + Tranimaci
SEARCH_ORDER = ["animecix", "tranime", "openani", "animedepo", "tranimaci"]


def search_all(query: str, limit: int = 10) -> List[Tuple[str, str]]:
    results = []
    seen = set()
    import concurrent.futures

    def _do_search(name):
        try:
            if name == "tranime":
                return name, tranime.search_tranime(query)[:limit]
            elif name == "anizle":
                return name, anizle.search_anizle(query)[:limit]
            elif name == "animely":
                return name, animely.search_animely(query, limit=limit)
            elif name == "openani":
                return name, openani.search_openani(query, limit=limit)
            elif name == "animedepo":
                return name, animedepo.search_animedepo(query, limit=limit)
            elif name == "animecix":
                return name, animecix.search_animecix(query)[:limit]
            elif name == "tranimaci":
                return name, tranimaci.search_tranimaci(query, limit=limit)
        except Exception as e:
            print(f"[chain] search error for {name}: {e}")
        return name, []

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(SEARCH_ORDER)) as executor:
        futures = {executor.submit(_do_search, name): name for name in SEARCH_ORDER}
        for future in concurrent.futures.as_completed(futures):
            name, items = future.result()
            for slug, title in items:
                full = f"{name}:{slug}"
                if full not in seen:
                    seen.add(full)
                    results.append((full, title))

    return results


def get_anime_details(full_slug: str) -> Optional[Dict[str, Any]]:
    prefix, slug = full_slug.split(":", 1)
    if prefix not in PROVIDERS:
        return None

    try:
        if prefix == "tranime":
            anime = tranime.get_anime_by_slug(slug)
            if anime:
                episodes = [(f"tranime:{ep.slug}", ep.title) for ep in anime.episodes]
                return {"title": anime.title, "poster": anime.poster, "summary": "", "episodes": episodes}
        elif prefix == "anizle":
            episode_data = anizle.get_anime_episodes(slug)
            if not episode_data:
                return None
            anime = anizle.get_anime_details(slug)
            title = anime.title if anime else slug.replace("-", " ").title()
            poster = anime.poster_url if anime else ""
            summary = anime.summary if anime else ""
            episodes = [(f"anizle:{url}", ep_title) for url, ep_title in episode_data]
            return {
                "title": title,
                "poster": poster,
                "summary": summary,
                "episodes": episodes
            }
        elif prefix == "animely":
            anime = animely.get_anime_by_slug(slug)
            if anime:
                episodes = [(f"animely:{slug}::{ep.episode_number}", ep.title) for ep in anime.episodes]
                return {"title": anime.name, "poster": anime.poster, "summary": "", "episodes": episodes}
        elif prefix == "openani":
            try:
                adapter = openani.OpenAniAdapter()
                anime_data = adapter.get_anime_details(f"https://openani.me/anime/{slug}")
                if anime_data:
                    ep_list = adapter.get_episodes(anime_data)
                    episodes = [(f"openani:{slug}::{ep['provider_data']['episode_id']}", ep['title']) for ep in ep_list]
                    return {"title": anime_data["title"], "poster": anime_data.get("image", ""), "summary": anime_data.get("description", ""), "episodes": episodes}
            except Exception as e:
                # Silently ignore openani errors
                return None
        elif prefix == "animedepo":
            eps = animedepo.get_anime_episodes(slug)
            if eps:
                title = slug.replace("-", " ").title()
                eps_formatted = [(f"animedepo:{slug}::{ep_slug}", ep_title) for ep_slug, ep_title in eps]
                return {"title": title, "poster": "", "summary": "", "episodes": eps_formatted}
        elif prefix == "animecix":
            from .animecix import CixAnime
            anime = CixAnime(id=slug, title=slug)
            episodes = [(f"animecix:{slug}::{ep.url}", ep.title) for ep in anime.episodes]
            if episodes:
                return {"title": anime.title, "poster": "", "summary": "", "episodes": episodes}
        elif prefix == "tranimaci":
            eps = tranimaci.get_anime_episodes(slug)
            if eps:
                title = slug.replace("-", " ").title()
                eps_formatted = [(f"tranimaci:{ep_slug}", ep_title) for ep_slug, ep_title in eps]
                return {"title": title, "poster": "", "summary": "", "episodes": eps_formatted}
    except Exception as e:
        print(f"[chain] get_anime_details error for {full_slug}: {e}")
    return None


def get_episode_streams(anime_slug_full: str, ep_slug: str) -> List[Dict[str, str]]:
    prefix, anime_slug = anime_slug_full.split(":", 1)
    if prefix not in PROVIDERS:
        return []
        
    if ep_slug.startswith(prefix + ":"):
        ep_slug = ep_slug[len(prefix) + 1:]
        
    # If using the new format "anime_slug::ep_slug"
    if "::" in ep_slug:
        anime_slug, ep_slug = ep_slug.split("::", 1)
        
    try:
        if prefix == "tranime":
            ep = tranime.get_episode_details(ep_slug)
            if ep:
                sources = ep.get_sources()
                streams = []
                for src in sources:
                    iframe = src.get_iframe()
                    if iframe:
                        if not iframe.startswith("http"):
                            iframe = "https:" + iframe if iframe.startswith("//") else iframe
                        streams.append({"url": iframe, "type": "iframe", "label": src.name})
                return streams
        elif prefix == "anizle":
            streams_raw = anizle.get_episode_streams(ep_slug)
            return [{"url": s["url"], "type": s.get("type", "video"), "label": s.get("label", "")} for s in streams_raw]
        elif prefix == "animely":
            anime = animely.get_anime_by_slug(anime_slug)
            if anime:
                for ep in anime.episodes:
                    if str(ep.episode_number) == str(ep_slug):
                        return [{"url": s.url, "type": "video", "label": s.quality} for s in ep.get_streams()]
        elif prefix == "openani":
            streams_raw = openani.get_episode_streams(ep_slug)
            return [{"url": s["url"], "type": s.get("type", "video"), "label": s.get("label", "")} for s in streams_raw]
        elif prefix == "animecix":
            streams = animecix._video_streams(ep_slug)
            return [{"url": s["url"], "type": "hls" if ".m3u8" in s["url"] else "video", "label": s.get("label", "")} for s in streams]
        elif prefix == "animedepo":
            streams_raw = animedepo.get_episode_streams(ep_slug)
            return [{"url": s["url"], "type": s.get("type", "video"), "label": s.get("label", "")} for s in streams_raw]
        elif prefix == "tranimaci":
            streams_raw = tranimaci.get_episode_streams(ep_slug)
            return [{"url": s["url"], "type": s.get("type", "video"), "label": s.get("label", "")} for s in streams_raw]
    except Exception as e:
        print(f"[chain] get_episode_streams error: {e}")
    return []