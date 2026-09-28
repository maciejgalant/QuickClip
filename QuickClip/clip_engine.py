# -*- coding: utf-8 -*-
"""
clip_engine.py
--------------
Właściwa logika przycinania warstw. Obsługuje dwa tryby określenia obszaru:

- "extent"  -> prostokątny zasięg (np. z widoku mapy) - wektory przez
               native:extractbyextent, rastry przez gdal:cliprasterbyextent.
- "mask"    -> dowolny poligon (z warstwy wektorowej lub narysowany ręcznie)
               - wektory przez native:clip, rastry przez
               gdal:cliprasterbymasklayer (CROP_TO_CUTLINE).

Jeśli obszar podany jako maska okaże się w rzeczywistości zwykłym,
osiowo zorientowanym prostokątem (patrz _resolve_area), automatycznie
sprowadzamy go do trybu "extent" - to znacznie szybsze niż ogólne
przycinanie po masce/cutline, a wynik jest identyczny.

W obu trybach obszar jest automatycznie transformowany do układu
współrzędnych każdej przycinanej warstwy, więc różne CRS w projekcie
nie wymagają żadnej interwencji użytkownika.

Uwaga o wydajności: przycinanie wykonywane jest synchronicznie (nie w
osobnym wątku QgsTask), zgodnie z priorytetem "stabilność ważniejsza niż
wielowątkowość" - algorytmy Processing/GDAL nie są w pełni bezpieczne do
równoległego odpalania z wielu wątków bez dodatkowej ostrożności. Interfejs
jest odświeżany między kolejnymi warstwami (patrz progress_callback w
quickclip_dialog.py), więc UI nie zamraża się na dłużej niż trwa
przycinanie pojedynczej warstwy. GDAL sam w sobie może jednak korzystać
z wielu wątków przy przycinaniu po masce (MULTITHREADING=True) - to nie
koliduje ze stabilnością API PyQGIS, bo dotyczy tylko wewnętrznego warpu.
"""

import os

import processing
from qgis.core import (
    Qgis,
    QgsVectorLayer,
    QgsRasterLayer,
    QgsFeature,
    QgsGeometry,
    QgsProject,
)

from . import utils

DEFAULT_OUTPUT_GROUP_NAME = "Przycięte warstwy"


class NoOverlapError(Exception):
    """Warstwa nie ma części wspólnej z obszarem przycinania - do pominięcia, nie błąd."""


class ClipResult:
    """Wynik przycięcia pojedynczej warstwy."""

    def __init__(self, layer_name, output_path=None, kind=None, error=None, skipped=False):
        self.layer_name = layer_name
        self.output_path = output_path
        self.kind = kind  # "vector" | "raster"
        self.error = error
        self.skipped = skipped  # warstwa nie pokrywa się z obszarem / wynik pusty

    @property
    def success(self):
        return self.error is None and not self.skipped


# ---------------------------------------------------------------------------
# Pomocnicze
# ---------------------------------------------------------------------------

def _vector_output_extension(layer):
    """Wybiera format wyjściowy zależnie od formatu warstwy źródłowej."""
    provider = layer.providerType().lower()
    source = layer.source().lower()
    if provider == "ogr":
        if ".gpkg" in source:
            return ".gpkg"
        if ".shp" in source:
            return ".shp"
    # Bezpieczny format zastępczy dla warstw pamięciowych, baz danych itp.
    return ".gpkg"


def _extent_string(extent, crs):
    text = (
        f"{extent.xMinimum()},{extent.xMaximum()},"
        f"{extent.yMinimum()},{extent.yMaximum()}"
    )
    authid = crs.authid()
    return f"{text} [{authid}]" if authid else text


def _make_mask_layer(geometry, crs, name="quickclip_mask"):
    """Tworzy tymczasową (pamięciową) warstwę wektorową z jedną geometrią poligonu."""
    mem_layer = QgsVectorLayer(f"Polygon?crs={crs.authid()}", name, "memory")
    provider = mem_layer.dataProvider()
    feature = QgsFeature()
    feature.setGeometry(geometry)
    provider.addFeature(feature)
    mem_layer.updateExtents()
    return mem_layer


def _area_bounding_box(area_mode, extent, extent_crs, mask_geometry, mask_crs):
    """Zwraca (prostokąt, crs) opisujące obszar przycinania - niezależnie od trybu."""
    if area_mode == "extent":
        return extent, extent_crs
    return mask_geometry.boundingBox(), mask_crs


def _layer_intersects_area(layer, area_mode, extent, extent_crs, mask_geometry, mask_crs, project):
    """
    Szybkie sprawdzenie "czy w ogóle warto przycinać" - porównuje zasięg
    warstwy z zasięgiem obszaru (po przeliczeniu do CRS warstwy). Pozwala
    pominąć warstwy (np. sąsiednie kafle rastra), które w ogóle nie
    pokrywają się z zaznaczonym obszarem, bez odpalania Processing/GDAL.
    """
    layer_extent = layer.extent()
    if layer_extent.isEmpty():
        return False

    area_extent, area_crs = _area_bounding_box(area_mode, extent, extent_crs, mask_geometry, mask_crs)
    try:
        area_extent_in_layer_crs = utils.transform_extent(area_extent, area_crs, layer.crs(), project)
    except Exception:
        # Jeśli transformacja się nie powiedzie, nie blokujemy przycinania -
        # niech spróbuje właściwy algorytm Processing/GDAL.
        return True

    return layer_extent.intersects(area_extent_in_layer_crs)


def _delete_output_file(path):
    """Usuwa plik wynikowy (wraz z plikami towarzyszącymi dla Shapefile)."""
    try:
        if path.lower().endswith(".shp"):
            from qgis.core import QgsVectorFileWriter
            QgsVectorFileWriter.deleteShapeFile(path)
        elif os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


_NO_OVERLAP_ERROR_HINTS = (
    "outside",
    "poza zasi",  # "poza zasięgiem" - komunikaty QGIS bywają lokalizowane
    "empty",
    "pusty",
    "zero-size",
    "no valid",
    "falls completely",
)


def _looks_like_no_overlap_error(exc):
    """Heurystyka: czy wyjątek z GDAL/Processing wygląda na brak nakładania się warstwy z obszarem."""
    message = str(exc).lower()
    return any(hint in message for hint in _NO_OVERLAP_ERROR_HINTS)


def _resolve_area(area_mode, extent, extent_crs, mask_geometry, mask_crs):
    """
    Ustala RAZ (dla całej operacji, nie dla każdej warstwy z osobna), jak
    właściwie potraktować obszar przycinania.

    Jeśli obszar podany jako maska (warstwa wektorowa albo narysowany
    poligon) jest w rzeczywistości zwykłym, osiowo zorientowanym
    prostokątem, sprowadzamy go do zwykłego extentu - dzięki temu wektory
    są przycinane szybszym native:extractbyextent zamiast native:clip,
    a rastry szybszym gdal:cliprasterbyextent zamiast wolniejszego
    maskowania po cutline (gdal:cliprasterbymasklayer). To główne źródło
    przyspieszenia dla dużych rastrów przy trybach "Warstwa wektorowa"
    i "Narysuj obszar".

    Zwraca (mode, extent_or_None, extent_crs_or_None, mask_geom_or_None, mask_crs).
    """
    if area_mode == "extent":
        return "extent", extent, extent_crs, None, None

    bbox = mask_geometry.boundingBox()
    if mask_geometry.equals(QgsGeometry.fromRect(bbox)):
        return "extent", bbox, mask_crs, None, None

    return "mask", None, None, mask_geometry, mask_crs


# ---------------------------------------------------------------------------
# Przycinanie wg prostokątnego extentu
# ---------------------------------------------------------------------------

def clip_vector_by_extent(layer, extent, extent_crs, output_path):
    processing.run(
        "native:extractbyextent",
        {
            "INPUT": layer,
            "EXTENT": _extent_string(extent, extent_crs),
            "CLIP": True,
            "OUTPUT": output_path,
        },
    )


def clip_raster_by_extent(layer, extent, extent_crs, output_path, project=None):
    project = project or QgsProject.instance()
    # Ograniczamy obszar do faktycznego zasięgu rastra. Bez tego GDAL
    # wypełniałby część wykraczającą poza raster zerami (czarne tło).
    area = utils.transform_extent(extent, extent_crs, layer.crs(), project)
    overlap = layer.extent().intersect(area)
    if overlap.isEmpty():
        raise NoOverlapError(layer.name())

    processing.run(
        "gdal:cliprasterbyextent",
        {
            "INPUT": layer,
            "PROJWIN": _extent_string(overlap, layer.crs()),
            "NODATA": None,
            "OPTIONS": "",
            "DATA_TYPE": 0,  # taki sam typ danych, jak warstwa wejściowa
            "OUTPUT": output_path,
        },
    )


# ---------------------------------------------------------------------------
# Przycinanie wg dowolnej maski poligonowej
# ---------------------------------------------------------------------------

def clip_vector_by_mask(layer, mask_geometry, mask_crs, output_path, project=None):
    project = project or QgsProject.instance()
    geometry = utils.transform_geometry(QgsGeometry(mask_geometry), mask_crs, layer.crs(), project)
    mask_layer = _make_mask_layer(geometry, layer.crs())
    processing.run(
        "native:clip",
        {
            "INPUT": layer,
            "OVERLAY": mask_layer,
            "OUTPUT": output_path,
        },
    )


def _mask_clip_fill_options(layer):
    """
    Zwraca (nodata, alpha_band) dla przycinania rastra po masce, tak aby
    obszar poza maską był PRZEZROCZYSTY, a nie czarny.

    - raster ma już NoData lub kanał alfa -> nic nie zmieniamy,
    - raster RGB (3 kanały)               -> dodajemy kanał alfa,
    - raster jednokanałowy (np. NMT)      -> ustawiamy NoData
      (-9999 dla typów zmiennoprzecinkowych, 0 dla całkowitoliczbowych).
    """
    provider = layer.dataProvider()
    try:
        if provider.sourceHasNoDataValue(1) and provider.useSourceNoDataValue(1):
            return None, False
    except Exception:
        pass

    bands = layer.bandCount()
    if bands == 2 or bands >= 4:
        return None, False  # kanał alfa już istnieje (szary+alfa / RGBA)
    if bands == 3:
        return None, True

    try:
        dtype = provider.dataType(1)
        is_float = dtype in (Qgis.DataType.Float32, Qgis.DataType.Float64)
    except Exception:
        is_float = False
    return (-9999 if is_float else 0), False


def clip_raster_by_mask(layer, mask_geometry, mask_crs, output_path, project=None):
    project = project or QgsProject.instance()
    geometry = utils.transform_geometry(QgsGeometry(mask_geometry), mask_crs, layer.crs(), project)

    # Tniemy maskę do zasięgu rastra - inaczej CROP_TO_CUTLINE kadrowałby
    # wynik do całego konturu i wypełniał brakujące piksele czernią.
    geometry = geometry.intersection(QgsGeometry.fromRect(layer.extent()))
    if geometry.isNull() or geometry.isEmpty():
        raise NoOverlapError(layer.name())

    nodata, alpha_band = _mask_clip_fill_options(layer)
    mask_layer = _make_mask_layer(geometry, layer.crs())
    processing.run(
        "gdal:cliprasterbymasklayer",
        {
            "INPUT": layer,
            "MASK": mask_layer,
            "SOURCE_CRS": None,
            "TARGET_CRS": None,
            "NODATA": nodata,
            "ALPHA_BAND": alpha_band,
            "CROP_TO_CUTLINE": True,
            "KEEP_RESOLUTION": True,
            "SET_RESOLUTION": False,
            "X_RESOLUTION": None,
            "Y_RESOLUTION": None,
            "MULTITHREADING": True,
            "OPTIONS": "",
            "DATA_TYPE": 0,
            "EXTRA": "",
            "OUTPUT": output_path,
        },
    )


# ---------------------------------------------------------------------------
# Maska z warstwy wektorowej (dissolve wszystkich obiektów w jedną geometrię)
# ---------------------------------------------------------------------------

def dissolve_layer_geometry(layer):
    """
    Łączy geometrie wszystkich obiektów warstwy w jedną (unary union),
    tak aby wiele poligonów maski działało jako jeden wspólny obszar
    przycinania. Zwraca (geometry, crs).
    """
    geometries = [f.geometry() for f in layer.getFeatures() if f.geometry() and not f.geometry().isEmpty()]
    if not geometries:
        raise ValueError(f"Warstwa maski '{layer.name()}' nie zawiera żadnych geometrii.")
    combined = QgsGeometry.unaryUnion(geometries)
    return combined, layer.crs()


def _get_or_create_output_group(project, group_name):
    """
    Zwraca grupę w drzewie warstw o podanej nazwie, tworząc ją na samej
    górze drzewa, jeśli jeszcze nie istnieje. Dzięki temu wyniki kolejnych
    operacji QuickClip trafiają zawsze do tej samej, wspólnej podgrupy
    zamiast zaśmiecać główny widok warstw.
    """
    root = project.layerTreeRoot()
    group = root.findGroup(group_name)
    if group is None:
        group = root.insertGroup(0, group_name)
    return group


# ---------------------------------------------------------------------------
# Główna pętla przycinania wielu warstw
# ---------------------------------------------------------------------------

def run_quickclip(
    layers,
    area_mode,
    output_folder,
    add_to_project=True,
    extent=None,
    extent_crs=None,
    mask_geometry=None,
    mask_crs=None,
    progress_callback=None,
    project=None,
    output_group_name=DEFAULT_OUTPUT_GROUP_NAME,
):
    """
    Przycina listę warstw do wspólnego obszaru.

    area_mode: "extent" (prostokąt) albo "mask" (dowolny poligon).
    progress_callback(index, total, layer_name): wywoływane przed
        przetworzeniem każdej warstwy - pozwala odświeżyć UI.
    output_group_name: nazwa podgrupy w drzewie warstw, do której trafiają
        wyniki (domyślnie "Przycięte warstwy"). Ustaw None, aby dodawać
        warstwy bezpośrednio do głównego drzewa (bez grupowania).

    Zwraca listę obiektów ClipResult (jeden na warstwę). Błąd jednej
    warstwy nie przerywa przetwarzania kolejnych.
    """
    project = project or QgsProject.instance()
    results = []
    total = len(layers)

    output_group = None
    if add_to_project and output_group_name:
        output_group = _get_or_create_output_group(project, output_group_name)

    # Obszar rozstrzygamy RAZ dla całej operacji (patrz _resolve_area) -
    # zamiast robić to dla każdej warstwy osobno w pętli.
    resolved_mode, r_extent, r_extent_crs, r_mask_geom, r_mask_crs = _resolve_area(
        area_mode, extent, extent_crs, mask_geometry, mask_crs
    )

    for index, layer in enumerate(layers, start=1):
        if progress_callback:
            progress_callback(index, total, layer.name())

        # Pomiń od razu warstwy, których zasięg w ogóle nie pokrywa się
        # z zaznaczonym obszarem (np. sąsiednie kafle rastra/wektora) -
        # bez marnowania czasu na Processing/GDAL i bez zaśmiecania wyników.
        if not _layer_intersects_area(layer, resolved_mode, r_extent, r_extent_crs, r_mask_geom, r_mask_crs, project):
            results.append(ClipResult(layer.name(), skipped=True))
            continue

        base_name = f"{utils.sanitize_filename(layer.name())}_cut"
        kind = None
        out_path = None

        try:
            if isinstance(layer, QgsVectorLayer):
                kind = "vector"
                out_path = utils.unique_output_path(output_folder, base_name, _vector_output_extension(layer))
                if resolved_mode == "extent":
                    clip_vector_by_extent(layer, r_extent, r_extent_crs, out_path)
                else:
                    clip_vector_by_mask(layer, r_mask_geom, r_mask_crs, out_path, project)

            elif isinstance(layer, QgsRasterLayer):
                kind = "raster"
                out_path = utils.unique_output_path(output_folder, base_name, ".tif")
                if resolved_mode == "extent":
                    clip_raster_by_extent(layer, r_extent, r_extent_crs, out_path, project)
                else:
                    clip_raster_by_mask(layer, r_mask_geom, r_mask_crs, out_path, project)

            else:
                results.append(ClipResult(layer.name(), error="Nieobsługiwany typ warstwy."))
                continue

        except Exception as exc:  # noqa: BLE001 - błąd jednej warstwy nie może przerwać reszty
            if isinstance(exc, NoOverlapError) or _looks_like_no_overlap_error(exc):
                if out_path:
                    _delete_output_file(out_path)
                results.append(ClipResult(layer.name(), skipped=True))
            else:
                results.append(ClipResult(layer.name(), error=str(exc)))
            continue

        # Wczytujemy wynik TYLKO RAZ - i do sprawdzenia, czy nie jest pusty,
        # i (jeśli trzeba) do dodania do projektu. Podwójne otwieranie tego
        # samego dużego rastra/wektora było zbędnym spowolnieniem.
        result_name = os.path.splitext(os.path.basename(out_path))[0]
        if kind == "vector":
            output_layer = QgsVectorLayer(out_path, result_name, "ogr")
        else:
            output_layer = QgsRasterLayer(out_path, result_name)

        if not output_layer.isValid():
            del output_layer
            results.append(
                ClipResult(
                    layer.name(),
                    output_path=out_path,
                    kind=kind,
                    error="Plik zapisano, ale nie udało się go wczytać.",
                )
            )
            continue

        is_empty = (kind == "vector" and output_layer.featureCount() == 0) or (
            kind == "raster" and (output_layer.width() == 0 or output_layer.height() == 0)
        )
        if is_empty:
            del output_layer
            _delete_output_file(out_path)
            results.append(ClipResult(layer.name(), skipped=True))
            continue

        if add_to_project:
            utils.copy_style(layer, output_layer)
            if output_group is not None:
                # addMapLayer(..., False) rejestruje warstwę w projekcie bez
                # dodawania jej do głównego drzewa, dzięki czemu możemy
                # ręcznie umieścić ją w podgrupie wyników.
                project.addMapLayer(output_layer, False)
                output_group.insertLayer(0, output_layer)
            else:
                project.addMapLayer(output_layer)
        else:
            del output_layer

        results.append(ClipResult(layer.name(), output_path=out_path, kind=kind))

    return results
