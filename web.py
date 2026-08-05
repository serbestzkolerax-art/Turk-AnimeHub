import sys
import os
import traceback
import functools
import requests
import re
from urllib.parse import quote

# Robust import setup: walk upward from this file until we find a folder
# that actually contains the package, and add THAT to sys.path.
PACKAGE_NAME = "turkanime_api"

def _find_and_register_package_root(start_dir):
    d = start_dir
    for _ in range(5):  # don't walk up forever
        if os.path.isdir(os.path.join(d, PACKAGE_NAME)):
            sys.path.insert(0, d)
            return True
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return False

current_dir = os.path.dirname(os.path.abspath(__file__))
if not _find_and_register_package_root(current_dir):
    sys.path.insert(0, os.path.dirname(current_dir))
    sys.path.insert(0, current_dir)

# --- FALLBACK MOCKS FOR ENVIRONMENT COMPATIBILITY ---
try:
    import yt_dlp
except ImportError:
    from unittest.mock import MagicMock
    yt_mock = MagicMock()
    sys.modules['yt_dlp'] = yt_mock
    sys.modules['yt_dlp.networking'] = MagicMock()
    sys.modules['yt_dlp.networking.impersonate'] = MagicMock()

try:
    import Crypto
except ImportError:
    from unittest.mock import MagicMock
    crypto_mock = MagicMock()
    sys.modules['Crypto'] = crypto_mock
    sys.modules['Crypto.Cipher'] = MagicMock()
    sys.modules['Crypto.Util'] = MagicMock()
    sys.modules['Crypto.Util.Padding'] = MagicMock()

try:
    import curl_cffi
except ImportError:
    import requests
    from unittest.mock import MagicMock
    
    class DummySession(requests.Session):
        def __init__(self, *args, impersonate=None, verify=None, **kwargs):
            super().__init__(*args, **kwargs)
            
    curl_requests = MagicMock()
    curl_requests.Session = DummySession
    curl_requests.get = requests.get
    curl_requests.post = requests.post
    curl_mock = MagicMock()
    curl_mock.requests = curl_requests
    sys.modules['curl_cffi'] = curl_mock
    sys.modules['curl_cffi.requests'] = curl_requests

try:
    from turkanime_api import animedepo
    from turkanime_api import objects as turkanime_objects
    
    # Fast timeout wrapper to prevent Gitlab network hangs
    _orig_animedepo_get = animedepo.requests.get
    def _fast_animedepo_get(url, *args, **kwargs):
        kwargs['timeout'] = kwargs.get('timeout', 3)
        return _orig_animedepo_get(url, *args, **kwargs)
    animedepo.requests.get = _fast_animedepo_get
    animedepo.USE_TURKANIME = True
except ModuleNotFoundError as e:
    print(f"[FATAL] '{PACKAGE_NAME}' paketi bulunamadı: {e}")
    print(f"web.py konumu: {current_dir}")
    print(f"sys.path: {sys.path}")
    raise

from flask import Flask, render_template_string, request, redirect

app = Flask(__name__)

# --- MYANIMELIST COVER FETCHING WITH CACHING ---
DEFAULT_COVER = "https://images.unsplash.com/photo-1578632767115-351597cf2477?w=400&q=80"

@functools.lru_cache(maxsize=500)
def get_mal_cover(title):
    """MyAnimeList API üzerinden yüksek çözünürlüklü kapak fotoğrafı çeker."""
    if not title:
        return DEFAULT_COVER
    
    clean_title = re.sub(r'-(izle|bolum|bölüm|\d+.*)', '', str(title), flags=re.IGNORECASE).strip()
    clean_title = re.sub(r'[^\w\s]', ' ', clean_title).strip()
    if not clean_title:
        clean_title = str(title)
        
    try:
        url = f"https://myanimelist.net/search/prefix.json?type=anime&keyword={quote(clean_title)}&v=1"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        resp = requests.get(url, headers=headers, timeout=2.5)
        if resp.status_code == 200:
            data = resp.json()
            categories = data.get("categories", [])
            if categories and categories[0].get("items"):
                img_url = categories[0]["items"][0].get("image_url", "")
                if img_url:
                    full_res_img = re.sub(r'/r/\d+x\d+', '', img_url)
                    return full_res_img
    except Exception as e:
        print(f"[MAL Cover error for '{title}']: {e}")
        
    return DEFAULT_COVER

@app.route("/api/cover")
def cover_api():
    """Asenkron kapak resmi yönlendiricisi (Sayfa yüklemesini hızlandırır)."""
    title = request.args.get("title", "").strip()
    cover_url = get_mal_cover(title)
    return redirect(cover_url)

HTML_TEMPLATE = """
<!DOCTYPE html>
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
                    fontFamily: {
                        sans: ['Inter', 'sans-serif'],
                    },
                    colors: {
                        darker: '#0a0d14',
                        cardbg: '#121722',
                        cardhover: '#1a202c',
                        accent: '#e11d48',
                        accentglow: '#ff2a55',
                    }
                }
            }
        }
    </script>
    <style>
        ::-webkit-scrollbar {
            width: 8px;
            height: 8px;
        }
        ::-webkit-scrollbar-track {
            background: #0a0d14;
        }
        ::-webkit-scrollbar-thumb {
            background: #232a3b;
            border-radius: 4px;
        }
        ::-webkit-scrollbar-thumb:hover {
            background: #e11d48;
        }
        .card-glow:hover {
            box-shadow: 0 10px 30px -10px rgba(225, 29, 72, 0.4);
        }
        .text-glow {
            text-shadow: 0 0 12px rgba(225, 29, 72, 0.6);
        }
    </style>
</head>
<body class="bg-darker text-gray-100 font-sans min-h-screen selection:bg-accent selection:text-white flex flex-col">
    <!-- Top Navbar -->
    <nav class="bg-cardbg/95 backdrop-blur-md border-b border-gray-800/80 sticky top-0 z-50 px-4 sm:px-8 py-3.5 flex items-center justify-between shadow-2xl">
        <div class="flex items-center gap-8">
            <a href="/" class="text-2xl font-black tracking-wider text-accent flex items-center gap-2 group">
                <span class="text-3xl transform group-hover:scale-110 transition duration-300">⚡</span>
                <span class="bg-gradient-to-r from-accent via-rose-400 to-white bg-clip-text text-transparent">ANIME</span><span class="text-white">HUB</span>
            </a>
            <div class="hidden md:flex items-center gap-6 text-sm font-semibold text-gray-300">
                <a href="/" class="hover:text-accent transition flex items-center gap-1.5">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6"/></svg>
                    Ana Sayfa
                </a>
            </div>
        </div>

        <form action="/" method="GET" class="flex items-center gap-2 w-full max-w-md ml-4">
            <div class="relative w-full">
                <input type="text" name="q" value="{{ query }}" placeholder="Anime ara (örn. Naruto, One Piece)..." 
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

    <!-- Main Container -->
    <main class="max-w-7xl mx-auto px-4 sm:px-6 py-8 flex-1 w-full">

        {% if selected_anime %}
            <!-- Detail View -->
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
                        <div class="absolute top-3 left-3 bg-black/70 backdrop-blur px-2.5 py-1 rounded-lg text-xs font-bold text-amber-400 flex items-center gap-1 border border-amber-400/30">
                            ★ {{ selected_anime.info.get('Puanı', '8.5') }}
                        </div>
                    </div>
                </div>

                <div class="md:col-span-3 flex flex-col justify-between">
                    <div>
                        <div class="flex flex-wrap items-center gap-3 mb-3">
                            <span class="bg-accent/20 border border-accent/40 text-accent font-bold text-xs px-3 py-1 rounded-full uppercase tracking-wider">
                                {{ selected_anime.info.get('Tür', 'TV Serisi') }}
                            </span>
                            <span class="bg-gray-800 text-gray-300 text-xs px-3 py-1 rounded-full font-medium">
                                Kaynak: {{ source_name or 'AnimeDepo & Turkanime' }}
                            </span>
                        </div>

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
                        <span>Bölüm Sayısı: <strong class="text-accent">{{ episodes|length }} Bölüm</strong></span>
                    </div>
                </div>
            </div>

            <!-- Episodes Grid Section -->
            <div class="mt-10">
                <div class="flex items-center justify-between mb-6">
                    <h2 class="text-2xl font-bold text-white flex items-center gap-3">
                        <span class="w-2 h-7 bg-accent rounded-full inline-block"></span>
                        Bölümler Listesi
                    </h2>
                    <span class="text-xs text-gray-400 bg-cardbg px-3 py-1.5 rounded-lg border border-gray-800">
                        Toplam {{ episodes|length }} Bölüm
                    </span>
                </div>

                <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3 max-h-[500px] overflow-y-auto pr-2 p-1">
                    {% if episodes %}
                        {% for ep in episodes %}
                            {% set ep_slug_val = ep.get('slug') if ep is mapping else ep[0] %}
                            {% set ep_title_val = ep.get('title') if ep is mapping else ep[1] %}
                            <a href="/watch?slug={{ selected_anime.slug }}&ep={{ ep_slug_val }}&title={{ ep_title_val|urlencode }}" 
                               class="group bg-cardbg hover:bg-gradient-to-r hover:from-accent hover:to-rose-600 border border-gray-800/80 hover:border-accent p-3.5 rounded-xl text-center text-sm font-semibold transition-all duration-200 truncate block shadow-md hover:shadow-rose-600/30 hover:scale-[1.02]">
                                <span class="text-gray-300 group-hover:text-white truncate block">
                                    {{ ep_title_val }}
                                </span>
                            </a>
                        {% endfor %}
                    {% else %}
                        <div class="col-span-full bg-cardbg p-8 rounded-2xl text-center border border-gray-800">
                            <p class="text-gray-400 mb-2">⚠️ Bu seriye ait bölüm bilgisi sunucudan çekilemedi.</p>
                        </div>
                    {% endif %}
                </div>
            </div>

        {% elif watch_slug %}
            <!-- Watch View -->
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
                    {% if player_name %}
                        <span class="inline-flex items-center gap-2 bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 text-xs px-3.5 py-1.5 rounded-full font-semibold self-start sm:self-auto">
                            <span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
                            Aktif Kaynak: {{ player_name }}
                        </span>
                    {% endif %}
                </div>

                {% if stream_url %}
                    <div class="bg-black rounded-2xl overflow-hidden mb-6 aspect-video shadow-2xl border border-gray-800 relative">
                        {% if stream_kind == "video" %}
                            <video id="player" src="{{ stream_url }}" controls autoplay class="w-full h-full"></video>
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
                        <p class="text-xs text-gray-400 mb-4">Seçilen video oynatıcı yanıt vermedi. Lütfen aşağıdaki alternatif kaynakları deneyin.</p>
                        {% if player_error %}<pre class="text-left text-xs bg-black/60 p-4 rounded-xl text-red-300 overflow-x-auto whitespace-pre-wrap font-mono">{{ player_error }}</pre>{% endif %}
                    </div>
                {% endif %}

                {% if other_players %}
                    <div class="border-t border-gray-800/80 pt-6">
                        <h3 class="text-xs font-bold text-gray-400 uppercase tracking-wider mb-3">Alternatif Oynatıcı Kaynakları:</h3>
                        <div class="flex flex-wrap gap-2.5">
                            {% for p in other_players %}
                                <a href="/watch?slug={{ watch_slug }}&ep={{ ep_slug }}&title={{ ep_title|urlencode }}&player={{ p }}"
                                   class="text-xs font-bold px-4 py-2 rounded-xl border transition-all duration-200 flex items-center gap-1.5 {{ 'bg-accent border-accent text-white shadow-lg shadow-rose-600/30' if p == player_name else 'bg-darker hover:bg-gray-800 border-gray-700 text-gray-300' }}">
                                    <span>▶</span> {{ p }}
                                </a>
                            {% endfor %}
                        </div>
                    </div>
                {% endif %}
            </div>

            <!-- Client-side History Saver -->
            <script>
                (function() {
                    try {
                        const historyItem = {
                            slug: {{ watch_slug|tojson }},
                            ep_slug: {{ ep_slug|tojson }},
                            ep_title: {{ ep_title|tojson }},
                            anime_title: {{ (anime_title or watch_slug)|tojson }},
                            cover: "/api/cover?title=" + encodeURIComponent({{ (anime_title or watch_slug)|tojson }}),
                            timestamp: new Date().getTime()
                        };
                        let history = JSON.parse(localStorage.getItem('animehub_history') || '[]');
                        history = history.filter(item => !(item.slug === historyItem.slug && item.ep_slug === historyItem.ep_slug));
                        history.unshift(historyItem);
                        history = history.slice(0, 15);
                        localStorage.setItem('animehub_history', JSON.stringify(history));
                    } catch(e) {
                        console.error('History save error:', e);
                    }
                })();
            </script>

        {% elif query %}
            <!-- Search Results View -->
            <div class="mb-6 flex items-center justify-between">
                <h2 class="text-2xl font-bold text-white">
                    Arama Sonuçları: <span class="text-accent font-extrabold">"{{ query }}"</span>
                </h2>
                <a href="/" class="text-xs font-semibold text-gray-400 hover:text-white">Filtreyi Temizle</a>
            </div>

            <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-6">
                {% if results %}
                    {% for item in results %}
                        {% set item_slug = item.get('slug') if item is mapping else item[0] %}
                        {% set item_title = item.get('title') if item is mapping else item[1] %}
                        <a href="/?slug={{ item_slug }}" class="group bg-cardbg rounded-2xl overflow-hidden border border-gray-800 hover:border-accent transition-all duration-300 flex flex-col shadow-xl card-glow">
                            <div class="relative aspect-[2/3] overflow-hidden bg-darker">
                                <img src="/api/cover?title={{ item_title|urlencode }}" alt="{{ item_title }}" class="w-full h-full object-cover group-hover:scale-105 transition duration-500" loading="lazy">
                                <div class="absolute inset-0 bg-gradient-to-t from-darker via-transparent to-transparent opacity-80"></div>
                                <span class="absolute top-2 right-2 bg-black/70 backdrop-blur text-amber-400 text-[11px] font-bold px-2 py-0.5 rounded border border-amber-400/20">
                                    ★ MAL
                                </span>
                            </div>
                            <div class="p-4 flex-1 flex flex-col justify-between">
                                <h3 class="text-sm font-bold group-hover:text-accent transition line-clamp-2 text-white leading-snug mb-2">
                                    {{ item_title }}
                                </h3>
                                <span class="text-[11px] text-gray-400 font-semibold group-hover:text-rose-400 transition">
                                    İzlemek için tıkla →
                                </span>
                            </div>
                        </a>
                    {% endfor %}
                {% else %}
                    <div class="col-span-full bg-cardbg p-12 rounded-3xl text-center border border-gray-800">
                        <div class="text-4xl mb-3">🔍</div>
                        <h3 class="text-lg font-bold text-white mb-1">Aramanızla eşleşen anime bulunamadı</h3>
                        <p class="text-sm text-gray-400">Lütfen farklı kelimelerle (örn. "Naruto", "One Piece") tekrar arama yapın.</p>
                    </div>
                {% endif %}
            </div>

        {% else %}
            <!-- MAIN HOME PAGE (AnimeCix.tv Style) -->
            
            <!-- Hero Featured Banner Section -->
            {% if featured_anime %}
            <div class="relative rounded-3xl overflow-hidden mb-12 shadow-2xl border border-gray-800 bg-gradient-to-r from-darker via-cardbg to-darker">
                <div class="grid grid-cols-1 lg:grid-cols-12 items-center min-h-[380px] p-6 sm:p-10 relative z-10">
                    <div class="lg:col-span-7 flex flex-col justify-center">
                        <div class="flex items-center gap-3 mb-3">
                            <span class="bg-accent text-white font-black text-[10px] uppercase tracking-widest px-2.5 py-1 rounded-md shadow-md">
                                Öne Çıkan Anime
                            </span>
                            <span class="text-amber-400 text-xs font-bold flex items-center gap-1">
                                ★ {{ featured_anime.get('score', '9.1') }} MyAnimeList
                            </span>
                        </div>
                        <h1 class="text-3xl sm:text-5xl font-black text-white tracking-tight leading-tight mb-4 text-glow">
                            {{ featured_anime.title }}
                        </h1>
                        <p class="text-gray-300 text-sm leading-relaxed line-clamp-3 mb-6 max-w-xl">
                            {{ featured_anime.get('summary', 'Efsanevi anime serisini Full HD kalitede ve kesintisiz hemen izlemeye başla!') }}
                        </p>
                        <div class="flex items-center gap-4">
                            <a href="/?slug={{ featured_anime.slug }}" class="bg-gradient-to-r from-accent to-rose-600 hover:from-rose-600 hover:to-rose-700 text-white font-extrabold px-8 py-3.5 rounded-2xl text-sm shadow-xl shadow-rose-600/30 hover:scale-105 transition duration-200 flex items-center gap-2">
                                <svg class="w-5 h-5" fill="currentColor" viewBox="0 0 20 20"><path d="M6.3 2.841A1.5 1.5 0 004 4.11v11.78a1.5 1.5 0 002.3 1.269l9.344-5.89a1.5 1.5 0 000-2.538L6.3 2.84z"/></svg>
                                Hemen İzle
                            </a>
                            <a href="/?slug={{ featured_anime.slug }}" class="bg-gray-800/80 hover:bg-gray-700 text-gray-200 font-bold px-6 py-3.5 rounded-2xl text-sm border border-gray-700 transition">
                                Detaylar
                            </a>
                        </div>
                    </div>
                    <div class="lg:col-span-5 hidden lg:flex justify-center items-center p-4">
                        <div class="relative w-64 h-96 rounded-2xl overflow-hidden shadow-2xl border-2 border-accent/40 rotate-2 hover:rotate-0 transition duration-500">
                            <img src="/api/cover?title={{ featured_anime.title|urlencode }}" alt="{{ featured_anime.title }}" class="w-full h-full object-cover">
                            <div class="absolute inset-0 bg-gradient-to-t from-black/80 via-transparent to-transparent"></div>
                        </div>
                    </div>
                </div>
            </div>
            {% endif %}

            <!-- Recently Watched (Son İzlenenler) Section -->
            <section id="recent-watched-section" class="mb-12 hidden">
                <div class="flex items-center justify-between mb-6">
                    <h2 class="text-2xl font-black text-white flex items-center gap-3">
                        <span class="w-2.5 h-7 bg-rose-500 rounded-full inline-block"></span>
                        Son İzlenenler
                    </h2>
                    <button onclick="clearAllHistory()" class="text-xs text-gray-400 hover:text-accent transition font-semibold">
                        Geçmişi Temizle
                    </button>
                </div>
                <div id="recent-watched-container" class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-5">
                    <!-- Dynamic JS Injection -->
                </div>
            </section>

            <!-- Popular Animes Section -->
            <section class="mb-12">
                <div class="flex items-center justify-between mb-6">
                    <h2 class="text-2xl font-black text-white flex items-center gap-3">
                        <span class="w-2.5 h-7 bg-accent rounded-full inline-block"></span>
                        Popüler Animeler (AnimeDepo Katalog)
                    </h2>
                    <span class="text-xs text-gray-400 font-medium">MyAnimeList Görselleri</span>
                </div>

                <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-6">
                    {% for item in popular_catalog %}
                        {% set item_slug = item[0] %}
                        {% set item_title = item[1] %}
                        <a href="/?slug={{ item_slug }}" class="group bg-cardbg rounded-2xl overflow-hidden border border-gray-800/80 hover:border-accent transition-all duration-300 flex flex-col shadow-xl card-glow">
                            <div class="relative aspect-[2/3] overflow-hidden bg-darker">
                                <img src="/api/cover?title={{ item_title|urlencode }}" alt="{{ item_title }}" class="w-full h-full object-cover group-hover:scale-105 transition duration-500" loading="lazy">
                                <div class="absolute inset-0 bg-gradient-to-t from-darker via-transparent to-transparent opacity-80"></div>
                                <div class="absolute top-2 right-2 bg-black/70 backdrop-blur px-2 py-0.5 rounded text-[10px] font-bold text-amber-400 border border-amber-400/20">
                                    ★ MAL
                                </div>
                            </div>
                            <div class="p-3.5 flex-1 flex flex-col justify-between">
                                <h3 class="text-xs font-bold group-hover:text-accent transition line-clamp-2 text-white leading-snug mb-1">
                                    {{ item_title }}
                                </h3>
                                <div class="flex items-center justify-between text-[10px] text-gray-400 mt-2 pt-2 border-t border-gray-800/60">
                                    <span class="text-accent font-bold">HD Türkçe</span>
                                    <span>İzlese →</span>
                                </div>
                            </div>
                        </a>
                    {% endfor %}
                </div>
            </section>

        {% endif %}
    </main>

    <!-- Footer -->
    <footer class="bg-cardbg border-t border-gray-800/80 py-8 px-6 text-center text-xs text-gray-500 mt-auto">
        <p class="font-semibold text-gray-400 mb-1">⚡ ANIMEHUB Localhost Streaming</p>
        <p>AnimeDepo JSON Index & Turkanime & MyAnimeList API Integration</p>
    </footer>

    <!-- Client-side History Renderer Script -->
    <script>
        function renderRecentlyWatched() {
            const container = document.getElementById('recent-watched-container');
            const section = document.getElementById('recent-watched-section');
            if (!container || !section) return;

            try {
                const history = JSON.parse(localStorage.getItem('animehub_history') || '[]');
                if (history.length === 0) {
                    section.classList.add('hidden');
                    return;
                }

                section.classList.remove('hidden');
                container.innerHTML = history.map(item => `
                    <div class="relative group bg-cardbg rounded-2xl overflow-hidden border border-gray-800 hover:border-accent transition-all duration-300 shadow-xl flex flex-col">
                        <div class="relative aspect-[2/3] overflow-hidden bg-darker">
                            <img src="${item.cover}" alt="${item.anime_title}" class="w-full h-full object-cover group-hover:scale-105 transition duration-500" loading="lazy">
                            <div class="absolute inset-0 bg-gradient-to-t from-darker via-black/30 to-transparent"></div>
                            <button onclick="removeFromHistory('${item.slug}', '${item.ep_slug}', event)" title="Geçmişten Kaldır" 
                                class="absolute top-2 right-2 bg-black/80 hover:bg-accent text-white w-6 h-6 rounded-full text-xs font-bold flex items-center justify-center transition shadow-md z-10">
                                ✕
                            </button>
                            <div class="absolute bottom-2 left-2 right-2">
                                <span class="inline-block bg-accent/90 text-white text-[10px] font-black px-2 py-0.5 rounded shadow mb-1">
                                    ${item.ep_title}
                                </span>
                                <h3 class="text-xs font-bold text-white truncate">${item.anime_title}</h3>
                            </div>
                        </div>
                        <a href="/watch?slug=${item.slug}&ep=${item.ep_slug}&title=${encodeURIComponent(item.ep_title)}" 
                           class="bg-accent/10 hover:bg-accent text-accent hover:text-white text-xs font-bold py-2 text-center transition flex items-center justify-center gap-1">
                            <span>▶</span> Devam Et
                        </a>
                    </div>
                `).join('');
            } catch(e) {
                console.error('History render error:', e);
            }
        }

        function removeFromHistory(slug, ep_slug, event) {
            if (event) event.stopPropagation();
            let history = JSON.parse(localStorage.getItem('animehub_history') || '[]');
            history = history.filter(item => !(item.slug === slug && item.ep_slug === ep_slug));
            localStorage.setItem('animehub_history', JSON.stringify(history));
            renderRecentlyWatched();
        }

        function clearAllHistory() {
            localStorage.removeItem('animehub_history');
            renderRecentlyWatched();
        }

        document.addEventListener('DOMContentLoaded', renderRecentlyWatched);
    </script>
</body>
</html>
"""

def get_anime_detail(slug):
    """AnimeDepo (öncelikli), Turkanime (ikincil) veya CLI title match ile detay çek."""
    # 1. Aşama: AnimeDepo slug doğrudan dene
    try:
        anime = animedepo.Anime(slug=slug)
        episodes = anime.get_bolum_listesi() or []
        if episodes or anime.info.get("Özet"):
            return anime, episodes, "AnimeDepo", None
    except Exception:
        print("[AnimeDepo detail error]\n" + traceback.format_exc())

    # 2. Aşama: Turkanime scrape dene
    try:
        anime = turkanime_objects.Anime(slug=slug)
        episodes = anime.get_bolum_listesi() or []
        if episodes:
            return anime, episodes, "Turkanime.co", None
    except Exception:
        print("[Turkanime detail error]\n" + traceback.format_exc())

    # 3. Aşama (CLI Tarzı Fallback): Turkanime patlarsa veya 0 bölüm dönerse, Animedepo dizininde başlığa göre arayıp eşleşen slug'ı bul!
    try:
        clean_query = slug.replace("-izle", "").replace("-", " ")
        matches = animedepo.Anime.arama_yap(clean_query)
        if matches:
            matched_slug = matches[0][0]
            anime = animedepo.Anime(slug=matched_slug)
            episodes = anime.get_bolum_listesi() or []
            if episodes:
                return anime, episodes, "AnimeDepo (Akıllı Eşleşme)", None
    except Exception:
        print("[Animedepo search fallback detail error]\n" + traceback.format_exc())

    return None, [], None, "Anime detay ve bölüm bilgileri sunucudan çekilemedi."


def run_search(query):
    """AnimeDepo indeksinde ara; boş dönerse turkanime.co aramasına düş."""
    try:
        results = animedepo.Anime.arama_yap(query)
        if results:
            return results, None
    except Exception:
        print("[AnimeDepo search error]\n" + traceback.format_exc())

    try:
        results = turkanime_objects.Anime.arama_yap(query) or []
        return results, None
    except Exception:
        err = traceback.format_exc()
        print("[Turkanime search error]\n" + err)
        return [], err


DEFAULT_POPULAR_ANIMES = [
    ("naruto-shippuuden-izle", "Naruto Shippuuden"),
    ("one-piece-izle", "One Piece"),
    ("shingeki-no-kyojin-izle", "Shingeki no Kyojin (Attack on Titan)"),
    ("kimetsu-no-yaiba-izle", "Kimetsu no Yaiba (Demon Slayer)"),
    ("jujutsu-kaisen-izle", "Jujutsu Kaisen"),
    ("bleach-izle", "Bleach"),
    ("death-note-izle", "Death Note"),
    ("hunter-x-hunter-2011-izle", "Hunter x Hunter"),
    ("boku-no-hero-academia-izle", "Boku no Hero Academia"),
    ("fullmetal-alchemist-brotherhood-izle", "Fullmetal Alchemist: Brotherhood"),
    ("tokyo-ghoul-izle", "Tokyo Ghoul"),
    ("solo-leveling-izle", "Solo Leveling"),
]

def get_homepage_data():
    """Ana sayfa için popüler seriler ve öne çıkan hero banner verisini anında hazırlar."""
    catalog = DEFAULT_POPULAR_ANIMES
    featured_item = catalog[0]
    featured = {
        "slug": featured_item[0],
        "title": featured_item[1],
        "score": "9.1",
        "summary": f"{featured_item[1]} efsanevi serisi yüksek çözünürlüklü görüntü kalitesi ve kesintisiz Türkçe alt yazı seçeneği ile AnimeHub'da sizleri bekliyor."
    }
    return catalog, featured


@app.route("/")
def index():
    query = request.args.get("q", "").strip()
    slug = request.args.get("slug")

    if slug:
        anime, episodes, source_name, err = get_anime_detail(slug)
        if anime is None:
            return f"<pre>Anime bilgisi alınamadı ({slug}):\n\n{err}</pre>", 502
        return render_template_string(
            HTML_TEMPLATE, selected_anime=anime, episodes=episodes, source_name=source_name,
            query="", watch_slug=None, featured_anime=None, popular_catalog=[])

    results = []
    if query:
        results, err = run_search(query)
        if err and not results:
            return f"<pre>Arama başarısız oldu:\n\n{err}</pre>", 502
        return render_template_string(
            HTML_TEMPLATE, results=results, selected_anime=None, query=query,
            watch_slug=None, featured_anime=None, popular_catalog=[])

    # Ana Sayfa Görünümü (Anında Yükleme)
    popular_catalog, featured_anime = get_homepage_data()
    return render_template_string(
        HTML_TEMPLATE, results=None, selected_anime=None, query="",
        watch_slug=None, featured_anime=featured_anime, popular_catalog=popular_catalog)


def build_bolum(slug, ep_slug):
    """Bölüm objesini AnimeDepo (öncelikli), turkanime scrape veya CLI fallback ile kur."""
    # 1. AnimeDepo doğrudan dene
    try:
        anime = animedepo.Anime(slug=slug)
        bolum = animedepo.Bolum(slug=ep_slug, anime=anime)
        bolum.get_videos()
        if bolum._videos:
            return bolum, None
    except Exception:
        print("[AnimeDepo bolum error]\n" + traceback.format_exc())

    # 2. Turkanime scrape dene
    try:
        anime = turkanime_objects.Anime(slug=slug)
        bolum = turkanime_objects.Bolum(slug=ep_slug, anime=anime)
        bolum.get_videos()
        if bolum._videos:
            return bolum, None
    except Exception:
        print("[Turkanime bolum error]\n" + traceback.format_exc())

    # 3. Akıllı CLI Fallback: Slug uyuşmazlığında AnimeDepo kataloğunda arama yapıp bölüm videosu çek
    try:
        clean_query = slug.replace("-izle", "").replace("-", " ")
        matches = animedepo.Anime.arama_yap(clean_query)
        if matches:
            matched_slug = matches[0][0]
            anime = animedepo.Anime(slug=matched_slug)
            bolum = animedepo.Bolum(slug=ep_slug, anime=anime)
            bolum.get_videos()
            if bolum._videos:
                return bolum, None
    except Exception:
        print("[AnimeDepo fallback bolum error]\n" + traceback.format_exc())

    return None, "Bölüm kaynak videoları hiçbir sağlayıcıdan (AnimeDepo & Turkanime) yüklenemedi."


def pick_video(bolum, requested_player=None):
    """Oynatıcı önceliğine göre sırala ve çalışan ilk videoyu bul."""
    vids = [v for v in bolum._videos if v.is_supported]
    if requested_player:
        matched = [v for v in vids if v.player == requested_player]
        if matched:
            vids = matched
    vids = sorted(
        vids,
        key=lambda v: turkanime_objects.SUPPORTED.index(v.player)
        if v.player in turkanime_objects.SUPPORTED else 99)
    last_error = None
    for v in vids:
        try:
            if v.is_working:
                return v, None
        except Exception:
            last_error = traceback.format_exc()
    return None, last_error or "Hiçbir kaynak çalışmıyor."


def resolve_stream(vid):
    """yt-dlp'nin çözdüğü doğrudan medya linkini çıkar."""
    info = vid.info or {}
    direct = info.get("url")
    candidate = direct or vid.url
    if not candidate:
        return None, None
    if ".m3u8" in candidate:
        return candidate, "hls"
    if info.get("ext") in ("mp4", "webm", "mkv", "m4v"):
        return candidate, "video"
    return candidate, "iframe"


@app.route("/watch")
def watch():
    slug = request.args.get("slug")
    ep_slug = request.args.get("ep")
    ep_title = request.args.get("title") or ep_slug
    requested_player = request.args.get("player")

    bolum, build_err = build_bolum(slug, ep_slug)
    if bolum is None:
        return f"<pre>Bölüm yüklenemedi:\n\n{build_err}</pre>", 502

    other_players = list(dict.fromkeys(v.player for v in bolum._videos if v.is_supported))

    stream_url, stream_kind, player_name, player_error = None, None, None, None
    vid, pick_err = pick_video(bolum, requested_player)
    if vid is None:
        player_error = pick_err
    else:
        player_name = vid.player
        try:
            stream_url, stream_kind = resolve_stream(vid)
            if not stream_url:
                player_error = "Kaynak linki çözülemedi."
        except Exception:
            player_error = traceback.format_exc()

    anime_title = slug.replace("-izle", "").replace("-", " ").title()

    return render_template_string(
        HTML_TEMPLATE, selected_anime=None, results=None,
        watch_slug=slug, ep_slug=ep_slug, ep_title=ep_title, anime_title=anime_title,
        query="", stream_url=stream_url, stream_kind=stream_kind,
        player_name=player_name, player_error=player_error,
        other_players=other_players, featured_anime=None, popular_catalog=[])

if __name__ == "__main__":
    app.run(debug=True, port=5000)