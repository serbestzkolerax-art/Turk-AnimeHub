# Anime İzle Projesi

Bu proje, farklı kaynaklardan (AnimeDepo, Animecix, vb.) anime bölümlerini çeken ve modern bir web arayüzü ile sunan bir platformdur.

## Özellikler
- **Kronolojik Sıralama:** AniList GraphQL API'si kullanılarak animelerin OVA, prequel ve sequel bölümleri otomatik olarak kronolojik şekilde listelenir.
- **Akıllı Arama:** Seriler otomatik olarak gruplandırılır, sadece ana animeler gösterilerek arama sonuçlarındaki karmaşa önlenir.
- **MyAnimeList Entegrasyonu:** Puanlar ve sezon bilgileri otomatik olarak MAL üzerinden çekilir.
- **İzleme Listesi (Watchlist):** Beğendiğiniz animeleri listeleyebilir ve takip edebilirsiniz.
- **Otomatik Birleştirme:** Farklı kaynaklardaki bölümler tek bir çatı altında toplanıp sekmeler (sezonlar) halinde sunulur.

## Kurulum
1. `pip install -r requirements.txt`
2. `python web.py` komutuyla projeyi başlatın.
3. Tarayıcınızda `http://127.0.0.1:5000` adresine gidin.

## Teşekkürler (Credits)
Bu projenin geliştirilmesinde aşağıdaki açık kaynaklı projelerden esinlenilmiş ve faydalanılmıştır. Katkıları için teşekkür ederiz:
- [turkanime-indirici](https://github.com/KebabLord/turkanime-indirici)
- [AnimecixScraper](https://github.com/requi5m/AnimecixScraper)
- [turkanime-gui](https://github.com/barkeser2002/turkanime-gui/)
