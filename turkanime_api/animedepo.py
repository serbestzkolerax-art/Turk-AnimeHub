from curl_cffi import requests
import logging

from .objects import Anime as BaseAnime
from .objects import Bolum as BaseBolum
from .objects import Video as BaseVideo
from .objects import LogHandler
from . import bypass

BASE_URL = "https://gitlab.com/AnimeDepo/animedepo/-/raw/master"
USE_TURKANIME = False
_dizin = None

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def fetch_json(path):
    """AnimeDepo JSON dosyasını getir."""
    url = BASE_URL + "/" + path.lstrip("/")
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logging.error(f'Error fetching JSON from {url}: {e}')
        return None

def dizin():
    global _dizin
    if _dizin is None:
        _dizin = fetch_json("dizin.json")
    return _dizin

def dizin_anime(slug):
    for anime_grubu in dizin().get("index", {}).values():
        if slug in anime_grubu:
            return anime_grubu[slug]
    return {}

class Anime(BaseAnime):

    def fetch_info(self):
        data = fetch_json(f"animeler/{self.slug}/info.json")
        if data:
            self.info.update(data)
            self._title = data.get("title") or data.get("Başlık") or dizin_anime(self.slug).get("title") or self._title

    def get_bolum_listesi(self):
        data = fetch_json(f"animeler/{self.slug}/bolumler.json")
        if data:
            return [(slug, title) for slug, title in data]
        return []

    @staticmethod
    def get_anime_listesi():
        liste = []
        dizin_data = dizin()
        if dizin_data:
            for anime_grubu in dizin_data.get("index", {}).values():
                for slug, anime in anime_grubu.items():
                    liste.append((slug, anime["title"]))
        return liste

    @staticmethod
    def arama_yap(query):
        """AnimeDepo JSON index'inde arama yapar."""
        liste = []
        dizin_data = dizin()
        if not dizin_data:
            logging.error("Arama yapılamadı: Dizin verisi çekilemedi.")
            return liste
            
        query_lower = query.lower()
        for anime_grubu in dizin_data.get("index", {}).values():
            for slug, anime in anime_grubu.items():
                title = anime.get("title", "")
                # Hem başlıktan hem slug üzerinden arama yap
                if query_lower in title.lower() or query_lower in slug.lower():
                    liste.append((slug, title))
        return liste

    @property
    def bolumler(self):
        if not self._bolumler:
            for slug, title in self.get_bolum_listesi():
                self._bolumler.append(
                    Bolum(
                        slug=slug,
                        title=title,
                        anime=self,
                        parse_fansubs=self.parse_fansubs))
        return self._bolumler

class Bolum(BaseBolum):

    @property
    def html(self):
        raise NotImplementedError

    @property
    def fansubs(self):
        if not self._fansubs:
            self.get_videos()
            self._fansubs = list(dict.fromkeys(v.fansub for v in self._videos if v.fansub))
        return self._fansubs

    def get_videos(self):
        if self.anime is None:
            raise ValueError("Bölüm objesi anime objesinden yaratılmalıdır.")
        self._videos = []
        data = fetch_json(f"animeler/{self.anime.slug}/{self.slug}.json")
        if data:
            for item in data:
                if item.get("alive") is False:
                    continue
                if not USE_TURKANIME and not item.get("url"):
                    continue
                video_path = item.get("mask") or item.get("path") or item.get("url")
                if not video_path:
                    continue
                self._videos.append(Video(
                    self,
                    video_path,
                    player=item.get("player"),
                    fansub=item.get("fansub"),
                    mask=item.get("mask"),
                    url=item.get("url")))
        return self._videos

class Video(BaseVideo):

    def __init__(self, bolum, path, player=None, fansub=None, mask=None, url=None, log_handler=LogHandler):
        super().__init__(bolum, path, player=player, fansub=fansub, log_handler=log_handler)
        self.mask = mask
        self._url = url

    @property
    def url(self):
        if self._url is None and self.mask:
            bypass.get_session() 
            mask = self.mask if self.mask.startswith("http") else bypass.BASE_URL + self.mask
            self._url = bypass.unmask_real_url(mask, video=self)
            return self._url
        return super().url