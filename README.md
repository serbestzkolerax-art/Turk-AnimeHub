# Turk-AnimeHub

Bu proje, farklý kaynaklardan (AnimeDepo, Animecix, Ecchicix vb.) anime bölümlerini çeken ve modern bir web arayüzü ile sunan kapsamlý bir platformdur.

## Özellikler
- **Kesintisiz Deneyim:** Bölümler için en hýzlý ve stabil olan kaynaktan (örn. OpenAni) otomatik video alýnýr. 
- **Otomatik Geçiþ & Auto-Skip:** Kýrýk veya çalýþmayan video oynatýcýlar tespit edilip anýnda bir sonraki saðlayýcýya (fansub/player) geçilir.
- **Geliþmiþ Kronolojik Sýralama:** AniList GraphQL API'si kullanýlarak animelerin OVA, prequel ve sequel bölümleri otomatik olarak izleme sýrasýna göre dizilir. AniList'te eksik olan 'Özel Bölümler' veya 'OVA'lar (örn. One Punch Man 2nd Season Commemorative Special), AnimeDepo veritabanýyla çapraz referanslanarak doðru sezonun altýna otomatik olarak dahil edilir.
- **Akýllý Arama:** Seriler otomatik olarak gruplandýrýlýr, OVA'lar arama çubuðundan gizlenerek sadece ana animeler gösterilir. Karmaþaya son verilir.
- **Hýzlý Yerel Veritabaný:** 2600'den fazla anime ve bölümleri önbelleðe alýnmýþ yerel JSON dosyalarýndan anýnda çekilir, canlý (live) kaynak aramalarýndaki bekleme süreleri sýfýra indirilmiþtir.
- **Geliþmiþ Medya Oynatýcý (Player):** Tam ekranda bile gözüken Netflix tarzý "Sonraki Bölüm" butonu ve seçtiðiniz oynatýcýyý (player & fansub) sonraki bölümlerde de hatýrlayan akýllý sistem.
- **Ýzleme Listesi (Watchlist):** Beðendiðiniz animeleri listeleyebilir ve takip edebilirsiniz.

## Kurulum
1. Gerekli kütüphaneleri kurun: \pip install -r requirements.txt\
2. Uygulamayý baþlatýn: \python web.py\
3. Tarayýcýnýzda \http://127.0.0.1:5000\ adresine gidin.

## Teþekkürler (Credits)
Bu projenin arka plan arama ve saðlayýcý mimarisinde aþaðýdaki açýk kaynaklý projelerden esinlenilmiþ ve kod faydalanýlmýþtýr:
- [turkanime-indirici](https://github.com/KebabLord/turkanime-indirici)
- [AnimecixScraper](https://github.com/requi5m/AnimecixScraper)
- [turkanime-gui](https://github.com/barkeser2002/turkanime-gui/)
