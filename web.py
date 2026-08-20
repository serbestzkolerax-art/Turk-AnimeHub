import threading
import json
import sys, os, time, traceback, re, functools, requests
import subprocess, zipfile, io
from collections import OrderedDict
from urllib.parse import quote

def _ensure_flaresolverr():
    try:
        r = requests.get('http://localhost:8191/', timeout=1)
        if 'FlareSolverr' in r.text:
            return
    except Exception:
        pass

    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        fs_dir = os.path.join(base_dir, 'flaresolverr')
        exe_path = os.path.join(fs_dir, 'flaresolverr.exe')

        if not os.path.exists(exe_path):
            print("[FlareSolverr] Ä°ndiriliyor (bu iÅŸlem bir kez yapÄ±lÄ±r, ~80MB)...")
            url = 'https://github.com/FlareSolverr/FlareSolverr/releases/download/v3.3.17/flaresolverr_windows_x64.zip'
            r = requests.get(url)
            with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                z.extractall(base_dir)
            print("[FlareSolverr] Ä°ndirme ve Ã§Ä±karma tamamlandÄ±.")
            time.sleep(2)
        
        try:
            output = subprocess.check_output('tasklist /FI "IMAGENAME eq flaresolverr.exe"', shell=True).decode(errors='ignore')
            if 'flaresolverr.exe' in output:
                return
        except Exception:
            pass

        print("[FlareSolverr] Arka planda baÅŸlatÄ±lÄ±yor. LÃ¼tfen hazÄ±r olmasÄ±nÄ± bekleyin...")
        subprocess.Popen([exe_path], cwd=fs_dir, creationflags=0x08000000)
        
        for _ in range(20):
            try:
                r = requests.get('http://localhost:8191/', timeout=1)
                if 'FlareSolverr' in r.text:
                    print("[FlareSolverr] BaÅŸarÄ±yla baÅŸlatÄ±ldÄ± ve istekleri kabul etmeye hazÄ±r!")
                    break
            except Exception:
                time.sleep(1)
    except Exception as e:
        print(f"[FlareSolverr] Otomatik baÅŸlatma baÅŸarÄ±sÄ±z: {e}")

if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
    _ensure_flaresolverr()
else:
    # Ensure it's ready in worker process too
    _ensure_flaresolverr()

# ---- Path setup ----
PACKAGE_NAME = "turkanime_api"
def _find_and_register_package_root(start_dir):
    d = start_dir
    for _ in range(5):
        if os.path.isdir(os.path.join(d, PACKAGE_NAME)):
            sys.path.insert(0, d)
            return True
        parent = os.path.dirname(d)
        if parent == d: break
        d = parent
    return False

current_dir = os.path.dirname(os.path.abspath(__file__))
if not _find_and_register_package_root(current_dir):
    sys.path.insert(0, os.path.dirname(current_dir))
    sys.path.insert(0, current_dir)

# ---- Mocks ----
try: import yt_dlp
except (ImportError, ModuleNotFoundError):
    from unittest.mock import MagicMock; sys.modules['yt_dlp'] = MagicMock()
try: import Crypto
except (ImportError, ModuleNotFoundError):
    from unittest.mock import MagicMock; sys.modules['Crypto'] = MagicMock()
try: import curl_cffi
except (ImportError, ModuleNotFoundError):
    from unittest.mock import MagicMock; sys.modules['curl_cffi'] = MagicMock()

from turkanime_api import animecix, animedepo
from turkanime_api.sources import chain as live_chain
from turkanime_api.sources import tranime, anizle, animely, openani
from flask import Flask, render_template, request, redirect, jsonify

app = Flask(__name__)

@app.template_filter('clean_ep_title')
def clean_ep_title(ep_title, anime_title):
    ep_title = str(ep_title)
    anime_title = str(anime_title)
    
    # 1. Simple replace first
    cleaned = ep_title.replace(anime_title, '').strip()
    
    # 2. If the anime_title was "One Punch Man 3", and ep_title was "One Punch Man 3rd Season 1. BÃ¶lÃ¼m"
    # it leaves "rd Season 1. BÃ¶lÃ¼m". Let's clean up orphaned suffixes.
    cleaned = re.sub(r'^(rd|nd|st|th)?\s*[Ss]eason\s*', '', cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r'^-\s*', '', cleaned).strip()
    
    return cleaned if cleaned else ep_title

DEFAULT_COVER = "https://images.unsplash.com/photo-1578632767115-351597cf2477?w=400&q=80"

_anilist_cache = OrderedDict()

# --- DISK CACHE & RATE LIMIT LOCK ---
ANILIST_CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "anime data", "anilist_cache.json")
_anilist_lock = threading.Lock()

def load_anilist_cache():
    global _anilist_cache
    if os.path.exists(ANILIST_CACHE_FILE):
        try:
            with open(ANILIST_CACHE_FILE, 'r', encoding='utf-8') as f:
                _anilist_cache.update(json.load(f))
        except: pass

def save_anilist_cache():
    try:
        with open(ANILIST_CACHE_FILE, 'w', encoding='utf-8') as f:
            # Sadece son 500 öğeyi kaydet ki dosya şişmesin
            keys = list(_anilist_cache.keys())[-500:]
            to_save = {k: _anilist_cache[k] for k in keys}
            json.dump(to_save, f)
    except: pass

load_anilist_cache()

def fetch_media(search_title=None, media_id=None):
    cache_key = f"{search_title}_{media_id}"
    if cache_key in _anilist_cache:
        return _anilist_cache[cache_key]
        
    query = '''
    query ($search: String, $id: Int) {
      Media(search: $search, id: $id, type: ANIME) {
        id
        title { romaji english }
        description
        coverImage { large }
        format
        relations {
          edges {
            relationType
            node {
              id
              title { romaji english }
              format
              type
              coverImage { large }
            }
          }
        }
      }
    }
    '''
    import threading
    def _do_req(st=None, mid=None):
        variables = {}
        if st: variables['search'] = st
        if mid: variables['id'] = mid
        for _ in range(3):
            try:
                with _anilist_lock:
                    r = requests.post('https://graphql.anilist.co', json={'query': query, 'variables': variables}, timeout=5)
                    if r.status_code == 429:
                        time.sleep(2.5) # Wait out the rate limit
                        continue
                    if r.ok:
                        data = r.json()
                        return data.get('data', {}).get('Media')
                    # Hata varsa biraz bekle
                    time.sleep(0.5)
            except Exception:
                time.sleep(0.5)
        return None
        return res.json().get('data', {}).get('Media')

    try:
        data = _do_req(search_title, media_id)
        
        # Fallback logic for long/mismatched titles
        if not data and search_title:
            # 1. Remove common suffixes
            import re
            cleaned = re.sub(r'(?i)\b(TV|OVA|ONA|Special|Specials|Movie|Season \d+|Part \d+)\b.*', '', search_title).strip()
            if cleaned and cleaned != search_title:
                data = _do_req(cleaned)
                
            # 2. Try first 4, 3, or 2 words (gradual fallback to get franchise cover)
            if not data:
                words = search_title.split()
                if len(words) > 4:
                    data = _do_req(' '.join(words[:4]))
                if not data and len(words) > 3:
                    data = _do_req(' '.join(words[:3]))
                if not data and len(words) > 2:
                    data = _do_req(' '.join(words[:2]))
                    
            # 3. Only split by colon if the prefix is reasonably long to avoid false positives (like "Magi:")
            if not data and ':' in search_title:
                prefix = search_title.split(':')[0].strip()
                if len(prefix) > 5:
                    data = _do_req(prefix)

        if data:
            _anilist_cache[cache_key] = data
            return data
    except Exception as e:
        print(f"AniList API error: {e}")
    return None

_cover_cache = {}

def search_mal_cover(title):
    if title in _cover_cache: return _cover_cache[title]
    
    with _anilist_lock:
        import urllib.parse
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        url = f'https://myanimelist.net/anime.php?q={urllib.parse.quote(title)}&cat=anime'
        try:
            r = requests.get(url, headers=headers, timeout=5)
            if r.status_code == 429: time.sleep(1.5)
            match = re.search(r'https://cdn\.myanimelist\.net/r/\d+x\d+/images/anime/\d+/\d+\.jpg', r.text)
            if match:
                url = match.group(0)
                url = re.sub(r'r/\d+x\d+/', '', url)
                _cover_cache[title] = url
                return url
        except Exception:
            pass
        _cover_cache[title] = None
        return None

def get_anilist_cover(title):
    if not title or title.lower() == "none":
        return DEFAULT_COVER
    clean = re.sub(r'-(izle|bolum|bÃ¶lÃ¼m|\d+.*)', '', str(title), flags=re.IGNORECASE).strip()
    clean = re.sub(r'[^\w\s]', ' ', clean).strip()
    if not clean: clean = str(title)
    
    # MAL is the 1st choice for covers
    mal_cover = search_mal_cover(clean)
    if mal_cover:
        return mal_cover
        
    # Fallback to AniList if MAL fails
    try:
        data = fetch_media(search_title=clean)
        if data and data.get("coverImage") and data["coverImage"].get("large"):
            return data["coverImage"]["large"]
    except Exception: pass
        
    return DEFAULT_COVER

@app.route("/api/cover")
def cover_api():
    title = request.args.get("title", "").strip()
    if not title or title.lower() == "none":
        return redirect(DEFAULT_COVER)
    return redirect(get_anilist_cover(title))

@app.route("/api/alt_sources")
def alt_sources_api():
    title = request.args.get("title", "").strip()
    ep_title = request.args.get("ep_title", "").strip()
    current_slug = request.args.get("current_slug", "").strip()
    
    if not title or not ep_title:
        return jsonify([])
        
    target_num = None
    am = re.search(r'(\d+)\s*\.?\s*[Bb]ölüm', ep_title)
    if not am: am = re.search(r'[Bb]ölüm\s*(\d+)', ep_title)
    if not am:
        anums = re.findall(r'(\d+)', ep_title)
        if anums: target_num = int(anums[-1])
    else:
        target_num = int(am.group(1))
        
    if target_num is None:
        return jsonify([])

    alternatives = []
    
    import concurrent.futures

    def check_live_provider(l_slug, provider_name):
        try:
            details = live_chain.get_anime_details(l_slug)
            if details and "episodes" in details:
                for ep_s, ep_t in details["episodes"]:
                    anums2 = re.findall(r'(\d+)', ep_t)
                    if anums2 and int(anums2[-1]) == target_num:
                        url = f"/watch?slug={quote(l_slug)}&ep={quote(ep_s)}&title={quote(ep_t)}"
                        return {"provider": provider_name, "url": url}
        except Exception:
            pass
        return None

    futures_list = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:

        # Check AnimeCix
        def check_animecix():
            try:
                cix_results = animecix.Anime.arama_yap(title)
                for cix_slug, cix_title in cix_results:
                    if _is_title_match(cix_title, title) and str(cix_slug) != current_slug:
                        test_anime = animecix.Anime(slug=cix_slug)
                        eps = test_anime.get_bolum_listesi()
                        if eps:
                            for ep_s, ep_t in eps:
                                anums2 = re.findall(r'(\d+)', ep_t)
                                if anums2 and int(anums2[-1]) == target_num:
                                    url = f"/watch?slug={quote(str(cix_slug))}&ep={quote(ep_s)}&title={quote(ep_t)}"
                                    return {"provider": "AnimeCix", "url": url}
                        break
            except Exception:
                pass
            return None
        futures_list.append(executor.submit(check_animecix))
        
        # Check Live Providers
        try:
            live_results = live_chain.search_all(title, limit=3, skip_depo=True)
            # Filter results with matching exact title and different slug
            valid_slugs = []
            seen_providers = set()
            for s, t in live_results:
                if _is_title_match(t, title) and s != current_slug:
                    prov = s.split(":")[0].title()
                    if prov.lower() == "animecix":
                        continue
                    if prov not in seen_providers:
                        seen_providers.add(prov)
                        valid_slugs.append((s, prov))
                        
            for s, p in valid_slugs:
                futures_list.append(executor.submit(check_live_provider, s, p))
        except Exception:
            pass

        for future in concurrent.futures.as_completed(futures_list):
            res = future.result()
            if res:
                alternatives.append(res)
                
    # Deduplicate providers (case insensitive)
    seen = set()
    deduped = []
    for alt in alternatives:
        prov = alt["provider"].lower()
        if prov not in seen:
            seen.add(prov)
            deduped.append(alt)
                
    # Sort alphabetically by provider name
    deduped.sort(key=lambda x: x["provider"])
    return jsonify(deduped)

# ---- Popular list ----
POPULAR = [
    ("ecchi_8", "One Punch Man"),
    ("ecchi_25", "Attack on Titan"),
    ("ecchi_17", "Tokyo Ghoul"),
    ("ecchi_7609", "Kuroko no Basket"),
    ("ecchi_12136", "My Hero Academia"),
    ("ecchi_7352", "Jujutsu Kaisen"),
    ("ecchi_66", "One Piece"),
    ("ecchi_7258", "Dr. Stone"),
    ("ecchi_8086", "Kyoukai no Kanata"),
]

# ---- HTML Template (keep your existing template) ----
# ---------- Caching ----------
_anime_cache = OrderedDict()
CACHE_MAX = 50
CACHE_TTL = 600

def _extract_seasons(episodes):
    seasons = {}
    for slug, title in episodes:
        cix_match = re.match(r'^(\d+)-[\d\.]+$', str(slug))
        match = re.search(r'(\d+)[-]sezon|sezon[-](\d+)|[Ss](\d+)[Ee]', str(slug))
        
        # Check if OVA or Special
        if 'ova' in str(title).lower() or 'ova' in str(slug).lower():
            season = 'OVA'
        elif 'special' in str(title).lower() or 'Ã¶zel' in str(title).lower() or 'special' in str(slug).lower():
            season = 'Special'
        elif cix_match:
            season = int(cix_match.group(1))
        elif match:
            season = int(match.group(1) or match.group(2) or match.group(3))
        else:
            sm = re.search(r'(\d+)\.?\s*[Ss]ezon', str(title))
            season = int(sm.group(1)) if sm else 1
            
        seasons.setdefault(season, []).append((slug, title))
        
    # Sort seasons: integers first, then strings
    sorted_seasons = {}
    sorted_keys = sorted(seasons.keys(), key=lambda x: (isinstance(x, str), x))
    for k in sorted_keys:
        sorted_seasons[str(k)] = seasons[k]
        
    return sorted_seasons

def _normalize_slug_from_title(title):
    slug = title.lower()
    for tr, eng in zip("Ã§ÄŸÄ±Ã¶ÅŸÃ¼", "cgiosu"):
        slug = slug.replace(tr, eng)
    slug = re.sub(r'[^a-z0-9]+', '-', slug)
    return slug.strip('-')

import difflib

def _is_title_match(t1, t2):
    def normalize(t):
        t_str = str(t).lower()
        # Remove ordinals from numbers (1st, 2nd, 3rd, 4th)
        t_str = re.sub(r'(?<=\d)(st|nd|rd|th)\b', '', t_str)
        # Strip structural keywords
        t_str = re.sub(r'\b(season|part|tv|movie\s*\d*|movie)\b', '', t_str)
        # Unify special/ona to ova so they match
        t_str = re.sub(r'\b(special|specials|ona)\b', 'ova', t_str)
        return re.sub(r'[^a-z0-9]', '', t_str)
    
    n1 = normalize(t1)
    n2 = normalize(t2)
    
    if n1 == n2:
        return True
        
    aliases = {
        normalize("2.5-jigen no Ririsa"): [normalize("2.5 Dimensional Seduction"), normalize("Nitengo-jigen no Ririsa"), normalize("2.5 Jigen no Ririsa")],
        normalize("2.5 Dimensional Seduction"): [normalize("2.5-jigen no Ririsa")],
    }
    
    if n1 in aliases and n2 in aliases[n1]:
        return True
    if n2 in aliases and n1 in aliases[n2]:
        return True
        
    if n1 and n2:
        # Prevent matching different seasons/parts
        if re.findall(r'\d+', n1) != re.findall(r'\d+', n2):
            return False
            
        ratio = difflib.SequenceMatcher(None, n1, n2).ratio()
        if ratio > 0.90:
            return True
            
    return False
def _merge_all_episodes_for_title(title):
    if not title:
        return []
    all_eps = {}

    def parse_sn_en(slug, ep_title):
        m = re.match(r'^(\d+)\.\s*[Ss]ezon\s*(\d+)\.\s*[Bb]', str(ep_title))
        if m:
            return int(m.group(1)), float(m.group(2))

        m = re.match(r'^(\d+)-([\d\.]+)$', str(slug))
        if m:
            return int(m.group(1)), float(m.group(2))
        
        sm = re.search(r'(?i)(\d+)(?:st|nd|rd|th)?\.?\s*(?:sezon|season)', str(ep_title))
        season = int(sm.group(1)) if sm else 1
        
        em = re.search(r'(?i)(\d+)\s*\.?\s*(?:b\w*l\w*m|ep)', str(ep_title))
        if not em:
            em = re.search(r'(?i)(?:b\w*l\w*m|ep)\s*(\d+)', str(ep_title))
            
        if not em:
            nums = re.findall(r'(\d+)', str(ep_title))
            if nums:
                if sm and sm.group(1) in nums:
                    nums.remove(sm.group(1))
                ep = float(nums[-1]) if nums else 0.0
            else:
                ep = 0.0
        else:
            ep = float(em.group(1))
        return season, ep
    
    import concurrent.futures

    def fetch_local():
        try:
            results = animecix.Anime.arama_yap(title)
            is_fallback = False
            if not results:
                t = re.sub(r'(?i)\d+(st|nd|rd|th)?\s*[Ss]eason', '', title)
                t = re.sub(r'(?i)[Ss]eason\s*\d+', '', t)
                t = re.sub(r'(?i)part\s*\d+', '', t)
                base_title = re.sub(r'\s+', ' ', t).strip()
                if base_title != title:
                    results = animecix.Anime.arama_yap(base_title)
                    is_fallback = True

            for slug, res_title in results:
                search_t = base_title if is_fallback else title
                q = re.sub(r'[^a-zA-Z0-9\s]', '', search_t.lower().strip())
                s_clean = str(slug).split(':', 1)[-1].replace('-', ' ').lower().strip()
                if _is_title_match(res_title, search_t) or q == s_clean or q in s_clean:
                    anime = animecix.Anime(slug=slug)
                    # If this is a fallback for an OVA/Special, don't return the main anime's episodes!
                    if is_fallback and re.search(r'(?i)(ova|special)', title):
                        return []
                    return anime.get_bolum_listesi() or []
        except Exception:
            pass
        return []

    def fetch_depo():
        try:
            from turkanime_api.sources import animedepo as animedepo_source
            slug = _normalize_slug_from_title(title)
            return [(f"animedepo:{slug}::{ep_slug}", ep_title) for ep_slug, ep_title in (animedepo_source.get_anime_episodes(slug) or [])]
        except Exception:
            return []

    def fetch_live():
        # User requested to drop live sources from auto-merging to prevent slow page loads
        return []

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        f_local = executor.submit(fetch_local)
        f_depo = executor.submit(fetch_depo)
        f_live = executor.submit(fetch_live)
        
        depo_eps = f_depo.result()
        local_eps = f_local.result()
        live_eps = f_live.result()
        
        depo_limits = {}
        for ep_slug, ep_title in depo_eps:
            sn, en = parse_sn_en(ep_slug.split("/")[-1] if "animedepo" in ep_slug else ep_slug, ep_title)
            depo_limits[sn] = max(depo_limits.get(sn, 0.0), en)
            all_eps[(sn, en)] = (ep_slug, ep_title)
            
        
        for eps, is_cix in [(local_eps, True), (live_eps, False)]:
            for ep_slug, ep_title in eps:
                sn, en = parse_sn_en(ep_slug, ep_title)
                
                # ENFORCE ANIMEDEPO STRUCTURE ONLY FOR LOCAL ECCI:
                if is_cix and depo_limits:
                    if sn not in depo_limits:
                        continue
                    if en > depo_limits[sn]:
                        continue
                    
                original_en = en
                if original_en == 0.0:
                    while (sn, en) in all_eps:
                        existing_slug, existing_title = all_eps[(sn, en)]
                        if existing_title == ep_title or _is_title_match(existing_title, ep_title):
                            break
                        en += 0.001
                        
                if (sn, en) not in all_eps:
                    all_eps[(sn, en)] = (ep_slug, ep_title)

    sorted_keys = sorted(all_eps.keys(), key=lambda x: (x[0], x[1]))
    return [all_eps[k] for k in sorted_keys]

def get_anime_detail(slug):
    now = time.time()
    if slug in _anime_cache:
        entry = _anime_cache[slug]
        if now - entry['time'] < CACHE_TTL:
            _anime_cache.move_to_end(slug)
            return entry['anime'], entry['episodes'], entry['seasons'], entry['source']
        else:
            del _anime_cache[slug]

    anime = None
    title = None
    source = "unknown"
    live_episodes = None

    # 1. Live provider (prefixed slug)
    if ":" in slug and not slug.startswith("ecchi_"):
        try:
            details = live_chain.get_anime_details(slug)
            if details:
                title = details["title"]
                passed_title = request.args.get("title")
                
                # If the title is just a numeric ID (like animecix), use the passed title
                if not title or title.isdigit():
                    if passed_title:
                        title = passed_title
                        details["title"] = title
                
                # Try to enhance metadata using AniList if title is just numbers or metadata is empty
                if not details.get("poster"):
                    search_t = passed_title if passed_title else title
                    if search_t:
                        try:
                            ani_info = fetch_media(search_title=search_t)
                            if ani_info:
                                details["poster"] = ani_info.get("coverImage", {}).get("large", "")
                                details["summary"] = ani_info.get("description", "")
                                # Use the canonical romaji title from AniList if it's better
                                if title.isdigit() and ani_info.get("title", {}).get("romaji"):
                                    title = ani_info["title"]["romaji"]
                                    details["title"] = title
                        except Exception as e:
                            print(f"Error fetching enhanced metadata: {e}")
                source = slug.split(":")[0]
                class LiveAnime:
                    def __init__(self, slug, title, poster, summary):
                        self.slug = slug
                        self.title = title
                        self.info = {"Ã–zet": summary, "Resim": poster}
                anime = LiveAnime(slug, title, details.get("poster", ""), details.get("summary", ""))
                live_episodes = details.get("episodes", [])
        except Exception as e:
            print(f"[get_anime_detail] live error: {e}")



    # 3. Local (animecix/ecchicix)
    if anime is None:
        try:
            test_anime = animecix.Anime(slug=slug)
            if test_anime.title:
                anime = test_anime
                title = anime.title
                source = "animecix"
                
                # Enhance metadata using AniList if missing
                if not anime.info.get("Resim") and title:
                    try:
                        ani_info = fetch_media(search_title=title)
                        if ani_info:
                            if ani_info.get("coverImage", {}).get("large"):
                                anime.info["Resim"] = ani_info["coverImage"]["large"]
                            if ani_info.get("description"):
                                anime.info["Özet"] = ani_info["description"]
                    except Exception as e:
                        print(f"Error fetching enhanced metadata for ecchi: {e}")
        except Exception:
            pass

    if anime is not None:
        if not hasattr(anime, "slug"):
            anime.slug = slug

    if anime is None:
        title = slug.replace("-", " ").title()
        class DummyAnime:
            def __init__(self, slug, title):
                self.slug = slug
                self.title = title
                self.info = {"Ã–zet": "Bu anime iÃ§in detay bulunamadÄ±.", "Resim": ""}
        anime = DummyAnime(slug, title)
        return anime, [], {}, "dummy"

    if not title:
        title = slug.replace("-", " ").title()

    merged_eps = _merge_all_episodes_for_title(title)
    
    # If the magical merge failed for some reason, fallback to the provider's direct list
    if not merged_eps and live_episodes:
        merged_eps = live_episodes

    seasons = _extract_seasons(merged_eps) if merged_eps else {}

    if len(_anime_cache) >= CACHE_MAX:
        _anime_cache.popitem(last=False)
    _anime_cache[slug] = {
        'anime': anime,
        'episodes': merged_eps,
        'seasons': seasons,
        'source': source,
        'time': now
    }
    return anime, merged_eps, seasons, source

def run_search(query):
    local = []
    seen_titles = set()

    # Search across all sources
    try:
        from turkanime_api.sources import chain as live_chain
        results = live_chain.search_all(query, limit=20)
        
        base_titles = []
        for slug, title in results:
            # User specifically requested: "don show ona ova specials in search just show main show"
            if re.search(r'(?i)\b(ova|ona|special|specials|season\s*\d+|\d+(st|nd|rd|th)?\s*season|part\s*\d+|movie)\b', title):
                continue
                
            # Filter out AnimeDepo split seasons (e.g. "One Punch Man 3" or "One Punch Man: Road to Hero")
            # If the base title ("One Punch Man") is already found, we skip these suffixes.
            is_suffix = False
            for bt in base_titles:
                if title.lower().startswith(bt.lower()) and len(title) > len(bt):
                    is_suffix = True
                    break
            if is_suffix:
                continue
                
            normalized = re.sub(r'[^a-z0-9]', '', title.lower())
            if title and normalized not in seen_titles:
                local.append((slug, title))
                seen_titles.add(normalized)
                base_titles.append(title)
    except Exception as e:
        print(f"[run_search] Error: {e}")

    # Return the raw deduplicated results. 
    # Do not group by franchise prefix, as it causes false positives.
    return local

# ---- Watchlist API ----
WATCHLIST_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "anime data", "watchlist.json")

def load_watchlist():
    if not os.path.exists(WATCHLIST_FILE):
        return []
    try:
        import json
        with open(WATCHLIST_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []

def save_watchlist(data):
    import json
    with open(WATCHLIST_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


# ---- BaÄŸlantÄ±lÄ± Seriler API'si ----
# AniList GraphQL cache to avoid 429 Too Many Requests
_anilist_cache = {}

@app.route('/api/related', methods=['GET'])
def api_related():
    title = request.args.get('title')
    if not title:
        return jsonify({"error": "No title provided"}), 400
        
    try:
        from turkanime_api.sources import animedepo
        
        def get_best_title(node):
            t = node.get('title', {})
            return t.get('romaji') or t.get('english') or 'Unknown'

        # 1. KÃ¶k animeyi bul
                # 1. Kk animeyi bul
        # Often AnimeDepo has weird suffixes that Anilist doesn't have.
        import re
        search_t = re.sub(r'(?i)(Commemorative Special|Special|Specials|OVA|ONA)', '', title).strip()
        current_media = fetch_media(search_title=search_t)
        if not current_media: 
            current_media = fetch_media(search_title=title)
            
        if not current_media: 
            return jsonify([])
        
        for _ in range(4):
            prequel_edge = next((e for e in current_media.get('relations', {}).get('edges', []) 
                                 if e['relationType'] in ('PREQUEL', 'PARENT', 'MAIN_STORY') and e['node']['type'] == 'ANIME'), None)
            if prequel_edge:
                p_media = fetch_media(media_id=prequel_edge['node']['id'])
                if p_media: current_media = p_media
                else: break
            else:
                break
                
        # 2. Devam serilerini aÅŸaÄŸÄ± doÄŸru tara
        timeline = []
        current_node = current_media
        for _ in range(6):
            if not current_node: break
            
            # Ana seriyi ekle
            timeline.append({
                'title': get_best_title(current_node),
                'relation': 'TV Series' if current_node.get('format') == 'TV' else str(current_node.get('format')),
                'is_main': True,
                'cover': current_node.get('coverImage', {}).get('large', '')
            })
            
            edges = current_node.get('relations', {}).get('edges', [])
            
            # Yan hikayeleri / OVA'larÄ± ekle
            for e in edges:
                if e['relationType'] in ['SIDE_STORY', 'OVA', 'SPIN_OFF', 'OTHER', 'ALTERNATIVE', 'SUMMARY'] and e['node']['type'] == 'ANIME':
                    fmt = e['node'].get('format', 'OVA')
                    timeline.append({
                        'title': get_best_title(e['node']),
                        'relation': f"{e['relationType'].replace('_', ' ').title()} ({fmt})",
                        'is_main': False,
                        'cover': e['node'].get('coverImage', {}).get('large', '')
                    })
                    
            # Sonraki devam serisine geÃ§
            sequel_edge = next((e for e in edges if e['relationType'] == 'SEQUEL' and e['node']['type'] == 'ANIME'), None)
            if sequel_edge:
                current_node = fetch_media(media_id=sequel_edge['node']['id'])
            else:
                break

        # 3. Eşleştirme ve Son Liste
        from turkanime_api.sources import chain as live_chain
        final_list = []
        seen_titles = set()
        
        for item in timeline:
            rel_title = item['title']
            found_slug = None
            found_title_matched = rel_title
            
            # Hızlıca tüm kaynaklarda ara
            search_results = live_chain.search_all(rel_title, limit=5)
            
            for slug, d_title in search_results:
                if _is_title_match(d_title, rel_title):
                    found_slug = slug
                    found_title_matched = d_title
                    break
                    
            # Başlık tekrarını önle
            normalized_title = re.sub(r'[^a-z0-9]', '', found_title_matched.lower())
            if normalized_title not in seen_titles:
                seen_titles.add(normalized_title)
                final_list.append({
                    "relation": item['relation'],
                    "title": found_title_matched,
                    "slug": found_slug,
                    "cover": item.get('cover')
                })
                
        # Global Inject: Search AnimeDepo for the base title, and inject ANY missing series into the timeline!
        import re
        base_title_clean = re.sub(r'(?i)\\b(Commemorative Special|Special|Specials|OVA|ONA|Movie)\\b', '', title).strip()
        from turkanime_api.sources import animedepo as animedepo_source
        try:
            depo_results = animedepo_source.search_animedepo(base_title_clean, limit=15)
            for d_slug, d_title in depo_results:
                # Check if this depo title is already in our final_list
                found = False
                for item in final_list:
                    if item['title'].lower() == d_title.lower():
                        found = True
                        break
                if not found:
                    # Is this depo result actually related to our base anime?
                    if base_title_clean.lower() in d_title.lower():
                        # Find the best place to inject it
                        search_t = re.sub(r'(?i)\\b(Commemorative Special|Special|Specials|OVA|ONA|Movie)\\b', '', d_title).strip().lower()
                        # Find the best place to inject it (longest matching title)
                        best_match_idx = -1
                        best_match_len = -1
                        for i, item in enumerate(final_list):
                            if search_t in item['title'].lower() or item['title'].lower() in search_t:
                                if len(item['title']) > best_match_len:
                                    best_match_len = len(item['title'])
                                    best_match_idx = i
                        
                        if best_match_idx != -1:
                            final_list.insert(best_match_idx+1, {
                                "title": d_title,
                                "relation": "OVA/Special",
                                "slug": "animedepo:" + str(d_slug),
                                "cover": final_list[best_match_idx].get('cover')
                            })
                        else:
                            final_list.append({
                                "title": d_title,
                                "relation": "OVA/Special",
                                "slug": "animedepo:" + str(d_slug),
                                "cover": final_list[0].get('cover') if final_list else None
                            })
        except Exception as e:
            print("[Related] Error injecting AnimeDepo items:", e)
            
        return jsonify(final_list)
        
    except Exception as e:
        print("[Related] Error:", e)
        return jsonify([])

@app.route('/api/watchlist', methods=['GET', 'POST', 'DELETE'])
def api_watchlist():
    if request.method == 'GET':
        return jsonify(load_watchlist())
        
    try:
        req_data = request.get_json()
        if not req_data or 'slug' not in req_data:
            return jsonify({"error": "Invalid payload"}), 400
            
        slug = req_data['slug']
        title = req_data.get('title', slug)
        
        current_list = load_watchlist()
        
        if request.method == 'POST':
            # Add to watchlist
            if not any(item['slug'] == slug for item in current_list):
                current_list.append({"slug": slug, "title": title})
                save_watchlist(current_list)
                print(f"[Watchlist] Added: {title} ({slug})")
            return jsonify({"status": "added", "list": current_list})
            
        elif request.method == 'DELETE':
            # Remove from watchlist
            new_list = [item for item in current_list if item['slug'] != slug]
            if len(new_list) < len(current_list):
                save_watchlist(new_list)
                print(f"[Watchlist] Removed: {slug}")
            return jsonify({"status": "removed", "list": new_list})
            
    except Exception as e:
        print(f"[Watchlist] Error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/watchlist/clear', methods=['POST'])
def clear_watchlist():
    try:
        save_watchlist([])
        return jsonify({"status": "cleared"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/watchlist")
def watchlist_page():
    wl = load_watchlist()
    return render_template('watchlist.html', watchlist=wl, query="", popular_catalog=None)

@app.route("/")
def index():
    query = request.args.get("q", "").strip()
    slug = request.args.get("slug")
    if slug:
        anime, eps, seasons, src = get_anime_detail(slug)
        if not anime: return "<pre>Anime bulunamadÄ±</pre>", 404
        total_episodes = sum(len(v) for v in seasons.values()) if seasons else len(eps)
        wl = load_watchlist()
        in_watchlist = any(item['slug'] == slug for item in wl)
        return render_template('watch.html', selected_anime=anime, episodes=eps,
                                      seasons=seasons, total_episodes=total_episodes,
                                      source_name=src, query="", watch_slug=slug, in_watchlist=in_watchlist)
    if query:
        results = run_search(query)
        return render_template('index.html', results=results, query=query,
                                      selected_anime=None, watch_slug=None,
                                      popular_catalog=None)
    return render_template('index.html', popular_catalog=POPULAR, query="",
                                  selected_anime=None, watch_slug=None)

# ---------- Video ----------
def build_bolum(slug, ep_slug):
    # Live providers first
    if ":" in ep_slug and not ep_slug.startswith("ecchi_"):
        try:
            # We pass ep_slug as anime_slug_full so chain.py can extract the prefix from it
            streams = live_chain.get_episode_streams(ep_slug, ep_slug)
            if streams:
                class LiveBolum:
                    def __init__(self):
                        self._videos = []
                bolum = LiveBolum()
                from turkanime_api.animecix import Video, Anime, Bolum
                for s in streams:
                    v = Video(None, s["url"])
                    v._url = s["url"]
                    v._is_working = True
                    label = s.get("label", "Video")
                    if "player" in s and "fansub" in s:
                        v.player, v.fansub = s["player"], s["fansub"]
                    else:
                        parts = label.split(" - ", 1)
                        if len(parts) == 2:
                            v.player, v.fansub = parts[0], parts[1]
                        else:
                            v.player, v.fansub = label, "AnimeDepo"
                    v.type = s.get("type", "video")
                    bolum._videos.append(v)
                
                # UNIONIZE: Check for Ecchicix streams
                from flask import request
                anime_obj, _, _, _ = get_anime_detail(slug)
                title = anime_obj.title if anime_obj else ""
                ep_t = request.args.get("title", "") or ep_slug
                if title:
                    target_num = None
                    am = re.search(r'(\d+)\s*\.?\s*[Bb]ölüm', ep_t)
                    if not am: am = re.search(r'[Bb]ölüm\s*(\d+)', ep_t)
                    if not am:
                        anums = re.findall(r'(\d+)', ep_t)
                        if anums: target_num = int(anums[-1])
                    else:
                        target_num = int(am.group(1))
                        
                    if target_num is not None:
                        cix_results = Anime.arama_yap(title)
                        for cix_slug, cix_title in cix_results:
                            if _is_title_match(cix_title, title) and str(cix_slug).startswith("ecchi_"):
                                test_anime = Anime(slug=cix_slug)
                                eps = test_anime.get_bolum_listesi()
                                if eps:
                                    for ecchi_ep_s, ecchi_ep_t in eps:
                                        anums2 = re.findall(r'(\d+)', ecchi_ep_t)
                                        if anums2 and int(anums2[-1]) == target_num:
                                            # Fetch streams for this ecchi episode!
                                            ecchi_bolum = Bolum(slug=ecchi_ep_s, anime=test_anime)
                                            ecchi_bolum.get_videos()
                                            if ecchi_bolum._videos:
                                                for v in ecchi_bolum._videos:
                                                    if not getattr(v, "fansub", ""):
                                                        v.fansub = "Ecchicix"
                                                    else:
                                                        v.fansub = f"Ecchicix - {v.fansub}"
                                                    bolum._videos.append(v)
                                            break
                                break
                return bolum, None
            else:
                return None, "Video bulunamadi."
        except Exception as e:
            return None, str(e)



    # 1. AnimeDepo
    try:
        from turkanime_api.sources import animedepo
        anime = animedepo.Anime(slug=slug)
        bolum = animedepo.Bolum(slug=ep_slug, anime=anime)
        bolum.get_videos()
        
        # UNIONIZE: Add Animecix/Ecchicix sources into the AnimeDepo player!
        try:
            from turkanime_api.animecix import Anime, Bolum as CixBolum
            from flask import request
            anime_obj, _, _, _ = get_anime_detail(slug)
            title = anime_obj.title if anime_obj else ""
            ep_t = request.args.get("title", "") or ep_slug
            if title:
                target_num = None
                am = re.search(r'(\d+)\s*\.?\s*[Bb]lÇ¬m', ep_t)
                if not am: am = re.search(r'[Bb]lÇ¬m\s*(\d+)', ep_t)
                if not am:
                    anums = re.findall(r'(\d+)', ep_t)
                    if anums: target_num = int(anums[-1])
                else:
                    target_num = int(am.group(1))
                    
                if target_num is not None:
                    cix_results = Anime.arama_yap(title)
                    for cix_slug, cix_title in cix_results:
                        if _is_title_match(cix_title, title):
                            test_anime = Anime(slug=cix_slug)
                            eps = test_anime.get_bolum_listesi()
                            if eps:
                                for ecchi_ep_s, ecchi_ep_t in eps:
                                    anums2 = re.findall(r'(\d+)', ecchi_ep_t)
                                    if anums2 and int(anums2[-1]) == target_num:
                                        ecchi_bolum = CixBolum(slug=ecchi_ep_s, anime=test_anime)
                                        ecchi_bolum.get_videos()
                                        if ecchi_bolum._videos:
                                            if not hasattr(bolum, "_videos"): bolum._videos = []
                                            for v in ecchi_bolum._videos:
                                                if not getattr(v, "fansub", ""):
                                                    v.fansub = "Ecchicix"
                                                else:
                                                    v.fansub = f"Ecchicix - {v.fansub}"
                                                bolum._videos.append(v)
                                        break
                            break
        except Exception as e:
            print(f"[build_bolum] Unionize error: {e}")

        if hasattr(bolum, "_videos") and bolum._videos:
            return bolum, None
    except Exception as e:
        print(f"[AnimeDepo bolum error]\n{e}")

    # 2. Local (animecix/ecchicix) fallback for direct ecchi slugs
    try:
        from turkanime_api.animecix import Anime, Bolum
        anime = Anime(slug=slug)
        bolum = Bolum(slug=ep_slug, anime=anime)
        bolum.get_videos()
        if bolum._videos:
            for v in bolum._videos: v._provider = "animecix"
            return bolum, None
    except Exception as e:
        print(f"[build_bolum] Local fallback error: {e}")

    return None, "HiÃ§bir saÄŸlayÄ±cÄ±dan video bulunamadÄ±."

def pick_video(bolum, requested_player=None, requested_fansub=None):
    vids = [v for v in bolum._videos if v.is_supported]
    if requested_player:
        matched = [v for v in vids if v.player == requested_player]
        if requested_fansub is not None:
            matched_with_fs = [v for v in matched if getattr(v, "fansub", "") == requested_fansub]
            if matched_with_fs:
                matched = matched_with_fs
        if matched: vids = matched
    for v in vids:
        try:
            if v.is_working: return v, None
        except Exception: continue
    return None, "Ã‡alÄ±ÅŸan video bulunamadÄ±."

def resolve_stream(vid):
    candidate = vid.url
    if not candidate: return None, None
    if ".m3u8" in candidate: return candidate, "hls"
    if ".mp4" in candidate: return candidate, "video"
    return candidate, "iframe"

@app.route("/watch")
def watch():
    slug = request.args.get("slug")
    ep_slug = request.args.get("ep")
    if not ep_slug:
        return redirect(f"/?slug={slug}")
    ep_title = request.args.get("title") or ep_slug
    requested_player = request.args.get("player")
    requested_fansub = request.args.get("fansub")

    bolum, err = build_bolum(slug, ep_slug)

    grouped_videos = OrderedDict()
    stream_url = stream_kind = player_name = fansub_name = player_error = None
    
    if bolum is None:
        player_error = err
    else:
        for v in bolum._videos:
            if not v.is_supported: continue
            fs = getattr(v, 'fansub', '') or 'VarsayÄ±lan'
            if fs not in grouped_videos:
                grouped_videos[fs] = OrderedDict()
            if v.player not in grouped_videos[fs]:
                grouped_videos[fs][v.player] = v

        vid, pick_err = pick_video(bolum, requested_player, requested_fansub)
        if vid is None:
            player_error = pick_err
        else:
            player_name = vid.player
            fansub_name = getattr(vid, 'fansub', '') or 'VarsayÄ±lan'
            try:
                stream_url, stream_kind = resolve_stream(vid)
                if not stream_url:
                    player_error = "Stream Ã§Ã¶zÃ¼lemedi."
            except Exception:
                player_error = traceback.format_exc()

    anime_detail_obj, merged_eps, seasons, source_type = get_anime_detail(slug)
    anime_title = anime_detail_obj.title if anime_detail_obj else slug
    
    # Calculate Next Episode
    next_ep_slug = None
    next_ep_title = None
    if merged_eps:
        for i, (e_slug, e_title) in enumerate(merged_eps):
            if e_slug == ep_slug and i + 1 < len(merged_eps):
                next_ep_slug = merged_eps[i+1][0]
                next_ep_title = merged_eps[i+1][1]
                break

    wl = load_watchlist()
    in_watchlist = any(item['slug'] == slug for item in wl)

    return render_template('watch.html',
        selected_anime=anime_detail_obj, results=None,
        watch_slug=slug, ep_slug=ep_slug, ep_title=ep_title,
        anime_title=anime_title, query="",
        stream_url=stream_url, stream_kind=stream_kind,
        player_error=player_error, 
        current_player=player_name, current_fansub=fansub_name,
        grouped_videos=grouped_videos,
        next_ep_slug=next_ep_slug, next_ep_title=next_ep_title,
        seasons=seasons, episodes=merged_eps, in_watchlist=in_watchlist)

@app.route("/api/refresh_catalog", methods=["GET", "POST"])
def api_refresh_catalog():
    try:
        msg = animecix.trigger_manual_update()
        return jsonify({"status": "success", "message": msg})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/update-catalog")
def update_catalog():
    try:
        msg = animecix.trigger_manual_update()
        return f"<pre>{msg}</pre><p><a href='/'>Ana Sayfa</a></p>"
    except Exception as e:
        return f"<pre>GÃ¼ncelleme baÅŸlatÄ±lamadÄ±: {e}</pre>"

if __name__ == "__main__":
    app.run(debug=True, port=5000)
