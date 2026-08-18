""" TürkAnimu Downloader """
from os import environ,name,path
from time import sleep
import sys
import atexit
import concurrent.futures as cf
from rich import print as rprint
from rich.live import Live
import questionary as qa
import traceback
import platform
from datetime import datetime
from curl_cffi import requests

try:
    from easygui import diropenbox
except ImportError:
    os_name = platform.system()
    rprint("[red][strong]python3-tk paketi sisteminizde eksik![/strong][/red]")
    if os_name == "Darwin":
        print("Kurmak için: brew install python-tk")
    else:
        print("Debian için örnek kurulum: sudo apt install python3-tk")
    input("(Programı Kapatmak İçin Enter'a Basın)")
    exit(1)

from ..bypass import fetch
from .. import bypass, animedepo
from .. import objects as turkanime
from .. import animecix
from .dosyalar import Dosyalar
from .gereksinimler import gereksinim_kontrol_cli
from .cli_tools import prompt_tema,clear,indirme_task_cli,VidSearchCLI,CliStatus,DownloadBoard,player_onceligi,player_onceligi_duzenle,player_onceligi_uygula
from .version import guncel_surum, update_type, __version__

MANIFEST_URL = "https://raw.githubusercontent.com/KebabLord/turkanime-indirici/refs/heads/master/manifest.json"
USE_ANIMEDEPO = True
SEARCH_FALLBACK = False
provider = None
Anime, Bolum = None, None


def provider_sec(yeni_provider):
    global provider, Anime, Bolum
    provider = yeni_provider
    Anime, Bolum = provider.Anime, provider.Bolum

# Default to animecix
try:
    provider_sec(animecix)
except Exception:
    provider_sec(animedepo)  # fallback

# Uygulama dizinini sistem PATH'ına ekle.
SEP = ";" if name=="nt" else ":"
environ["PATH"] +=  SEP + Dosyalar().ta_path + SEP


def log_error(e):
    """ Hata logunu error.log dosyasına yazar. """
    error_path = path.join(Dosyalar().ta_path, "error.log")
    with open(error_path, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now()}: {str(e)}\n{traceback.format_exc()}\n\n")


def eps_to_choices(liste,mark_type):
    assert len(liste) != 0 and isinstance(liste[0], Bolum)
    slug = liste[0].anime.slug
    recent, choices, gecmis = None, [], []
    gecmis_ = Dosyalar().gecmis
    if slug in gecmis_[mark_type]:
        gecmis = gecmis_[mark_type][slug]
        recent = gecmis[-1]
    for bolum in liste:
        isim = str(bolum.title)
        if bolum.slug in gecmis:
            isim += " ●"
        choice = qa.Choice(isim,bolum)
        if bolum.slug == recent:
            recent = choice
        choices.append(choice)
    return choices, recent


def fansub_sec(anime):
    try:
        with CliStatus("Fansub listesi getiriliyor.."):
            fansubs = animedepo.Anime(anime.slug).info.get("fansubs") or []
    except Exception:
        return True,None
    if len(fansubs) <= 1:
        return True,None
    sub = qa.select(
        message='Fansub seç',
        choices=["(Fark etmez)"] + fansubs,
        style=prompt_tema,
    ).ask(kbi_msg="")
    if sub is None:
        return False,None
    if sub == "(Fark etmez)":
        return True,None
    return True,sub


def son_anime_sec(dosya):
    son_anime = dosya.last_anime
    if not isinstance(son_anime,dict):
        return "ara",None
    title = son_anime.get("title")
    slug = son_anime.get("slug")
    if not title or not slug:
        return "ara",None
    secim = qa.select(
        "Anime seç",
        choices=[
            qa.Choice(f"Devam et: {title}",("devam",slug)),
            qa.Choice("Anime ara",("ara",None)),
            qa.Choice("Geri dön",("geri",None)),
        ],
        style=prompt_tema,
        instruction=" "
    ).ask()
    return secim or ("geri",None)


def search_all_providers(query):
    """Search across all providers and return list of (slug, title, provider_name)."""
    results = []
    for prov in [animedepo, turkanime, animecix]:
        try:
            res = prov.Anime.arama_yap(query)
            if res:
                for slug, title in res:
                    results.append((slug, title, prov.__name__))
        except Exception:
            continue
    # Deduplicate by title (keep first)
    seen = set()
    unique = []
    for slug, title, prov_name in results:
        if title not in seen:
            seen.add(title)
            unique.append((slug, title, prov_name))
    # Sort so animecix appears first
    unique.sort(key=lambda x: 0 if x[2] == "animecix" else 1)
    return unique


def menu_loop():
    while True:
        clear()
        islem = qa.select(
            "İşlemi seç",
            choices=['Anime izle',
                    'Anime indir',
                    'Ayarlar',
                    'Kapat'],
            style=prompt_tema,
            instruction=" "
        ).ask()
        if not islem:
            break
        # Anime izle veya indir seçildiyse.
        if "Anime" in islem:
            dosya = Dosyalar()
            secim, seri_slug = son_anime_sec(dosya)
            if secim == "geri":
                continue
            if secim == "ara":
                arama_metni = qa.text(
                    'Animeyi yazın',
                    style=prompt_tema
                ).ask()
                if not arama_metni:
                    continue
                with CliStatus(f"'{arama_metni}' için tüm kaynaklarda aranıyor.."):
                    all_results = search_all_providers(arama_metni)
                if not all_results:
                    rprint("[red][strong]Aradığınız anime bulunamadı.[/strong][/red]")
                    sleep(1.5)
                    continue

                choices = [qa.Choice(f"{title} ({prov})", (slug, prov)) for slug, title, prov in all_results]
                selected = qa.select(
                    'Bulunan sonuçlardan birini seçin:',
                    choices=choices,
                    style=prompt_tema,
                    instruction="(Ok tuşlarını kullan)"
                ).ask()
                if selected is None:
                    continue
                seri_slug, selected_provider = selected
                # Set provider to the selected one
                if selected_provider == "animedepo":
                    provider_sec(animedepo)
                elif selected_provider == "turkanime":
                    provider_sec(turkanime)
                elif selected_provider == "animecix":
                    provider_sec(animecix)
                else:
                    provider_sec(animecix)  # fallback
                # Save last anime with title
                for s, t, p in all_results:
                    if s == seri_slug:
                        dosya.set_last_anime(seri_slug, t)
                        break
            else:
                # Continue with last anime – use current provider (which may be from previous selection)
                pass

            # Now we have the anime slug and provider set
            anime = Anime(seri_slug)

            while True:
                dosya = Dosyalar()
                if "izle" in islem:
                    with CliStatus("Bölümler getiriliyor.."):
                        bolumler = anime.bolumler
                    if not bolumler:
                        rprint("[red][strong]Bu anime için bölüm bulunamadı.[/strong][/red]")
                        sleep(1.5)
                        break
                    choices, recent = eps_to_choices(bolumler, mark_type="izlendi")
                    bolum = qa.select(
                        message='Bölüm seç',
                        choices=choices,
                        style=prompt_tema,
                        default=recent,
                        instruction="(Ok tuşlarını kullan)"
                    ).ask(kbi_msg="")
                    if not bolum:
                        break
                    fansubs, sub = bolum.fansubs, None
                    if dosya.ayarlar["manuel fansub"] and len(fansubs) > 1:
                        sub = qa.select(
                            message='Fansub seç',
                            choices=["(Fark etmez)"] + fansubs,
                            style=prompt_tema,
                        ).ask(kbi_msg="")
                        if sub is None:
                            break
                        if sub == "(Fark etmez)":
                            sub = None
                    # En iyi videoyu bul ve oynat, 3 şansı var.
                    success = False
                    for _ in range(3):
                        vid_cli = VidSearchCLI()
                        with vid_cli.progress:
                            best_video = bolum.best_video(
                                by_res=dosya.ayarlar["max resolution"],
                                by_fansub=sub,
                                callback=vid_cli.callback)
                        if not best_video:
                            print("  (!) Hiçbir çalışan video bulunamadı.")
                            break
                        print("  Video başlatılacak..")
                        proc = best_video.oynat(dakika_hatirla=dosya.ayarlar["dakika hatirla"])
                        if proc.returncode == 0:
                            success = True
                            break
                        best_video.is_working = False
                        print("  Video çalışmadı, başka bir video denenecek..")
                    if success:
                        dosya.set_gecmis(anime.slug, bolum.slug, "izlendi")
                else:
                    sub = None
                    if dosya.ayarlar["manuel fansub"]:
                        devam, sub = fansub_sec(anime)
                        if not devam:
                            break
                    bolumler = anime.bolumler
                    if not bolumler:
                        rprint("[red][strong]Bu anime için bölüm bulunamadı.[/strong][/red]")
                        sleep(1.5)
                        break
                    choices, recent = eps_to_choices(bolumler, mark_type="indirildi")
                    bolumler = qa.checkbox(
                        message = "Bölüm seç",
                        choices=choices,
                        style=prompt_tema,
                        initial_choice=recent,
                        instruction="(\"boşluk\" ile seç, \"a\" ile tümünü seç, \"i\" ile tersini seç)"
                    ).ask(kbi_msg="")
                    if not bolumler:
                        break

                    # İndirme ekranını yarat ve başlat.
                    board = DownloadBoard()
                    with Live(board.render(), refresh_per_second=10, vertical_overflow="visible") as live:
                        board.live = live
                        futures = []
                        paralel = dosya.ayarlar.get("paralel indirme sayisi")
                        with cf.ThreadPoolExecutor(max_workers=paralel) as executor:
                            for bolum in bolumler:
                                futures.append(executor.submit(
                                    indirme_task_cli, bolum, board, dosya, sub))
                            cf.wait(futures)

        elif islem == "Ayarlar":
            while True:
                clear()
                dosyalar = Dosyalar()
                ayarlar = dosyalar.ayarlar
                tr = lambda opt: "AÇIK" if opt else "KAPALI"
                ayarlar_options = [
                    'İndirilenler klasörünü seç',
                    'Player önceliğini düzenle',
                    'Manuel fansub seç: '+tr(ayarlar['manuel fansub']),
                    'Maksimum çözünürlüğe ulaş: '+tr(ayarlar["max resolution"]),
                    'Kaldığın dakikayı hatirla: '+tr(ayarlar["dakika hatirla"]),
                    'İzlerken kaydet: '+tr(ayarlar['izlerken kaydet']),
                    'Paralel indirme sayisi: '+str(ayarlar["paralel indirme sayisi"]),
                    'İzlendi/İndirildi ikonu: '+tr(ayarlar["izlendi ikonu"]),
                    'Aria2c ile hızlandır (deneysel): '+tr(ayarlar["aria2c kullan"]),
                    'AnimeDepo kullanmaya zorla: '+tr(ayarlar["AnimeDepo kullanmaya zorla"]),
                    'Geri dön'
                ]
                ayar_islem = qa.select(
                    'İşlemi seç',
                    ayarlar_options,
                    style=prompt_tema,
                    instruction=" "
                    ).ask()

                if ayar_islem == ayarlar_options[0]:
                    indirilenler_dizin=diropenbox()
                    if indirilenler_dizin:
                        dosyalar.set_ayar("indirilenler",indirilenler_dizin)
                elif ayar_islem == ayarlar_options[1]:
                    yeni_sira = player_onceligi_duzenle(player_onceligi(ayarlar))
                    if yeni_sira:
                        dosyalar.set_ayar("player önceliği",yeni_sira)
                        player_onceligi_uygula(dosyalar.ayarlar)
                elif ayar_islem == ayarlar_options[2]:
                    dosyalar.set_ayar('manuel fansub', not ayarlar['manuel fansub'])
                elif ayar_islem == ayarlar_options[3]:
                    dosyalar.set_ayar('max resolution', not ayarlar['max resolution'])
                elif ayar_islem == ayarlar_options[4]:
                    dosyalar.set_ayar('dakika hatirla', not ayarlar['dakika hatirla'])
                elif ayar_islem == ayarlar_options[5]:
                    dosyalar.set_ayar("izlerken kaydet", not ayarlar['izlerken kaydet'])
                elif ayar_islem == ayarlar_options[6]:
                    max_dl = qa.text(
                        message = 'Maksimum eş zamanlı kaç bölüm indirilsin?',
                        default = str(ayarlar["paralel indirme sayisi"]),
                        style = prompt_tema
                    ).ask(kbi_msg="")
                    if isinstance(max_dl,str) and max_dl.isdigit():
                        dosyalar.set_ayar("paralel indirme sayisi", int(max_dl))
                elif ayar_islem == ayarlar_options[7]:
                    dosyalar.set_ayar('izlendi ikonu', not ayarlar['izlendi ikonu'])
                elif ayar_islem == ayarlar_options[8]:
                    dosyalar.set_ayar('aria2c kullan', not ayarlar['aria2c kullan'])
                elif ayar_islem == ayarlar_options[9]:
                    dosyalar.set_ayar("AnimeDepo kullanmaya zorla", not ayarlar["AnimeDepo kullanmaya zorla"])
                else:
                    break

        elif islem == "Kapat":
            break


def main():
    global SEARCH_FALLBACK, provider, Anime, Bolum
    ayarlar = Dosyalar().ayarlar
    player_onceligi_uygula(ayarlar)

    # Manifest kararlarını uygula.
    manifest = {}
    try:
        with CliStatus("Manifest kontrol ediliyor.."):
            manifest = requests.get(MANIFEST_URL,timeout=5).json()
    except Exception:
        pass
    if manifest.get("turkanime_url"):
        bypass.BASE_URL = "https://www.turkanime.co"
    if manifest.get("animedepo_url"):
        animedepo.BASE_URL = manifest["animedepo_url"]
    current_version = tuple(int(i) for i in __version__.split("."))
    aktifler = [
        (name,conf) for name,conf in (manifest.get("providers") or {}).items()
        if conf.get("enabled",True)
        and current_version >= tuple(int(i) for i in conf.get("min_client_version","0.0.0").replace("v","").replace("V","").split("."))
    ]
    SEARCH_FALLBACK = (manifest.get("features") or {}).get("search",{}).get("force_fallback",False)
    turkanime_enabled = any(name == "turkanime" for name,_conf in aktifler)
    animedepo.USE_TURKANIME = turkanime_enabled

    # Determine primary provider: prefer animecix if enabled, else fallback
    if any(name == "animecix" for name, _ in aktifler):
        provider_sec(animecix)
    elif any(name == "animedepo" for name, _ in aktifler):
        provider_sec(animedepo)
    elif any(name == "turkanime" for name, _ in aktifler):
        provider_sec(turkanime)
    else:
        provider_sec(animecix)  # ultimate fallback

    # Güncelleme kontrolü
    try:
        with CliStatus("Güncelleme kontrol ediliyor.."):
            surum = guncel_surum()
        tip = update_type(surum)
        if tip:
            rprint(f"[yellow]{tip} Güncellemesi mevcut!! v{surum}[/yellow]")
            rprint("[yellow]Yeni özellikler için uygulamayı güncelleyebilirsiniz! [/yellow]")
            sleep(5)
    except Exception as e:
        log_error(e)
        rprint("[red][strong]Güncelleme kontrol edilemedi.[/strong][red]")
        sleep(3)

    # Gereksinimleri kontrol et
    gereksinim_kontrol_cli()

    # Script herhangi bir sebepten dolayı sonlandırıldığında.
    def kapat():
        with CliStatus("Kapatılıyor.."):
            sleep(1.5)
    atexit.register(kapat)

    # Türkanime'ye bağlan veya AnimeDepo fallback kullan.
    if provider is turkanime:
        try:
            with CliStatus("Türkanime'ye bağlanılıyor.."):
                fetch(None)
        except Exception as e:
            log_error(e)
            provider_sec(animedepo)
            animedepo.USE_TURKANIME = False
            msg = (manifest.get("messages") or {}).get("turkanime_offline") or "TürkAnime'ye ulaşılamıyor, AnimeDepo kullanılacak."
            rprint(f"[yellow]{msg}[/yellow]")
            sleep(2)

    # Navigasyon menüsünü başlat.
    clear()
    rprint("[green]!)[/green] Üst menülere dönmek için Ctrl+C kullanabilirsiniz.\n")
    sleep(1.7)
    menu_loop()


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        log_error(e)
        rprint("[red][strong]Beklenmeyen bir hata oluştu. Detaylar error.log dosyasında.[/strong][red]")
        sys.exit(1)