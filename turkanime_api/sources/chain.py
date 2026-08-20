"""Unified provider chain using the sources package."""
from typing import List, Tuple, Dict, Any, Optional
from . import anizle, openani, animecix, animedepo, tranimaci, animely
from . import PROVIDERS, get_provider_by_priority

# All live providers ( re‑enabled) + AnimeDepo + Tranimaci + Anizle
SEARCH_ORDER = ["animedepo", "animecix", "openani", "anizle"]

def search_all(query: str, limit: int = 10, skip_depo: bool = False) -> List[Tuple[str, str]]:
    import re
    import difflib
    import concurrent.futures
    def _score(title):
        q = re.sub(r'[^\w\s]', '', query.lower().strip())
        t = re.sub(r'[^\w\s]', '', title.lower().strip())
        q_words = q.split()
        t_words = set(t.split())
        s = 0.0
        if all(w in t_words for w in q_words):
            s += 1.0
        if q in t or t in q:
            s += 0.5
        s += difflib.SequenceMatcher(None, q, t).ratio()
        return s

    def is_good_match(slug, title):
        q = re.sub(r'[^\w\s]', '', query.lower().strip())
        s_clean = str(slug).replace('-', ' ').lower().strip()
        if q == s_clean or q in s_clean:
            return True
        score = _score(title)
        if score < 1.0:
            return score > 0.85
        return True

    def sort_key(item):
        prefix_slug, title = item
        return _score(title)

    def _do_search(name):
        try:
            if name == "animedepo":
                return name, animedepo.search_animedepo(query, limit=50)
            elif name == "animecix":
                from turkanime_api.animecix import Anime as LocalAnime
                return name, LocalAnime.arama_yap(query)[:50]
            elif name == "anizle":
                return name, anizle.search_anizle(query)[:limit]
            elif name == "animely":
                return name, animely.search_animely(query, limit=limit)
            elif name == "openani":
                return name, openani.search_openani(query, limit=limit)
        except Exception as e:
            print(f"[chain] search error for {name}: {e}")
        return name, []

    # PHASE 1: Fast local/direct sources
    fast_sources = ["animecix"]
    if not skip_depo:
        fast_sources.insert(0, "animedepo")
        
    phase1_results = []
    seen = set()
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(fast_sources)) as executor:
        futures = {executor.submit(_do_search, name): name for name in fast_sources}
        for future in concurrent.futures.as_completed(futures):
            name, items = future.result()
            for slug, title in items:
                if is_good_match(slug, title):
                    norm = title.lower().strip()
                    if norm not in seen:
                        seen.add(norm)
                        if str(slug).startswith("ecchi_"):
                            phase1_results.append((slug, title))
                        else:
                            phase1_results.append((f"{name}:{slug}", title))
                        
    if phase1_results:
        phase1_results.sort(key=sort_key, reverse=True)
        return phase1_results[:limit]
        
    # PHASE 2: Slow live sources
    live_sources = ["openani", "anizle", "animely"]
    phase2_results = []
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(live_sources)) as executor:
        futures = {executor.submit(_do_search, name): name for name in live_sources}
        for future in concurrent.futures.as_completed(futures):
            name, items = future.result()
            for slug, title in items:
                if is_good_match(slug, title):
                    norm = title.lower().strip()
                    if norm not in seen:
                        seen.add(norm)
                        phase2_results.append((f"{name}:{slug}", title))
                        
    phase2_results.sort(key=sort_key, reverse=True)
    return phase2_results[:limit]


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