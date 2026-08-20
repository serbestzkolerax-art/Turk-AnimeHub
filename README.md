# Turk-AnimeHub

Bu proje, farklı kaynaklardan (AnimeDepo, Animecix, OpenAni, Anizle vb.) anime bölümlerini çeken ve modern bir web arayüzü ile sunan kapsamlı bir platformdur.

## Özellikler
- **Kesintisiz Deneyim:** Bölümler için en hızlı ve stabil olan kaynaktan (örn. OpenAni) otomatik video alınır. 
- **Otomatik Geçiş & Auto-Skip:** Kırık veya çalışmayan video oynatñcılar tespit edilip anında bir sonraki sağlayıcıya (fansub/player) geçilir.
- **Kronolojik Sıralama:** AniList GraphQL API'si kullanılarak animelerin OVA, prequel ve sequel bölümleri otomatik olarak izleme sırasına göre dizilir.
- **Akıllı Arama:** Seriler otomatik olarak gruplandırılır, sadece ana animeler gösterilerek arama sonuçlarındaki karmaşa önlenir.
- **Gelişmiş Medya Oynatıcı (Player):** Tam ekranda bile gözüken Netflix tarzı "Sonraki Bölüm" butonu ve seçtiığiniz oynatıcıyı (player & fansub) sonraki bölümlerde de hatırlayan akıllı sistem.
- **MyAnimeList Entegrasyonu:** Kapak fotoğrafları, puanlar ve sezon bilgileri MAL üzerinden en yüksek kalitede çekilir.
- **Ìzleme Listesi (Watchlist):** Beğendiğiniz animeleri listeleyebilir ve takip edebilirsiniz.
- **Otomatik Birleştirme (Episode Merging):** Emsalsiz altyapısı sayesinde, farklı kaynaklarda (Animedepo, Animecix vs.) eksik olan bölümler tespit edilir ve canlı kaynaklardan (OpenAni vb.) alınarak kusursuz bir sezon listesi sunulur.

## Kurulum
1. Gerekli kütüphaneleri kurun: `pip install -r requirements.txt`
2. Uygulamayı başlatın: `python web.py`
3. Tarayıcınızda `http://127.0.0.1:5000` adresine gidin.

## Teşekkürler (Credits)
Bu projenin arka plan arama ve sağlayıcı mimarisinde aşağıdaki açık kaynaklı projelerden esinlenilmiş ve kod faydalanılmıştır:
- [turkanime-indirici](https://github.com/KebabLord/turkanime-indirici)
- [AnimecixScraper](https://github.com/requi5m/AnimecixScraper)
- [turkanime-gui](https://github.com/barkeser2002/turkanime-gui/)