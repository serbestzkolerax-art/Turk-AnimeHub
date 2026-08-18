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
            print("[FlareSolverr] İndiriliyor (bu işlem bir kez yapılır, ~80MB)...")
            url = 'https://github.com/FlareSolverr/FlareSolverr/releases/download/v3.3.17/flaresolverr_windows_x64.zip'
            r = requests.get(url)
            with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                z.extractall(base_dir)
            print("[FlareSolverr] İndirme ve çıkarma tamamlandı.")
            time.sleep(2)
        
        try:
            output = subprocess.check_output('tasklist /FI "IMAGENAME eq flaresolverr.exe"', shell=True).decode(errors='ignore')
            if 'flaresolverr.exe' in output:
                return
        except Exception:
            pass

        print("[FlareSolverr] Arka planda başlatılıyor. Lütfen hazır olmasını bekleyin...")
        subprocess.Popen([exe_path], cwd=fs_dir, creationflags=0x08000000)
        
        for _ in range(20):
            try:
                r = requests.get('http://localhost:8191/', timeout=1)
                if 'FlareSolverr' in r.text:
                    print("[FlareSolverr] Başarıyla başlatıldı ve istekleri kabul etmeye hazır!")
                    break
            except Exception:
                time.sleep(1)
    except Exception as e:
        print(f"[FlareSolverr] Otomatik başlatma başarısız: {e}")

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

DEFAULT_COVER = "https://images.unsplash.com/photo-1578632767115-351597cf2477?w=400&q=80"

@functools.lru_cache(maxsize=500)
def get_mal_cover(title):
    if not title or title.lower() == "none":
        return DEFAULT_COVER
    clean = re.sub(r'-(izle|bolum|bölüm|\d+.*)', '', str(title), flags=re.IGNORECASE).strip()
    clean = re.sub(r'[^\w\s]', ' ', clean).strip()
    if not clean: clean = str(title)
    try:
        url = f"https://myanimelist.net/search/prefix.json?type=anime&keyword={quote(clean)}&v=1"
        resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=2.5)
        if resp.status_code == 200:
            data = resp.json()
            cat = data.get("categories", [])
            if cat and cat[0].get("items"):
                img = cat[0]["items"][0].get("image_url", "")
                if img: return re.sub(r'/r/\d+x\d+', '', img)
    except Exception: pass
    return DEFAULT_COVER

@app.route("/api/cover")
def cover_api():
    title = request.args.get("title", "").strip()
    if not title or title.lower() == "none":
        return redirect(DEFAULT_COVER)
    return redirect(get_mal_cover(title))

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
            live_results = live_chain.search_all(title, limit=3)
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
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="tr" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AnimeHub - Anime İzle & Keşfet</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap" rel="stylesheet">
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        tailwind.config = {
            darkMode: 'class',
            theme: {
                extend: {
                    fontFamily: { sans: ['Inter', 'sans-serif'] },
                    colors: {
                        darker: '#0a0d14',
                        cardbg: '#121722',
                        accent: '#e11d48',
                    }
                }
            }
        }
    </script>
    <style>
        ::-webkit-scrollbar { width: 6px; height: 6px; }
        ::-webkit-scrollbar-track { background: #0a0d14; }
        ::-webkit-scrollbar-thumb { background: #232a3b; border-radius: 3px; }
        ::-webkit-scrollbar-thumb:hover { background: #e11d48; }
        .season-tab {
            transition: all 0.2s;
            cursor: pointer;
            border-bottom: 2px solid transparent;
        }
        .season-tab.active { border-bottom-color: #e11d48; color: #e11d48; font-weight: 700; }
        .season-tab:hover { color: #e11d48; }
    </style>
</head>
<body class="bg-darker text-gray-100 font-sans min-h-screen flex flex-col">
    <nav class="bg-cardbg/95 backdrop-blur-md border-b border-gray-800/80 sticky top-0 z-50 px-4 sm:px-8 py-3.5 flex items-center justify-between shadow-2xl">
        <div class="flex items-center gap-8">
            <a href="/" class="text-2xl font-black tracking-wider text-accent flex items-center gap-2 group">
                <span class="text-3xl transform group-hover:scale-110 transition duration-300">⚡</span>
                <span class="bg-gradient-to-r from-accent via-rose-400 to-white bg-clip-text text-transparent">ANIME</span><span class="text-white">HUB</span>
            </a>
        </div>
        <form action="/" method="GET" class="flex items-center gap-2 w-full max-w-md ml-4">
            <div class="relative w-full">
                <input type="text" name="q" value="{{ query }}" placeholder="Anime ara..."
                    class="w-full bg-darker/90 border border-gray-700/80 text-sm rounded-xl pl-10 pr-4 py-2.5 focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent text-white placeholder-gray-500 transition shadow-inner">
                <svg class="w-4 h-4 text-gray-400 absolute left-3.5 top-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
                </svg>
            </div>
            <button type="submit" class="bg-gradient-to-r from-accent to-rose-600 hover:from-rose-600 hover:to-rose-700 text-white px-5 py-2.5 rounded-xl text-sm font-bold shadow-md hover:shadow-rose-600/30 transition duration-200 shrink-0">
                Ara
            </button>
        </form>
    </nav>

    <main class="max-w-7xl mx-auto px-4 sm:px-6 py-8 flex-1 w-full">
        {% if selected_anime %}
            <div class="mb-6">
                <a href="/" class="inline-flex items-center text-sm font-semibold text-gray-400 hover:text-accent transition gap-2">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 19l-7-7m0 0l7-7m-7 7h18"/></svg>
                    Ana Sayfaya Dön
                </a>
            </div>
            <div class="grid grid-cols-1 md:grid-cols-4 gap-8 bg-cardbg/80 backdrop-blur p-6 sm:p-8 rounded-3xl border border-gray-800/80 shadow-2xl relative overflow-hidden">
                <div class="absolute -right-20 -top-20 w-80 h-80 bg-accent/10 rounded-full blur-3xl pointer-events-none"></div>
                <div class="md:col-span-1 flex flex-col items-center">
                    <div class="relative group w-full overflow-hidden rounded-2xl shadow-xl border border-gray-700/50 aspect-[2/3]">
                        <img src="/api/cover?title={{ selected_anime.title|urlencode }}" 
                             alt="{{ selected_anime.title }}" class="w-full h-full object-cover group-hover:scale-105 transition duration-500" loading="lazy">
                    </div>
                </div>
                <div class="md:col-span-3 flex flex-col justify-between">
                    <div>
                        <h1 class="text-3xl sm:text-4xl font-extrabold mb-4 text-white tracking-tight leading-tight">{{ selected_anime.title }}</h1>
                        <div class="bg-darker/60 p-4 rounded-2xl border border-gray-800/60 mb-6">
                            <h3 class="text-xs font-bold text-gray-400 uppercase tracking-wider mb-2">Özet / Konu</h3>
                            <p class="text-gray-300 text-sm leading-relaxed max-h-48 overflow-y-auto pr-2">
                                {{ selected_anime.info.get('Özet', 'Bu anime için özet açıklaması henüz eklenmedi.') }}
                            </p>
                        </div>
                    </div>
                    <div class="flex items-center gap-4 text-xs text-gray-400">
                        <span>Stüdyo: <strong class="text-gray-200">{{ selected_anime.info.get('Stüdyo', 'Bilinmiyor') }}</strong></span>
                        <span>•</span>
                        <span>Bölüm Sayısı: <strong class="text-accent">{{ total_episodes }} Bölüm</strong></span>
                    </div>
                </div>
            </div>

            <div class="mt-10">
                {% if seasons %}
                <div class="flex flex-wrap gap-2 mb-6 border-b border-gray-800 pb-2">
                    {% for season_num in seasons.keys()|sort %}
                        <button onclick="switchSeason({{ season_num }})" 
                                class="season-tab px-4 py-2 text-sm font-semibold text-gray-400 focus:outline-none"
                                id="tab-{{ season_num }}">{{ season_num }}. Sezon</button>
                    {% endfor %}
                </div>

                {% for season_num, eps in seasons.items()|sort %}
                    <div id="season-{{ season_num }}" class="season-content hidden">
                        <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3 max-h-[500px] overflow-y-auto pr-2 p-1">
                            {% for ep_slug, ep_title in eps %}
                                <a href="/watch?slug={{ selected_anime.slug }}&ep={{ ep_slug }}&title={{ ep_title|urlencode }}" 
                                   class="group bg-cardbg hover:bg-gradient-to-r hover:from-accent hover:to-rose-600 border border-gray-800/80 hover:border-accent p-3.5 rounded-xl text-center text-sm font-semibold transition-all duration-200 truncate block shadow-md hover:shadow-rose-600/30 hover:scale-[1.02]">
                                    <span class="text-gray-300 group-hover:text-white truncate block">{{ ep_title }}</span>
                                </a>
                            {% endfor %}
                        </div>
                    </div>
                {% endfor %}
                {% else %}
                    <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3 max-h-[500px] overflow-y-auto pr-2 p-1">
                        {% for ep_slug, ep_title in episodes %}
                            <a href="/watch?slug={{ selected_anime.slug }}&ep={{ ep_slug }}&title={{ ep_title|urlencode }}" 
                               class="group bg-cardbg hover:bg-gradient-to-r hover:from-accent hover:to-rose-600 border border-gray-800/80 hover:border-accent p-3.5 rounded-xl text-center text-sm font-semibold transition-all duration-200 truncate block shadow-md hover:shadow-rose-600/30 hover:scale-[1.02]">
                                <span class="text-gray-300 group-hover:text-white truncate block">{{ ep_title }}</span>
                            </a>
                        {% endfor %}
                    </div>
                {% endif %}
            </div>

            <script>
                document.addEventListener('DOMContentLoaded', function() {
                    const tabs = document.querySelectorAll('.season-tab');
                    if (tabs.length > 0) {
                        tabs[0].classList.add('active');
                        const firstSeasonNum = tabs[0].id.split('-')[1];
                        document.getElementById('season-' + firstSeasonNum).classList.remove('hidden');
                    }
                });
                function switchSeason(seasonNum) {
                    document.querySelectorAll('.season-tab').forEach(tab => tab.classList.remove('active'));
                    document.querySelectorAll('.season-content').forEach(div => div.classList.add('hidden'));
                    document.getElementById('tab-' + seasonNum).classList.add('active');
                    document.getElementById('season-' + seasonNum).classList.remove('hidden');
                }
            </script>

        {% elif watch_slug %}
            <div class="mb-6 flex items-center justify-between">
                <a href="/?slug={{ watch_slug }}" class="inline-flex items-center text-sm font-semibold text-gray-400 hover:text-accent transition gap-2">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 19l-7-7m0 0l7-7m-7 7h18"/></svg>
                    Bölüm Listesine Dön
                </a>
            </div>

            <div class="bg-cardbg p-6 sm:p-8 rounded-3xl border border-gray-800 shadow-2xl">
                <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
                    <div>
                        <span class="text-xs font-bold text-accent uppercase tracking-widest block mb-1">Oynatılıyor</span>
                        <h2 class="text-2xl sm:text-3xl font-extrabold text-white">{{ ep_title }}</h2>
                    </div>
                    {% if next_ep_slug %}
                    <a href="/watch?slug={{ watch_slug }}&ep={{ next_ep_slug }}&title={{ next_ep_title|urlencode }}" class="bg-accent hover:bg-rose-600 text-white font-bold py-2.5 px-5 rounded-xl shadow-lg transition-all flex items-center gap-2 hover:scale-105">
                        Sonraki Bölüm
                        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/></svg>
                    </a>
                    {% endif %}
                </div>

                {% if stream_url %}
                    <div class="bg-black rounded-2xl overflow-hidden mb-6 aspect-video shadow-2xl border border-gray-800 relative">
                        {% if stream_kind == "video" %}
                            <video src="{{ stream_url }}" controls autoplay class="w-full h-full"></video>
                        {% elif stream_kind == "hls" %}
                            <video id="player" controls autoplay class="w-full h-full"></video>
                            <script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
                            <script>
                                var video = document.getElementById('player');
                                var src = {{ stream_url|tojson }};
                                if (video.canPlayType('application/vnd.apple.mpegurl')) {
                                    video.src = src;
                                } else if (Hls.isSupported()) {
                                    var hls = new Hls();
                                    hls.loadSource(src);
                                    hls.attachMedia(video);
                                }
                            </script>
                        {% else %}
                            <iframe src="{{ stream_url }}" class="w-full h-full" allowfullscreen frameborder="0"></iframe>
                        {% endif %}
                    </div>
                {% else %}
                    <div class="bg-darker/90 rounded-2xl p-10 text-center border border-red-900/50 mb-6">
                        <div class="w-12 h-12 bg-red-500/10 text-red-500 rounded-full flex items-center justify-center mx-auto mb-3 text-xl">⚠️</div>
                        <h3 class="text-lg font-bold text-red-400 mb-2">Video Oynatılamadı</h3>
                        {% if player_error %}<p class="text-gray-400 text-sm">{{ player_error }}</p>{% endif %}
                    </div>
                {% endif %}
                  
                {% if grouped_videos %}
                  <div class="mt-4 flex flex-col gap-3 bg-darker/50 p-4 rounded-xl border border-gray-800/50">
                      <span class="text-sm text-gray-400 font-bold mb-1">📺 Video Seçimi:</span>
                      <div class="flex flex-col gap-4">
                          {% for fs, players in grouped_videos.items() %}
                              <div class="flex flex-col gap-1.5">
                                  <span class="text-xs text-gray-500 font-semibold uppercase tracking-wider">{{ fs }}</span>
                                  <div class="flex flex-wrap gap-2">
                                      {% for p_name, v in players.items() %}
                                          <a href="/watch?slug={{ watch_slug }}&ep={{ ep_slug }}&title={{ ep_title|urlencode }}&player={{ p_name|urlencode }}&fansub={{ (v.fansub or '')|urlencode }}" 
                                             class="px-3 py-1.5 text-xs font-bold rounded-lg transition-colors border shadow-sm
                                             {% if p_name == current_player and fs == current_fansub %}bg-accent text-white shadow-accent/20 border-accent
                                             {% else %}bg-gray-800/80 text-gray-300 hover:bg-gray-700 hover:text-white border-gray-700{% endif %}">
                                              {{ p_name }}
                                          </a>
                                      {% endfor %}
                                  </div>
                              </div>
                          {% endfor %}
                      </div>
                  </div>
                  {% endif %}
                  
                  <!-- Additional Resources / Alternate Providers -->
                  <div id="alt-sources-wrapper" class="mt-4 flex flex-col gap-3 hidden bg-darker/50 p-4 rounded-xl border border-gray-800/50">
                      <span class="text-sm text-gray-400 font-bold">🌍 Alternatif Kaynaklar:</span>
                      <div id="alt-sources-container" class="flex flex-wrap gap-2">
                      </div>
                  </div>
                
            </div>

            <!-- Alternate sources script -->
            <script>
                document.addEventListener('DOMContentLoaded', function() {
                    const title = {{ anime_title|tojson }};
                    const epTitle = {{ ep_title|tojson }};
                    const currentSlug = {{ watch_slug|tojson }};
                    
                    fetch('/api/alt_sources?title=' + encodeURIComponent(title) + '&ep_title=' + encodeURIComponent(epTitle) + '&current_slug=' + encodeURIComponent(currentSlug))
                        .then(res => res.json())
                        .then(data => {
                              const wrapper = document.getElementById('alt-sources-wrapper');
                              const container = document.getElementById('alt-sources-container');
                              
                              if(data && data.length > 0) {
                                  wrapper.classList.remove('hidden');
                                  container.innerHTML = '';
                                  data.forEach(src => {
                                      const a = document.createElement('a');
                                      a.href = src.url;
                                      a.className = "px-3 py-1.5 text-xs font-bold rounded-lg transition-colors border bg-gray-800/80 text-gray-300 hover:bg-gray-700 hover:text-white border-gray-700 shadow-sm";
                                      a.textContent = `[${src.provider}] Diğer Kaynak`;
                                      container.appendChild(a);
                                  });
                              }
                        })
                        .catch(err => console.error("Alt sources fetch error:", err));
                });
            </script>

            <!-- History Saver -->
            <script>
                (function() {
                    const item = {
                        slug: {{ watch_slug|tojson }},
                        ep_slug: {{ ep_slug|tojson }},
                        ep_title: {{ ep_title|tojson }},
                        anime_title: {{ anime_title|tojson }},
                        cover: "/api/cover?title=" + encodeURIComponent({{ anime_title|tojson }}),
                        timestamp: Date.now()
                    };
                    let history = JSON.parse(localStorage.getItem('animehub_history') || '[]');
                    history = history.filter(h => h.slug !== item.slug);
                    history.unshift(item);
                    history = history.slice(0, 15);
                    localStorage.setItem('animehub_history', JSON.stringify(history));
                })();
            </script>
            
            <!-- Episode Grid -->
            {% if seasons %}
                <div class="mt-8 bg-cardbg p-6 sm:p-8 rounded-3xl border border-gray-800 shadow-2xl">
                    <h3 class="text-xl font-bold text-white mb-6 border-b border-gray-800 pb-4">Tüm Bölümler</h3>
                    
                    {% if seasons|length > 1 %}
                        <div class="flex flex-wrap gap-2 mb-6 border-b border-gray-800/60 pb-4">
                            {% for season_num, _ in seasons.items()|sort %}
                                <button id="tab-{{ season_num }}" class="season-tab px-4 py-2 text-sm font-semibold text-gray-400 rounded-lg hover:bg-gray-800/50 {% if loop.first %}active{% endif %}" onclick="switchSeason('{{ season_num }}')">{{ season_num }}</button>
                            {% endfor %}
                        </div>
                    {% endif %}

                    {% for season_num, eps in seasons.items()|sort %}
                        <div id="season-{{ season_num }}" class="season-content {% if not loop.first %}hidden{% endif %}">
                            <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3 max-h-[500px] overflow-y-auto pr-2 p-1">
                                {% for ep_s, ep_t in eps %}
                                    <a href="/watch?slug={{ watch_slug }}&ep={{ ep_s }}&title={{ ep_t|urlencode }}" 
                                       class="group bg-darker hover:bg-gradient-to-r hover:from-accent hover:to-rose-600 border border-gray-800/80 hover:border-accent p-3.5 rounded-xl text-center text-sm font-semibold transition-all duration-200 truncate block shadow-md hover:shadow-rose-600/30 hover:scale-[1.02] {% if ep_s == ep_slug %}ring-2 ring-accent bg-accent/10{% endif %}">
                                        <span class="text-gray-300 group-hover:text-white truncate block">{{ ep_t }}</span>
                                    </a>
                                {% endfor %}
                            </div>
                        </div>
                    {% endfor %}
                </div>
            {% elif episodes %}
                <div class="mt-8 bg-cardbg p-6 sm:p-8 rounded-3xl border border-gray-800 shadow-2xl">
                    <h3 class="text-xl font-bold text-white mb-6 border-b border-gray-800 pb-4">Tüm Bölümler</h3>
                    <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3 max-h-[500px] overflow-y-auto pr-2 p-1">
                        {% for ep_s, ep_t in episodes %}
                            <a href="/watch?slug={{ watch_slug }}&ep={{ ep_s }}&title={{ ep_t|urlencode }}" 
                               class="group bg-darker hover:bg-gradient-to-r hover:from-accent hover:to-rose-600 border border-gray-800/80 hover:border-accent p-3.5 rounded-xl text-center text-sm font-semibold transition-all duration-200 truncate block shadow-md hover:shadow-rose-600/30 hover:scale-[1.02] {% if ep_s == ep_slug %}ring-2 ring-accent bg-accent/10{% endif %}">
                                <span class="text-gray-300 group-hover:text-white truncate block">{{ ep_t }}</span>
                            </a>
                        {% endfor %}
                    </div>
                </div>
            {% endif %}

        {% elif query %}
            <div class="mb-6">
                <h2 class="text-2xl font-bold text-white">Arama Sonuçları: <span class="text-accent">"{{ query }}"</span></h2>
            </div>
            <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-6">
                {% for item in results %}
                    <a href="/?slug={{ item[0] }}" class="group bg-cardbg rounded-2xl overflow-hidden border border-gray-800 hover:border-accent transition flex flex-col shadow-xl card-glow">
                        <div class="relative aspect-[2/3] overflow-hidden bg-darker">
                            <img src="/api/cover?title={{ item[1]|urlencode }}" alt="{{ item[1] }}" class="w-full h-full object-cover group-hover:scale-105 transition duration-500" loading="lazy">
                        </div>
                        <div class="p-3 flex-1">
                            <h3 class="text-xs font-bold group-hover:text-accent transition line-clamp-2 text-white">{{ item[1] }}</h3>
                        </div>
                    </a>
                {% endfor %}
            </div>

        {% else %}
            <!-- Homepage -->
            <section id="recent-watched-section" class="mb-12 hidden">
                <div class="flex justify-between mb-6">
                    <h2 class="text-2xl font-black text-white">Son İzlenenler</h2>
                    <button onclick="clearAllHistory()" class="text-xs text-gray-400 hover:text-accent">Geçmişi Temizle</button>
                </div>
                <div id="recent-watched-container" class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-5"></div>
            </section>

            <section class="mb-12">
                <h2 class="text-2xl font-black text-white mb-6">Popüler Animeler</h2>
                <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-6">
                    {% for item in popular_catalog %}
                        <a href="/?slug={{ item[0] }}" class="group bg-cardbg rounded-2xl overflow-hidden border border-gray-800/80 hover:border-accent transition flex flex-col shadow-xl card-glow">
                            <div class="relative aspect-[2/3] overflow-hidden bg-darker">
                                <img src="/api/cover?title={{ item[1]|urlencode }}" alt="{{ item[1] }}" class="w-full h-full object-cover group-hover:scale-105 transition duration-500" loading="lazy">
                            </div>
                            <div class="p-3.5 flex-1 flex flex-col justify-between">
                                <h3 class="text-xs font-bold group-hover:text-accent transition line-clamp-2 text-white">{{ item[1] }}</h3>
                            </div>
                        </a>
                    {% endfor %}
                </div>
            </section>
        {% endif %}
    </main>

    <footer class="bg-cardbg border-t border-gray-800/80 py-8 px-6 text-center text-xs text-gray-500 mt-auto">
        <p class="font-semibold text-gray-400 mb-1">⚡ ANIMEHUB Localhost Streaming</p>
        <p>Animecix & Ecchicix & Live Providers</p>
        <p class="mt-2">
            <a href="/update-catalog" class="text-gray-500 hover:text-accent transition" title="Kataloğu güncelle">🔄 Kataloğu Güncelle</a>
        </p>
    </footer>

    <script>
        function renderRecentlyWatched() {
            const container = document.getElementById('recent-watched-container');
            const section = document.getElementById('recent-watched-section');
            if (!container || !section) return;
            try {
                let history = JSON.parse(localStorage.getItem('animehub_history') || '[]');
                if (history.length === 0) { section.classList.add('hidden'); return; }
                section.classList.remove('hidden');
                container.innerHTML = history.map(item => `
                    <div class="relative group bg-cardbg rounded-2xl overflow-hidden border border-gray-800 hover:border-accent transition-all duration-300 shadow-xl flex flex-col">
                        <div class="relative aspect-[2/3] overflow-hidden bg-darker">
                            <img src="${item.cover}" alt="${item.anime_title}" class="w-full h-full object-cover group-hover:scale-105 transition duration-500" loading="lazy">
                            <button onclick="removeFromHistory('${item.slug}', event)" title="Kaldır" 
                                class="absolute top-2 right-2 bg-black/80 hover:bg-accent text-white w-6 h-6 rounded-full text-xs font-bold flex items-center justify-center transition shadow-md z-10">✕</button>
                            <div class="absolute bottom-2 left-2 right-2">
                                <span class="inline-block bg-accent/90 text-white text-[10px] font-black px-2 py-0.5 rounded shadow mb-1">${item.ep_title}</span>
                                <h3 class="text-xs font-bold text-white truncate">${item.anime_title}</h3>
                            </div>
                        </div>
                        <a href="/watch?slug=${item.slug}&ep=${item.ep_slug}&title=${encodeURIComponent(item.ep_title)}" 
                           class="bg-accent/10 hover:bg-accent text-accent hover:text-white text-xs font-bold py-2 text-center transition flex items-center justify-center gap-1">
                            <span>▶</span> Devam Et
                        </a>
                    </div>
                `).join('');
            } catch(e) { console.error('History render error:', e); }
        }
        function removeFromHistory(slug, event) {
            if (event) event.stopPropagation();
            let history = JSON.parse(localStorage.getItem('animehub_history') || '[]');
            history = history.filter(item => item.slug !== slug);
            localStorage.setItem('animehub_history', JSON.stringify(history));
            renderRecentlyWatched();
        }
        function clearAllHistory() {
            localStorage.removeItem('animehub_history');
            renderRecentlyWatched();
        }
        document.addEventListener('DOMContentLoaded', renderRecentlyWatched);
        function switchSeason(s) {
            document.querySelectorAll('.season-content').forEach(el => el.classList.add('hidden'));
            document.querySelectorAll('.season-tab').forEach(el => el.classList.remove('active'));
            document.getElementById('season-' + s).classList.remove('hidden');
            document.getElementById('tab-' + s).classList.add('active');
        }
    </script>
</body>
</html>
"""

# ---------- Caching ----------
_anime_cache = OrderedDict()
CACHE_MAX = 50
CACHE_TTL = 600

def _extract_seasons(episodes):
    seasons = {}
    for slug, title in episodes:
        cix_match = re.match(r'^(\d+)-[\d\.]+$', str(slug))
        match = re.search(r'(\d+)[-]sezon|sezon[-](\d+)|[Ss](\d+)[Ee]', str(slug))
        if cix_match:
            season = int(cix_match.group(1))
        elif match:
            season = int(match.group(1) or match.group(2) or match.group(3))
        else:
            sm = re.search(r'(\d+)\.?\s*[Ss]ezon', str(title))
            season = int(sm.group(1)) if sm else 1
        seasons.setdefault(season, []).append((slug, title))
    return seasons

def _normalize_slug_from_title(title):
    slug = title.lower()
    slug = re.sub(r'[^a-z0-9]+', '-', slug)
    return slug.strip('-')

def _is_title_match(t1, t2):
    def normalize(t):
        t_str = str(t).lower()
        t_str = re.sub(r'\b(ova|ona|tv|movie|special|specials)\b', '', t_str)
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
        
    return False
def _merge_all_episodes_for_title(title):
    if not title:
        return []
    all_eps = {}

    def parse_sn_en(slug, ep_title):
        m = re.match(r'^(\d+)-([\d\.]+)$', str(slug))
        if m:
            return int(m.group(1)), float(m.group(2))
        sm = re.search(r'(\d+)\.?\s*[Ss]ezon', str(ep_title))
        season = int(sm.group(1)) if sm else 1
        em = re.search(r'(\d+)\s*\.?\s*[Bb]ölüm', str(ep_title))
        if not em:
            em = re.search(r'[Bb]ölüm\s*(\d+)', str(ep_title))
        if not em:
            nums = re.findall(r'(\d+)', str(ep_title))
            ep = float(nums[-1]) if nums else 0.0
        else:
            ep = float(em.group(1))
        return season, ep

    import concurrent.futures

    def fetch_local():
        try:
            results = animecix.Anime.arama_yap(title)
            for slug, res_title in results:
                if _is_title_match(res_title, title):
                    anime = animecix.Anime(slug=slug)
                    return anime.get_bolum_listesi() or []
        except Exception:
            pass
        return []

    def fetch_depo():
        try:
            from turkanime_api.sources import animedepo as animedepo_source
            slug = _normalize_slug_from_title(title)
            return [(f"animedepo:{ep_slug}", ep_title) for ep_slug, ep_title in (animedepo_source.get_anime_episodes(slug) or [])]
        except Exception:
            return []

    def fetch_live(prefix):
        try:
            if prefix == "tranime":
                results = tranime.search_tranime(title)[:3]
            elif prefix == "openani":
                results = openani.search_openani(title, limit=3)
            else:
                return []
            
            for slug, res_title in results:
                if _is_title_match(res_title, title):
                    details = live_chain.get_anime_details(f"{prefix}:{slug}")
                    if details and "episodes" in details:
                        return details["episodes"]
        except Exception:
            pass
        return []

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(fetch_local), executor.submit(fetch_depo)]
        for prefix in ["tranime", "openani"]:
            futures.append(executor.submit(fetch_live, prefix))
        
        for future in concurrent.futures.as_completed(futures):
            eps = future.result()
            for ep_slug, ep_title in eps:
                sn, en = parse_sn_en(ep_slug.split("/")[-1] if "animedepo" in ep_slug else ep_slug, ep_title)
                if (sn, en) not in all_eps:
                    all_eps[(sn, en)] = (ep_slug, ep_title)
                else:
                    if "animedepo" in ep_slug:
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
                source = slug.split(":")[0]
                class LiveAnime:
                    def __init__(self, slug, title, poster, summary):
                        self.slug = slug
                        self.title = title
                        self.info = {"Özet": summary, "Resim": poster}
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
                self.info = {"Özet": "Bu anime için detay bulunamadı.", "Resim": ""}
        anime = DummyAnime(slug, title)
        return anime, [], {}, "dummy"

    if not title:
        title = slug.replace("-", " ").title()

    merged_eps = _merge_all_episodes_for_title(title)
    
    # If live provider returned episodes not captured by merge, add them
    if live_episodes:
        existing_slugs = {e[0] for e in merged_eps}
        for ep_s, ep_t in live_episodes:
            if ep_s not in existing_slugs:
                merged_eps.append((ep_s, ep_t))

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

    # AnimeDepo
    try:
        from turkanime_api.sources import animedepo
        depo_results = animedepo.search_animedepo(query)
        for slug, title in depo_results:
            if title and title.lower() not in seen_titles:
                local.append((f"animedepo:{slug}", title))
                seen_titles.add(title.lower())
    except Exception:
        pass

    # Filter out sequels/OVAs if the root franchise is already in the results
    # Sort by length so the shortest title (root) comes first
    local.sort(key=lambda x: len(x[1]))
    
    filtered_local = []
    for item in local:
        slug, t = item
        t_lower = t.lower()
        is_extension = False
        
        for _, k in filtered_local:
            k_lower = k.lower()
            if t_lower.startswith(k_lower):
                if len(t_lower) == len(k_lower) or t_lower[len(k_lower)] in ' :;-.,!?':
                    is_extension = True
                    break
        
        if not is_extension:
            filtered_local.append(item)
            
    # Sort back by some relevance if needed? AnimeDepo already returns by relevance.
    # We can preserve the original order by doing a final pass
    original_order = {item[0]: i for i, item in enumerate(local)}
    filtered_local.sort(key=lambda x: original_order[x[0]])

    return filtered_local

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


# ---- Bağlantılı Seriler API'si ----
@app.route('/api/related', methods=['GET'])
def api_related():
    title = request.args.get('title')
    if not title:
        return jsonify({"error": "No title provided"}), 400
        
    query = '''
    query ($search: String, $id: Int) {
      Media(search: $search, id: $id, type: ANIME) {
        id
        title { romaji english }
        format
        relations {
          edges {
            relationType
            node {
              id
              title { romaji english }
              type
              format
            }
          }
        }
      }
    }
    '''
    
    try:
        from turkanime_api.sources import animedepo
        
        def fetch_media(search_title=None, media_id=None):
            vars = {}
            if search_title: vars['search'] = search_title
            if media_id: vars['id'] = media_id
            res = requests.post('https://graphql.anilist.co', json={'query': query, 'variables': vars}, timeout=5)
            if not res.ok: return None
            return res.json().get('data', {}).get('Media')
            
        def get_best_title(node):
            return node['title']['romaji'] or node['title']['english']

        # 1. Kök animeyi bul
        current_media = fetch_media(search_title=title)
        if not current_media: return jsonify([])
        
        for _ in range(4):
            prequel_edge = next((e for e in current_media.get('relations', {}).get('edges', []) 
                                 if e['relationType'] == 'PREQUEL' and e['node']['type'] == 'ANIME'), None)
            if prequel_edge:
                p_media = fetch_media(media_id=prequel_edge['node']['id'])
                if p_media: current_media = p_media
                else: break
            else:
                break
                
        # 2. Devam serilerini aşağı doğru tara
        timeline = []
        current_node = current_media
        for _ in range(6):
            if not current_node: break
            
            # Ana seriyi ekle
            timeline.append({
                'title': get_best_title(current_node),
                'relation': 'TV Series' if current_node.get('format') == 'TV' else str(current_node.get('format')),
                'is_main': True
            })
            
            edges = current_node.get('relations', {}).get('edges', [])
            
            # Yan hikayeleri / OVA'ları ekle
            for e in edges:
                if e['relationType'] in ['SIDE_STORY', 'OVA', 'SPIN_OFF'] and e['node']['type'] == 'ANIME':
                    fmt = e['node'].get('format', 'OVA')
                    timeline.append({
                        'title': get_best_title(e['node']),
                        'relation': f"{e['relationType'].replace('_', ' ').title()} ({fmt})",
                        'is_main': False
                    })
                    
            # Sonraki devam serisine geç
            sequel_edge = next((e for e in edges if e['relationType'] == 'SEQUEL' and e['node']['type'] == 'ANIME'), None)
            if sequel_edge:
                current_node = fetch_media(media_id=sequel_edge['node']['id'])
            else:
                break

        # 3. AnimeDepo ile eşleştir
        final_list = []
        for item in timeline:
            rel_title = item['title']
            depo_results = animedepo.search_animedepo(rel_title)
            found_slug = None
            found_title_matched = None
            
            for slug, d_title in depo_results:
                if _is_title_match(d_title, rel_title):
                    found_slug = f"animedepo:{slug}"
                    found_title_matched = d_title
                    break
                    
            if found_slug:
                # Yan hikaye ana anime ile aynıysa kopyaları önlemek için
                if not any(x['slug'] == found_slug for x in final_list):
                    final_list.append({
                        "relation": item['relation'],
                        "title": found_title_matched,
                        "slug": found_slug
                    })
                    
        return jsonify(final_list)
        
    except Exception as e:
        print("[Related] Error:", e)
        return jsonify([])
        data = res.json()
        media = data.get('data', {}).get('Media')
        if not media or not media.get('relations'): return jsonify([])
        
        edges = media['relations'].get('edges', [])
        valid_types = ['SEQUEL', 'PREQUEL', 'SIDE_STORY', 'SPIN_OFF', 'ALTERNATIVE', 'OVA']
        
        related_list = []
        from turkanime_api.sources import animedepo
        
        for edge in edges:
            rel_type = edge.get('relationType')
            node = edge.get('node', {})
            if node.get('type') != 'ANIME' or rel_type not in valid_types:
                continue
                
            romaji = node.get('title', {}).get('romaji')
            english = node.get('title', {}).get('english')
            rel_title = english or romaji
            if not rel_title: continue
            
            # Search animedepo
            found_slug = None
            found_title_matched = None
            depo_results = animedepo.search_animedepo(rel_title)
            
            for slug, d_title in depo_results:
                if _is_title_match(d_title, romaji) or _is_title_match(d_title, english):
                    found_slug = f"animedepo:{slug}"
                    found_title_matched = d_title
                    break
            
            if found_slug:
                # Format label
                fmt = node.get('format', 'TV')
                rel_label = f"{rel_type.replace('_', ' ').title()} ({fmt})"
                related_list.append({
                    "relation": rel_label,
                    "title": found_title_matched,
                    "slug": found_slug
                })
                
        return jsonify(related_list)
        
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

@app.route("/")
def index():
    query = request.args.get("q", "").strip()
    slug = request.args.get("slug")
    if slug:
        anime, eps, seasons, src = get_anime_detail(slug)
        if not anime: return "<pre>Anime bulunamadı</pre>", 404
        total_episodes = sum(len(v) for v in seasons.values()) if seasons else len(eps)
        return render_template('watch.html', selected_anime=anime, episodes=eps,
                                      seasons=seasons, total_episodes=total_episodes,
                                      source_name=src, query="", watch_slug=None)
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
        except Exception as e:
            return None, str(e)



    # 2. Local (animecix/ecchicix)
    try:
        anime = animecix.Anime(slug=slug)
        bolum = animecix.Bolum(slug=ep_slug, anime=anime)
        bolum.get_videos()
        if bolum._videos:
            for v in bolum._videos: v._provider = "animecix"
            return bolum, None
    except Exception as e:
        print(f"[build_bolum] Local error: {e}")

    return None, "Hiçbir sağlayıcıdan video bulunamadı."

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
    return None, "Çalışan video bulunamadı."

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
            fs = getattr(v, 'fansub', '') or 'Varsayılan'
            if fs not in grouped_videos:
                grouped_videos[fs] = OrderedDict()
            if v.player not in grouped_videos[fs]:
                grouped_videos[fs][v.player] = v

        vid, pick_err = pick_video(bolum, requested_player, requested_fansub)
        if vid is None:
            player_error = pick_err
        else:
            player_name = vid.player
            fansub_name = getattr(vid, 'fansub', '') or 'Varsayılan'
            try:
                stream_url, stream_kind = resolve_stream(vid)
                if not stream_url:
                    player_error = "Stream çözülemedi."
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

    return render_template('watch.html',
        selected_anime=anime_detail_obj, results=None,
        watch_slug=slug, ep_slug=ep_slug, ep_title=ep_title,
        anime_title=anime_title, query="",
        stream_url=stream_url, stream_kind=stream_kind,
        player_error=player_error, 
        current_player=player_name, current_fansub=fansub_name,
        grouped_videos=grouped_videos,
        next_ep_slug=next_ep_slug, next_ep_title=next_ep_title,
        seasons=seasons, episodes=merged_eps)

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
        return f"<pre>Güncelleme başlatılamadı: {e}</pre>"

if __name__ == "__main__":
    app.run(debug=True, port=5000)