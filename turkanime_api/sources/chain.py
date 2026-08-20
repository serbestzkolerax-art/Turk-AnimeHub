"""Unified provider chain using the sources package."""
from typing import List, Tuple, Dict, Any, Optional
from . import anizle, openani, animecix, animedepo, tranimaci, animely
from . import PROVIDERS, get_provider_by_priority

# All live providers ( re‑enabled) + AnimeDepo + Tranimaci + Anizle
SEARCH_ORDER = ["animedepo", "animecix", "openani", "anizle", "animely"]

def search_all(query: str, limit: int = 10, skip_depo: bool = False) -> List[Tuple[str, str]]:
    import difflib
    import concurrent.futures
    
    if not skip_depo:
        # First, only search animedepo to make it fast
        try:
            depo_results = animedepo.search_animedepo(query, limit=limit)
        except Exception as e:
            print(f"[chain] search error for animedepo: {e}")
            depo_results = []
            
        if depo_results:
            # Sort animedepo results by similarity
            def sort_key(item):
                slug, title = item
                sim = difflib.SequenceMatcher(None, query.lower(), title.lower()).ratio()
                if query.lower() in title.lower() or title.lower() in query.lower():
                    sim += 0.5
                return sim
                
            depo_results.sort(key=sort_key, reverse=True)
            return [(f"animedepo:{slug}", title) for slug, title in depo_results[:limit]]
        
    # If animedepo has NO results, fallback to searching all other sources concurrently
    results = []
    seen = set()

    def _do_search(name):
        try:
            if name == "anizle":
                return name, anizle.search_anizle(query)[:limit]
            elif name == "animely":
                return name, animely.search_animely(query, limit=limit)
            elif name == "openani":
                return name, openani.search_openani(query, limit=limit)
            elif name == "animecix":
                return name, animecix.search_animecix(query)[:limit]
            elif name == "tranimaci":
                return name, tranimaci.search_tranimaci(query, limit=limit)
        except Exception as e:
            print(f"[chain] search error for {name}: {e}")
        return name, []

    collected = []
    other_sources = [s for s in SEARCH_ORDER if s != "animedepo"]
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(other_sources)) as executor:
        futures = {executor.submit(_do_search, name): name for name in other_sources}
        for future in concurrent.futures.as_completed(futures):
            name, items = future.result()
            for slug, title in items:
                full = f"{name}:{slug}"
                if full not in seen:
                    seen.add(full)
                    collected.append((full, title, name))

    def fallback_sort_key(item):
        full_slug, title, source_name = item
        sim = difflib.SequenceMatcher(None, query.lower(), title.lower()).ratio()
        if query.lower() in title.lower() or title.lower() in query.lower():
            sim += 0.5
        return sim

    collected.sort(key=fallback_sort_key, reverse=True)
    return [(c[0], c[1]) for c in collected[:25]]


def get_anime_details(full_slug: str) -> Optional[Dict[str, Any]]:
    prefix, slug = full_slug.split(":", 1)
    if prefix not in PROVIDERS:
        return None

    try:
        if prefix == "anizle":
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
        if prefix == "anizle":
            streams_raw = anizle.get_episode_streams(ep_slug)
            return [{"url": s["url"], "type": s.get("type", "video"), "label": s.get("label", ""), "referer": s.get("referer")} for s in streams_raw if s.get("url")]
        elif prefix == "openani":
            streams_raw = openani.get_episode_streams(ep_slug)
            return [{"url": s["url"], "type": s.get("type", "video"), "label": s.get("label", ""), "referer": s.get("referer")} for s in streams_raw if s.get("url")]
        elif prefix == "animecix":
            streams = animecix._video_streams(ep_slug)
            return [{"url": s["url"], "type": "hls" if ".m3u8" in s["url"] else "video", "label": s.get("label", ""), "referer": s.get("referer")} for s in streams if s.get("url")]
        elif prefix == "animedepo":
            streams_raw = animedepo.get_episode_streams(ep_slug)
            return [{"url": s["url"], "type": s.get("type", "video"), "label": s.get("label", ""), "referer": s.get("referer")} for s in streams_raw if s.get("url")]
        elif prefix == "tranimaci":
            streams_raw = tranimaci.get_episode_streams(ep_slug)
            return [{"url": s["url"], "type": s.get("type", "video"), "label": s.get("label", ""), "referer": s.get("referer")} for s in streams_raw if s.get("url")]
    except Exception as e:
        print(f"[chain] get_episode_streams error: {e}")
    return []