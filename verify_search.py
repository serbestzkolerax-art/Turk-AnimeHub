from turkanime_api.objects import parse_arama_sonuc

html = '<a href="/anime/one-piece" title="One Piece">One Piece</a>'
print(parse_arama_sonuc(html))
