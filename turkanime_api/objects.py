from os import remove
from os.path import join
from tempfile import NamedTemporaryFile
from html import unescape
import subprocess as sp
import re
import json
import warnings
import logging
from yt_dlp import YoutubeDL
from yt_dlp.networking.impersonate import ImpersonateTarget
from functools import lru_cache   # <-- added

from .bypass import get_real_url, unmask_real_url, fetch, get_m3u8_stream


def parse_arama_sonuc(src):
    if not src:
        return []
        
    results = []
    results.extend(
        (slug, unescape(isim_))
        for slug, isim_ in re.findall(r'/anime/([^"\'>]+)["\'] [^>]*?title=["\']([^"\']+?) izle', src)
    )

    if results:
        return results

    for match in re.finditer(r'<a[^>]+href=["\']?/anime/([^"\'\s>]+)[^>]*title=["\']([^"\']+)[^>]*>', src, re.IGNORECASE):
        slug = match.group(1)
        title = unescape(match.group(2).strip())
        if slug and title:
            results.append((slug, title))

    if results:
        return results

    for match in re.finditer(r'href=["\']?/anime/([^"\'\s>]+)[^>]*>(.*?)</a>', src, re.IGNORECASE | re.DOTALL):
        slug = match.group(1)
        title = re.sub(r'<.*?>', '', match.group(2))
        title = unescape(title).strip()
        if slug and title:
            results.append((slug, title))

    return results

SUPPORTED = [
    "ANIMECIX",
    "YADISK", "ALUCARD(BETA)", "GDRIVE", "MAIL", "PIXELDRAIN",
    "AMATERASU(BETA)", "HDVID", "DAILYMOTION",
    "VK", "VIDMOLY", "YOURUPLOAD", "SENDVID", "MYVI", "UQLOAD",
]

class LogHandler:
    @staticmethod
    def error(msg): pass
    @staticmethod
    def warning(msg): pass
    @staticmethod
    def debug(msg): pass

class Anime:
    def __init__(self,slug,parse_fansubs=True):
        self.slug = slug
        self._title = None
        self.anime_id = 0
        self.info = {
            "Kategori":None, "Japonca":None, "Anime Türü":[],
            "Bölüm Sayısı":0, "Başlama Tarihi":None, "Bitiş Tarihi":None,
            "Stüdyo":None, "Puanı":0.0, "Özet":None, "Resim":None
        }
        self.fetch_info()
        self._bolumler_data = None
        self._bolumler = []
        self.parse_fansubs = parse_fansubs

    def fetch_info(self):
        src = fetch(f'/anime/{self.slug}')
        if not src:
            return
        try:
            id_match = re.search(r'animeId\s*=\s*["\']?(\d+)', src)
            if id_match:
                self.anime_id = int(id_match.group(1))
            else:
                twitmeta = re.findall(r'twitter.image" content="(.*?serilerb/(.*?)\.jpg)"', src)
                if twitmeta:
                    self.info["Resim"], self.anime_id = twitmeta[0]

            if not self._title:
                title_match = re.findall(r'<title>(.*?)<\/title>', src)
                if title_match:
                    self._title = title_match[0].split(" izle")[0].strip()

            info_table_match = re.findall(r'<div id="animedetay">(<table.*?</table>)', src)
            if info_table_match:
                info_table = info_table_match[0]
                raw_m = re.findall(r"<tr>.*?<b>(.*?)<\/b>.*?width.*?>(.*?)<\/td>.*?<\/tr>", info_table)
                for key, val in raw_m:
                    if key not in self.info: 
                        continue
                    val = re.sub("<.*?>", "", val)
                    val = re.sub("^ {1,3}", "", val)
                    if key == "Puanı": 
                        try:
                            val = float(re.findall("^(.*?) ", val).pop())
                        except Exception:
                            val = 0.0
                    elif key == "Anime Türü": 
                        val = val.split("  ")
                    self.info[key] = val
                
                ozet_match = re.findall(r'"ozet">(.*?)</p>', info_table)
                if ozet_match:
                    self.info["Özet"] = ozet_match[0]
        except Exception as e:
            logging.error(f"Anime info çekilirken hata: {e}")

    def get_bolum_listesi(self):
        src = fetch(f'/anime/{self.slug}')
        if not src: 
            return []
            
        bolumler = re.findall(r'href=["\']?/video/([^"\'>]+)["\'][^>]*>(.*?)<\/a>', src)
        if bolumler:
            seen = set()
            temiz_liste = []
            for slug, title in bolumler:
                if slug not in seen and ("bolum" in slug or "-" in slug):
                    seen.add(slug)
                    clean_title = re.sub(r'<.*?>', '', title).strip()
                    temiz_liste.append((slug, unescape(clean_title or slug)))
            if temiz_liste:
                return temiz_liste

        anime_id = self.anime_id
        if not anime_id or anime_id == 0:
            id_match = re.search(r'animeId\s*=\s*["\']?(\d+)', src)
            if id_match:
                anime_id = int(id_match.group(1))
                
        if not anime_id or anime_id == 0:
            return []

        ajax_src = fetch(f'/ajax/bolumler&animeId={anime_id}')
        if not ajax_src: return []
        return re.findall(r'\/video\/(.*?)\\?".*?title=\\?"(.*?)\\?" style=', ajax_src)
    
    @staticmethod
    def get_anime_listesi():
        warnings.warn(FutureWarning, stacklevel=2)
        src = fetch("/ajax/tamliste")
        if not src: return []
        return re.findall(r'\/anime\/(.*?)".*?animeAdi">(.*?)<',src)

    @staticmethod
    def arama_yap(query):
        src = fetch("/arama", data={"arama": query})
        if not src:
            logging.error("Arama isteği boş döndü (Bağlantı engellenmiş olabilir).")
            return []
            
        results = parse_arama_sonuc(src)
        if not results and re.search(r'window\.location\s*=\s*"?anime/([^"\']+)', src):
            slug = re.findall(r'window\.location\s*=\s*"?anime/([^"\']+)', src)
            if not slug:
                return []
            ani = Anime(slug[0])
            return [(ani.slug, ani.title)]
        return results

    @property
    def title(self):
        if self._title is None: self.fetch_info()
        return self._title

    @title.setter
    def title(self, value): self._title = value

    @property
    def bolumler(self):
        if not self._bolumler:
            for slug,title in self.get_bolum_listesi():
                self._bolumler.append(
                    Bolum(slug=slug, title=title, anime=self, parse_fansubs=self.parse_fansubs))
        return self._bolumler

class Bolum:
    def __init__(self,slug,anime=None,title=None,parse_fansubs=True):
        if "http" == slug[:4]: slug = slug.split("/")[-1]
        self.slug = slug
        self.parse_fansubs = parse_fansubs
        self._title = title
        self._html = None
        self._videos = []
        self._anime = anime
        self._fansubs = []

    @property
    def html(self):
        if self._html is None: self._html = fetch(f"/video/{self.slug}")
        return self._html or ""

    @property
    def title(self):
        if self._title is None and self.html:
            try:
                self._title = re.findall(r'<title>(.*?)<\/title>',self.html)[0]
            except IndexError:
                self._title = "Bilinmeyen Bölüm"
        return self._title

    @property
    def videos(self):
        if not self._videos:
            try: self.get_videos()
            except IndexError: self._videos = []
        return self._videos

    @property
    def anime(self):
        return self._anime

    @property
    def fansubs(self):
        if not self._fansubs and self.html:
            self._fansubs = re.findall(r"</span> ([^<>/]*?)</a></button>",self.html)
            if not self._fansubs:
                self._fansubs = re.findall(r"</span> ([^\\<>]*)</button>.*?iframe",self.html)
        return self._fansubs

    def get_videos(self):
        self._videos = []
        if not self.html: return self._videos
        
        if "birden fazla grup" not in self.html:
            fansub_match = re.findall(r"</span> ([^\\<>]*)</button>.*?iframe",self.html)
            fansub = fansub_match[0] if fansub_match else None
            vids = re.findall(r"/embed/#/url/(.*?)\?status=0\".*?</span> ([^ ]*?) ?</button>", self.html)
            vids += re.findall(r"(ajax\/videosec&b=[A-Za-z0-9]+&v=.*?)'.*?<\/span> ?(.*?)<\/button",self.html)
            for vpath,player in vids: self._videos.append(Video(self,vpath,player,fansub))
        elif self.parse_fansubs:
            fansubs = re.findall(r"(ajax\/videosec&.*?)'.*?<\/span> ?(.*?)<\/a>",self.html)
            for path,fansub in fansubs:
                src = fetch(path)
                if not src: continue
                vids = re.findall(r"/embed/#/url/(.*?)\?status=0\".*?</span> ([^ ]*?) ?</button>", src)
                vids += re.findall(r"(ajax\/videosec&b=[A-Za-z0-9]+&v=.*?)'.*?<\/span> ?(.*?)<\/button",src)
                for vpath,player in vids: self._videos.append(Video(self,vpath,player,fansub))
        else:
            allpath_match = re.findall(r"(ajax\/videosec&b=[A-Za-z0-9]+.*?)&[fv]=.*?'.*?<\/span>",self.html)
            if allpath_match:
                src = fetch(allpath_match[0])
                if src:
                    vids = re.findall(r"/embed/#/url/(.*?)\?status=0\".*?</span> ([^ ]*?) ?</button>", src)
                    vids += re.findall(r"(ajax\/videosec&b=[A-Za-z0-9]+&v=.*?)'.*?<\/span> ?(.*?)<\/button",src)
                    for vpath,player in vids: self._videos.append(Video(self,vpath,player))
        return self._videos

    def best_video(self, by_res=True, by_fansub=None, default_res=600, callback=lambda x:None):
        vids = list(filter(lambda x: x.is_supported, self.videos))
        hook_dict = {"current": None, "total": len(vids), "player": None, "status": None, "object": self}
        vids = sorted(vids, key = lambda x: (by_fansub and x.fansub != by_fansub, SUPPORTED.index(x.player) if x.player in SUPPORTED else 99))

        working_vids = []
        for i,vid in enumerate(vids,start=1):
            hook_dict.update({"current": i, "player": vid.player, "status": "üstbilgi çekiliyor"})
            callback(hook_dict)
            if not vid.is_working:
                hook_dict.update({"status": "çalışmıyor"})
                callback(hook_dict)
                continue
            working_vids.append(vid)
            resolution = vid.resolution or default_res
            if not by_res or resolution >= 1080:
                hook_dict.update({"current":len(vids), "status": "çalışıyor"})
                callback(hook_dict)
                return vid
                
        if not working_vids:
            hook_dict.update({"player": None, "status": "hiçbiri çalışmıyor"})
            callback(hook_dict)
            return None
            
        vid = max(working_vids, key = lambda x:x.resolution or default_res)
        hook_dict.update({"player": vid.player , "status": "çalışıyor"})
        callback(hook_dict)
        return vid


class Video:
    def __init__(self,bolum,path,player=None,fansub=None,log_handler=LogHandler):
        self.path = path
        self.player = player
        self.fansub = fansub
        self.bolum = bolum
        self._resolution = None
        self._info = None
        self._url = None
        self._is_working = None
        self.is_supported = self.player in SUPPORTED

        self.ydl_opts = {
          'logger': log_handler, 'quiet': True, 'ignoreerrors': 'only_download',
          'retries': 5, 'fragment_retries': 10, 'restrictfilenames': True,
          'nocheckcertificate': True, 'concurrent_fragment_downloads': 5,
        }
        if self.player == "ALUCARD(BETA)":
            self.ydl_opts['impersonate'] = ImpersonateTarget("chrome")

    @property
    def url(self):
        if self._url is None:
            cipher = None
            if "/" in self.path:
                src = fetch(self.path)
                if src:
                    cipher_m = re.findall(r"\/embed\/#\/url\/(.*?)\?status",src)
                    cipher = cipher_m[0] if cipher_m else None
                    if not cipher:
                        tmp = re.findall('<iframe src="(.*?)"',src)
                        self._url = tmp[0] if tmp else None
                        self.is_working = True if self._url else False
            else: 
                cipher = self.path
                
            if cipher:
                try:
                    plaintext = get_real_url(cipher)
                    self._url = json.loads(plaintext)
                except (json.JSONDecodeError, ValueError) as e:
                    logging.error(f"Şifre çözme hatası (JSON parse): {e}")
                except Exception as e:
                    logging.error(f"Şifre çözme hatası: {e}")
                    
            if self._url is None:
                self.is_working = False
                return None
                
            self._url = "https:"+ self._url if self._url.startswith("//") else self._url
            self._url = self._url.replace("uqload.io","uqload.com")
            if "turkanime" in self._url:
                self._url = unmask_real_url(self._url, video=self)
        return self._url

    @property
    def info(self):
        if self._info is None:
            if not self.is_supported or self.url is None:
                self._info = {}
                return self._info
            try:
                with YoutubeDL(self.ydl_opts) as ydl:
                    raw_info = ydl.extract_info(self.url, download=False)
                    info = ydl.sanitize_info(raw_info)
                if info and "direct" in info:
                    del info["direct"]
                if info and info.get("video_ext") == "html":
                    info = None
                self._info = info or {}
            except Exception:
                self._info = {}
        return self._info

    @property
    def resolution(self):
        if self._resolution is None:
            formats = self.info.get("formats")
            res = self.info.get("resolution")
            if res and re.search(r'\d{2,4}',str(res)):
                res = int(re.findall(r'\d{2,4}',str(res))[-1])
            elif formats:
                if "height" in formats[0]:
                    res = max(formats,key=lambda x:x.get("height") or 0).get("height")
                elif "format_id" in formats[0]:
                    fid = formats[0].get("format_id")
                    res = {"sd":480, "hd":720, "fhd": 1080, "hq":2160}.get(fid, 0)
            self._resolution = res or 0
        return self._resolution

    @resolution.setter
    def resolution(self, value): self._resolution = value

    @property
    def is_working(self):
        if not self.is_supported: return False
        if self._is_working is None:
            try:
                url = self.url
                if url is None or "turkanime" in url: raise LookupError
                self._is_working = self.info not in (None, {})
            except Exception:
                self._is_working = False
        return self._is_working

    @is_working.setter
    def is_working(self,value): self._is_working = value

    def indir(self, callback=None, output=""):
        assert self.is_working, "Video çalışmıyor."
        seri_slug = self.bolum.anime.slug if self.bolum.anime else ""
        output = join(output, seri_slug, self.bolum.slug)
        opts = self.ydl_opts.copy()
        if callback: opts['progress_hooks'] = [callback]
        opts['outtmpl'] = {'default': output + r'.%(ext)s'}
        with NamedTemporaryFile("w",delete=False) as tmp:
            json.dump(self.info, tmp)
        with YoutubeDL(opts) as ydl:
            ydl.download_with_info_file(tmp.name)
        remove(tmp.name)

    def oynat(self, dakika_hatirla=False, izlerken_kaydet=False, mpv_opts=None):
        if mpv_opts is None: mpv_opts = []
        assert self.is_working, "Video çalışmıyor."
        with NamedTemporaryFile("w",delete=False) as tmp:
            json.dump(self.info, tmp)

        if self.url.endswith(".m3u8"):
            cmd = [
                "mpv", "--no-input-terminal", "--msg-level=all=error",
                "--demuxer-lavf-o=protocol_whitelist=[file,tcp,tls,https],http_keep_alive=0,http_persistent=0",
                "--cache=yes", get_m3u8_stream(self.url)
            ]
        else:
            cmd = [
                "mpv", "--no-input-terminal", "--msg-level=all=error",
                "--script-opts=ytdl_hook-ytdl_path=yt-dlp,ytdl_hook-try_ytdl_first=yes",
                "--ytdl-raw-options=load-info-json=" + tmp.name,
                "ytdl://" + self.bolum.slug
            ]

        if dakika_hatirla: mpv_opts.append("--save-position-on-quit")
        if izlerken_kaydet: mpv_opts.append("--stream-record")
        for opt in mpv_opts: cmd.insert(1,opt)
        try:
            return sp.run(cmd, text=True, stdout=sp.PIPE, stderr=sp.PIPE)
        finally:
            try:
                remove(tmp.name)
            except OSError:
                pass