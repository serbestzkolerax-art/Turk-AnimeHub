"""
Multi-Source Provider Architecture for TurkAnime Downloader

Adds parsing scaffolding for streaming sources: ecchicix.com and animecix.tv
These sites are parsed similarly to the existing turkanime.tv provider,
extracting embedded player URLs or direct video stream links.

Usage examples from cli/__main__.py context after adding providers:
  1) Update manifest.json with new source configurations
  2) Import parser modules in bypass.py or create fetch wrapper

Example pattern for using these sources during parsing (inline usage):
    src = fetch("/some/page", domain=ECCHICIX_BASE_URL)
    video_urls = extract_stream_links(src, provider="ecchicix")

NOT: Aşağıdaki regex desenleri, bu kaynakların genel embed sayfası
yapısına göre YAKLAŞIK/başlangıç noktası olarak yazılmıştır. Canlı sitenin
güncel HTML/JS yapısına göre doğrulanıp güncellenmesi gerekir -- bunun için
ilgili sayfanın kaynağını tarayıcıda inceleyip desenleri buna göre
düzeltin. `NotImplementedError` ile işaretlenen kısımlar henüz gerçek
sitede doğrulanmamıştır.
"""

import re


class BaseSiteParser:
    """Ortak regex tabanlı embed/stream ayıklama davranışı."""

    # Alt sınıflar bu desenleri kendi sitelerine göre override etmeli.
    IFRAME_PATTERN = r'<iframe[^>]+src=["\']([^"\']+)["\']'
    DIRECT_MP4_PATTERN = r'["\'](https?://[^"\'\s]+?\.mp4[^"\'\s]*)["\']'
    DIRECT_M3U8_PATTERN = r'["\'](https?://[^"\'\s]+?\.m3u8[^"\'\s]*)["\']'

    @classmethod
    def extract_iframe_src(cls, html):
        match = re.search(cls.IFRAME_PATTERN, html)
        return match.group(1) if match else None

    @classmethod
    def extract_stream_links(cls, html):
        """Sayfa kaynağında bulunan doğrudan .mp4/.m3u8 linklerini döndürür."""
        links = re.findall(cls.DIRECT_MP4_PATTERN, html)
        links += re.findall(cls.DIRECT_M3U8_PATTERN, html)
        # Sırayı korurken tekrarları temizle.
        return list(dict.fromkeys(links))


class EcchiCIXParser(BaseSiteParser):
    """HTML parser sınıfı: ecchicix.com - Anime streaming kaynağı."""

    IFRAME_PATTERN = r'<iframe[^>]+src=["\']([^"\']*/embed/[^"\']+)["\']'


class AnimeCIXParser(BaseSiteParser):
    """HTML parser sınıfı: animecix.tv - Anime streaming kaynağı."""

    IFRAME_PATTERN = r'<iframe[^>]+src=["\']([^"\']*/embed/[^"\']+)["\']'


_PARSERS = {
    "ecchicix": EcchiCIXParser,
    "animecix": AnimeCIXParser,
}


def parse_ecchicix_page(html):
    """ecchicix.com sayfa kaynağından embed player URL'sini çıkarır."""
    return EcchiCIXParser.extract_iframe_src(html)


def parse_animecix_page(html):
    """animecix.tv sayfa kaynağından embed player URL'sini çıkarır."""
    return AnimeCIXParser.extract_iframe_src(html)


def extract_stream_links(html, provider):
    """
    Verilen `provider` ("ecchicix" veya "animecix") için sayfa kaynağındaki
    doğrudan video stream linklerini döndürür.
    """
    parser = _PARSERS.get(provider)
    if parser is None:
        raise ValueError(f"Bilinmeyen provider: {provider!r}")
    return parser.extract_stream_links(html)
