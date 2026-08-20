"""
Animecix + Ecchicix provider – auto‑refreshing token with curl_cffi bypass.
Loads data from "anime data" folder. Supports extended search via live providers.
"""
import json, os, re, sys, time, threading, requests
from urllib.parse import urlparse, parse_qs
from pathlib import Path

# Use curl_cffi for token extraction and API requests
try:
    from curl_cffi import requests as curl_requests
    HAS_CURL = True
except ImportError:
    HAS_CURL = False
    import requests

from turkanime_api.objects import Anime as BaseAnime, Bolum as BaseBolum, Video as BaseVideo, LogHandler
from turkanime_api import catalog_updater

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://animecix.tv/",
    "Accept": "application/json, text/plain, */*"
}

# ── File paths ──────────────────────────────────────
# Try to locate the "anime data" folder in several places:
# 1) Current working directory
# 2) Parent of the package directory (project root)
# 3) The user's home folder (fallback)
def _find_data_dir():
    candidates = [
        os.path.join(os.getcwd(), "anime data"),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "anime data"),
        os.path.join(Path.home(), ".turkanime", "anime data"),
    ]
    for d in candidates:
        if os.path.isdir(d):
            print(f"[Data] Using data directory: {d}")
            return d
    # If none found, create in current working directory
    fallback = os.path.join(os.getcwd(), "anime data")
    os.makedirs(fallback, exist_ok=True)
    print(f"[Data] Created data directory: {fallback}")
    return fallback

_DATA_DIR = _find_data_dir()

_ANIMES_PATH   = os.path.join(_DATA_DIR, "animes.json")
_EPISODES_PATH = os.path.join(_DATA_DIR, "episodes.json")
_ECCHICIX_ANIMES_PATH   = os.path.join(_DATA_DIR, "ecchicix_animes.json")
_ECCHICIX_EPISODES_PATH = os.path.join(_DATA_DIR, "ecchicix_episodes.json")

def _load_json(path):
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[Data] Error loading {path}: {e}")
    return []

def _ensure_json(path, default=None):
    if default is None: default = []
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(default, f, ensure_ascii=False, indent=2)
    return _load_json(path)

_ANIMES = _ensure_json(_ANIMES_PATH)
_EPISODES = _ensure_json(_EPISODES_PATH)
_ECCHICIX_ANIMES = _ensure_json(_ECCHICIX_ANIMES_PATH)
_ECCHICIX_EPISODES = _ensure_json(_ECCHICIX_EPISODES_PATH)

for item in _ECCHICIX_ANIMES:
    item["id"] = f"ecchi_{item['id']}"
    _ANIMES.append(item)
for item in _ECCHICIX_EPISODES:
    item["id"] = f"ecchi_{item['id']}"
    _EPISODES.append(item)

_ANIME_BY_TITLE = {}
_ANIME_TITLE_BY_ID = {}
for a in _ANIMES:
    a["id"] = str(a["id"])
    key = a.get("title", "").strip().lower()
    if key:
        _ANIME_BY_TITLE.setdefault(key, []).append((a["id"], a["title"]))
        _ANIME_TITLE_BY_ID[a["id"]] = a["title"]

_EPISODE_BY_ID = {str(item["id"]): item for item in _EPISODES}

print(f"[Data] Loaded {len(_ANIMES)} anime entries, {len(_EPISODES)} episode entries")

# Use curl_cffi session if available
if HAS_CURL:
    session = curl_requests.Session(impersonate="chrome110")
else:
    session = requests.Session()
session.headers.update(HEADERS)

# ── Manual update trigger (unchanged) ──────────────
_updating = False
_update_lock = threading.Lock()

def trigger_manual_update():
    t = threading.Thread(target=_run_async_update, daemon=True)
    t.start()
    return "Update started (both sites) – this may take a few minutes."

def _run_async_update():
    global _updating
    with _update_lock:
        if _updating: return
        _updating = True
    try:
        import asyncio
        asyncio.run(catalog_updater.run_full_update())
    except Exception as e:
        print(f"[Update] Error: {e}")
    finally:
        _updating = False
        reload_catalog()

def reload_catalog():
    global _ANIMES, _EPISODES, _ANIME_BY_TITLE, _ANIME_TITLE_BY_ID, _EPISODE_BY_ID
    _ANIMES = _load_json(_ANIMES_PATH) or []
    _EPISODES = _load_json(_EPISODES_PATH) or []
    ecchianimes = _load_json(_ECCHICIX_ANIMES_PATH) or []
    ecchiepisodes = _load_json(_ECCHICIX_EPISODES_PATH) or []
    for item in ecchianimes:
        item["id"] = f"ecchi_{item['id']}"
        _ANIMES.append(item)
    for item in ecchiepisodes:
        item["id"] = str(item['id'])
        if not str(item['id']).startswith("ecchi_"):
            item["id"] = f"ecchi_{item['id']}"
        _EPISODES.append(item)
    _ANIME_BY_TITLE.clear()
    _ANIME_TITLE_BY_ID.clear()
    for a in _ANIMES:
        a["id"] = str(a["id"])
        key = a.get("title", "").strip().lower()
        if key:
            _ANIME_BY_TITLE.setdefault(key, []).append((a["id"], a["title"]))
            _ANIME_TITLE_BY_ID[a["id"]] = a["title"]
    _EPISODE_BY_ID = {str(item["id"]): item for item in _EPISODES}
    print(f"[Data] Reloaded: {len(_ANIMES)} anime, {len(_EPISODES)} episodes")

# ── Helpers (unchanged) ──────────────────────────────
def _parse_season_episode(url):
    try:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        season = int(qs.get("season", [1])[0])
        episode = float(qs.get("episode", [0])[0])
        return (season, episode)
    except Exception:
        return None

# ── Anime class ──────────────────────────────────────
class Anime(BaseAnime):
    def __init__(self, slug, parse_fansubs=True):
        slug = _slug_to_id(slug)
        super().__init__(slug, parse_fansubs=parse_fansubs)
        self.anime_id = slug
        title = _ANIME_TITLE_BY_ID.get(str(slug))
        if not title:
            data = _EPISODE_BY_ID.get(str(slug), {})
            title = data.get("title")
        self._title = title or str(slug)  # ensure it's never None
        self.info = {
            "Kategori": None, "Japonca": None, "Anime Türü": [],
            "Bölüm Sayısı": 0, "Başlama Tarihi": None, "Bitiş Tarihi": None,
            "Stüdyo": None, "Puanı": 0.0, "Özet": "", "Resim": "",
            "Yıl": "",
        }
        data = _EPISODE_BY_ID.get(str(slug), {})
        seen = set()
        ep_items = []
        for season_block in data.get("seasons", []):
            for ep in season_block.get("episodes", []):
                url = ep.get("url", "")
                sp = _parse_season_episode(url)
                if sp is None:
                    key = url
                    sn, en = 1, 1
                else:
                    sn, en = sp
                    key = (sn, en)
                if key not in seen:
                    seen.add(key)
                    ep_items.append((sn, en, ep["name"], url))
        ep_items.sort(key=lambda x: (x[0], x[1]))
        self._bolumler_data = [(f"{sn}-{en}", name, url) for sn, en, name, url in ep_items]

    def fetch_info(self): pass

    def get_bolum_listesi(self):
        return [(slug, title) for slug, title, _ in self._bolumler_data]

    @property
    def seasons(self):
        seasons_dict = {}
        for slug, title, _ in self._bolumler_data:
            parts = slug.split('-')
            if len(parts) == 2:
                try:
                    season = int(parts[0])
                except ValueError:
                    season = 1
            else:
                season = 1
            seasons_dict.setdefault(season, []).append((slug, title))
        return seasons_dict

    @staticmethod
    def arama_yap(query):
        import re
        results = []
        q = query.lower()
        q_norm = re.sub(r'[^a-z0-9]', '', q)
        seen_ids = set()
        seen_titles = set()

        def add_results(source_results):
            for id_, title in source_results:
                sid = str(id_)
                if sid not in seen_ids and title.lower() not in seen_titles:
                    seen_ids.add(sid)
                    seen_titles.add(title.lower())
                    results.append((sid, title))

        # Ecchicix first
        ecchi_results = []
        for key, entries in _ANIME_BY_TITLE.items():
            for id_, title in entries:
                t_norm = re.sub(r'[^a-z0-9]', '', title.lower())
                if str(id_).startswith("ecchi_") and (q in title.lower() or q_norm in t_norm):
                    ecchi_results.append((id_, title))
        add_results(ecchi_results)

        # Animecix second
        animecix_results = []
        for key, entries in _ANIME_BY_TITLE.items():
            for id_, title in entries:
                t_norm = re.sub(r'[^a-z0-9]', '', title.lower())
                if not str(id_).startswith("ecchi_") and (q in title.lower() or q_norm in t_norm):
                    animecix_results.append((id_, title))
        add_results(animecix_results)

        return results

# ── Extended search ──────────────────────────────
def extended_search(query):
    local = Anime.arama_yap(query)
    if len(local) >= 10:
        return local
    try:
        from turkanime_api.sources.chain import search_all as live_search
        live = live_search(query)
        seen_titles = {t.lower() for _, t in local}
        for slug, title in live:
            if title.lower() not in seen_titles:
                local.append((slug, title))
    except Exception as e:
        print(f"[extended_search] Live providers error: {e}")
    return local

class Bolum(BaseBolum):
    def __init__(self, slug, anime=None, title=None, parse_fansubs=True):
        super().__init__(slug, anime=anime, title=title, parse_fansubs=parse_fansubs)
        self._episode_url = None
        if anime and hasattr(anime, "_bolumler_data"):
            for ep_slug, ep_title, ep_url in anime._bolumler_data:
                if ep_slug == slug:
                    self._episode_url = ep_url
                    self._title = ep_title
                    break
            if not self._episode_url and slug:
                m = re.search(r'(\d+)-bolum', slug)
                if m:
                    ep_num = m.group(1)
                    for ep_slug, ep_title, ep_url in anime._bolumler_data:
                        if ep_slug.endswith(f"-{ep_num}"):
                            self._episode_url = ep_url
                            self._title = ep_title
                            break

    @property
    def html(self): return ""

    def get_videos(self):
        if self._videos: return self._videos
        self._videos = []
        if not self._episode_url: return self._videos
        if str(self.anime.anime_id).startswith("ecchi_"):
            embed_url = _resolve_embed_ecchicix(self._episode_url)
            if embed_url:
                self._videos.append(Video(self, embed_url))
        else:
            embed_url = _resolve_embed(self._episode_url)
            if embed_url:
                self._videos.append(Video(self, embed_url))
            else:
                abs_url = _make_absolute(self._episode_url)
                self._videos.append(Video(self, abs_url))
        return self._videos

class Video(BaseVideo):
    def __init__(self, bolum, url):
        super().__init__(bolum, path="dummy", player="ANIMECIX", fansub=None, log_handler=LogHandler)
        self._url = url
        self.is_supported = True
        self._is_working = True

    @property
    def is_working(self): return True
    @is_working.setter
    def is_working(self, value): self._is_working = value

    @property
    def info(self):
        if not self._url:
            return {}
        return {
            "id": "animecix_video",
            "title": self.bolum.slug if self.bolum else "video",
            "url": self._url,
            "urls": [self._url],
            "direct": True,
            "extractor": "generic",
            "formats": [{"url": self._url, "format_id": "direct"}]
        }

def _slug_to_id(slug):
    slug_str = str(slug)
    if slug_str.isdigit():
        data = _EPISODE_BY_ID.get(slug_str, {})
        if not data.get("seasons"):
            ecchi_id = f"ecchi_{slug_str}"
            if ecchi_id in _EPISODE_BY_ID and _EPISODE_BY_ID[ecchi_id].get("seasons"):
                return ecchi_id
        return slug_str
    if slug_str.startswith("ecchi_"): return slug_str
    clean = re.sub(r'-izle$', '', slug).replace('-', ' ').strip().lower()
    for a in _ANIMES:
        if a.get("title", "").strip().lower() == clean:
            return a["id"]
    for a in _ANIMES:
        if clean in a.get("title", "").strip().lower():
            return a["id"]
    return slug

def _make_absolute(url_path):
    if url_path.startswith("http"): return url_path
    if url_path.startswith("/"): return "https://animecix.tv" + url_path
    return "https://animecix.tv/" + url_path

def _make_absolute_ecchicix(url_path):
    if url_path.startswith("http"): return url_path
    if url_path.startswith("/"): return "https://ecchicix.com" + url_path
    return "https://ecchicix.com/" + url_path

def _resolve_embed(url_path):
    url = _make_absolute(url_path)
    sess = session if HAS_CURL else requests.Session()
    if not HAS_CURL:
        sess.headers.update(HEADERS)
    else:
        sess.headers.update(HEADERS)
    sess.headers["Referer"] = "https://animecix.tv/"
    try:
        r = sess.get(url, allow_redirects=True, timeout=15)
        ct = r.headers.get("Content-Type", "")
        if "application/json" in ct:
            data = r.json()
            for key in ("url", "video", "src", "file", "link"):
                if data.get(key):
                    r = sess.get(data[key], allow_redirects=True, timeout=15)
                    break
        final = r.url
        if "tau-video.xyz" in final or "embed" in final:
            return final
    except Exception as e:
        print(f"[ERROR] _resolve_embed: {e}")
    return None

def _resolve_embed_ecchicix(url_path):
    url = _make_absolute_ecchicix(url_path)
    sess = session if HAS_CURL else requests.Session()
    if not HAS_CURL:
        sess.headers.update(HEADERS)
    else:
        sess.headers.update(HEADERS)
    sess.headers["Referer"] = "https://ecchicix.com/"
    try:
        r = sess.get(url, allow_redirects=True, timeout=15)
        ct = r.headers.get("Content-Type", "")
        if "application/json" in ct:
            data = r.json()
            for key in ("url", "video", "src", "file", "link"):
                if data.get(key):
                    r = sess.get(data[key], allow_redirects=True, timeout=15)
                    break
        final = r.url
        if "tau-video.xyz" in final or "embed" in final:
            return final
    except Exception as e:
        print(f"[ERROR] _resolve_embed_ecchicix: {e}")
    return None