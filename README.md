# QuickClip

Wtyczka QGIS do **szybkiego, jednoczesnego przycinania wielu warstw wektorowych i rastrowych** do wspólnego obszaru.
Filozofia: *otwórz → wybierz → przytnij → gotowe.*

*English: a minimalist QGIS plugin that clips many vector and raster layers at once to a map view, a polygon layer or a hand‑drawn polygon.*

## Funkcje

- Wektory i rastry traktowane tak samo – jedno okno, jeden przycisk **PRZYTNIJ**
- Warstwy: **widoczne** albo **wybrane** ręcznie (osobne okno z wyszukiwarką)
- Obszar: **widok mapy**, **warstwa wektorowa** (maska) lub **narysowany poligon**
  (dwuklik kończy, `Backspace` cofa punkt, `Esc` anuluje)
- Automatyczna obsługa różnych CRS – nie trzeba nic wybierać
- Wyniki z dopiskiem `_cut` (bez nadpisywania: `_cut_2`, `_cut_3`…), dodawane do grupy „Przycięte warstwy”
- Zachowanie stylu warstwy źródłowej
- Warstwy niepokrywające się z obszarem są pomijane
- Poza maską rastry są przezroczyste (kanał alfa / NoData), nie czarne
- Błąd jednej warstwy nie zatrzymuje reszty

## Wymagania

QGIS **3.36 – 4.x** (Qt5 i Qt6).

## Instalacja

**Z repozytorium wtyczek QGIS:** *Wtyczki → Zarządzaj i instaluj wtyczki* → wyszukaj „QuickClip”
(przy wersji oznaczonej jako eksperymentalna zaznacz w ustawieniach „Pokaż także wtyczki eksperymentalne”).

**Z pliku ZIP:** pobierz `QuickClip-<wersja>.zip` z [Releases](https://github.com/maciejgalant/QuickClip/releases)
→ *Wtyczki → Zarządzaj i instaluj wtyczki → Zainstaluj z pliku ZIP*.

**Ręcznie:** skopiuj folder `QuickClip/` do katalogu wtyczek profilu QGIS
(*Ustawienia → Profile użytkownika → Otwórz aktywny folder profilu → python/plugins*).

## Użycie

1. Kliknij ikonę nożyczek na pasku narzędzi.
2. Wybierz warstwy i sposób określenia obszaru.
3. (Opcjonalnie) wskaż folder – domyślnie `QuickClip_wyniki` obok pliku projektu.
4. Kliknij **PRZYTNIJ**.

## Jak to działa

| Obszar | Wektory | Rastry |
|---|---|---|
| Prostokąt (widok mapy lub maska będąca prostokątem) | `native:extractbyextent` | `gdal:cliprasterbyextent` |
| Dowolny poligon | `native:clip` | `gdal:cliprasterbymasklayer` |

Przycinanie działa synchronicznie (stabilność ponad wielowątkowość), a interfejs jest odświeżany między warstwami.

## Rozwój

```bash
python build_plugin_zip.py   # tworzy dist/QuickClip-<wersja>.zip
```

Wydanie: podbij `version` i `changelog` w `QuickClip/metadata.txt`, dodaj tag `vX.Y.Z` – GitHub Actions zbuduje ZIP i dołączy go do wydania.

## Licencja

GNU GPL v2 lub nowsza – patrz [LICENSE](LICENSE).

## Autor

Maciej Galant · magal.pl@wp.pl · [Zgłaszanie błędów](https://github.com/maciejgalant/QuickClip/issues)
