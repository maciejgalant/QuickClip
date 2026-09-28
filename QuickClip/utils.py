# -*- coding: utf-8 -*-
"""
utils.py
--------
Funkcje pomocnicze używane przez resztę wtyczki QuickClip:
- zapamiętywanie ostatniego folderu wynikowego (QSettings),
- generowanie unikalnych nazw plików wynikowych,
- filtrowanie warstw obsługiwanych przez QuickClip (bez WMS/WMTS/XYZ itp.),
- pomoc przy transformacjach CRS,
- kopiowanie stylu (symbologii) ze źródłowej warstwy na przyciętą kopię.
"""

import os
import re

from qgis.PyQt.QtCore import QSettings
from qgis.PyQt.QtXml import QDomDocument
from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsRasterLayer,
    QgsWkbTypes,
    QgsCoordinateTransform,
    QgsApplication,
)

SETTINGS_KEY_LAST_FOLDER = "QuickClip/last_output_folder"


# ---------------------------------------------------------------------------
# Ustawienia (QSettings)
# ---------------------------------------------------------------------------

def get_last_output_folder():
    settings = QSettings()
    return settings.value(SETTINGS_KEY_LAST_FOLDER, "", type=str)


def set_last_output_folder(folder):
    settings = QSettings()
    settings.setValue(SETTINGS_KEY_LAST_FOLDER, folder)


def get_default_output_folder(project=None):
    """
    Zwraca domyślny folder wynikowy używany, gdy użytkownik nie wskaże
    własnego: podfolder "QuickClip_wyniki" obok pliku projektu, a jeśli
    projekt nie został jeszcze zapisany na dysku - w katalogu domowym
    użytkownika. Dzięki temu pole folderu w oknie QuickClip nie musi być
    wypełnione, aby móc kliknąć PRZYTNIJ.
    """
    project = project or QgsProject.instance()
    project_path = project.fileName()
    base_dir = os.path.dirname(project_path) if project_path else os.path.expanduser("~")
    return os.path.join(base_dir, "QuickClip_wyniki")


# ---------------------------------------------------------------------------
# Nazwy plików
# ---------------------------------------------------------------------------

def sanitize_filename(name):
    """Usuwa znaki niedozwolone w nazwach plików/warstw."""
    name = re.sub(r"[^\w\-. ]", "_", name)
    name = name.strip().replace(" ", "_")
    return name or "warstwa"


def unique_output_path(folder, base_name, extension):
    """
    Zwraca ścieżkę '<folder>/<base_name><extension>', a jeśli już istnieje,
    dostawia kolejny numer: base_name_2, base_name_3, itd. (nigdy nie
    nadpisuje istniejących plików bez ostrzeżenia).
    """
    extension = extension if extension.startswith(".") else f".{extension}"
    candidate = os.path.join(folder, f"{base_name}{extension}")
    if not os.path.exists(candidate):
        return candidate

    i = 2
    while True:
        candidate = os.path.join(folder, f"{base_name}_{i}{extension}")
        if not os.path.exists(candidate):
            return candidate
        i += 1


# ---------------------------------------------------------------------------
# Filtrowanie obsługiwanych warstw
# ---------------------------------------------------------------------------

# Nieobsługiwane typy dostawców rastrowych (kafle sieciowe, usługi OGC itp.)
_UNSUPPORTED_RASTER_PROVIDERS = {"wms", "wmts", "xyz", "arcgismapserver"}


def is_supported_vector(layer):
    """QuickClip obsługuje standardowe warstwy wektorowe z lokalnym/plikowym źródłem."""
    if not isinstance(layer, QgsVectorLayer):
        return False
    if not layer.isValid():
        return False
    provider = layer.providerType().lower()
    if provider in ("wfs",):
        return False
    return True


def is_supported_raster(layer):
    """QuickClip obsługuje tylko rastry z realnym źródłem danych (GDAL), bez usług kafelkowych."""
    if not isinstance(layer, QgsRasterLayer):
        return False
    if not layer.isValid():
        return False
    provider = layer.providerType().lower()
    return provider not in _UNSUPPORTED_RASTER_PROVIDERS


def get_supported_layers(project=None):
    """Zwraca listę wszystkich obsługiwanych warstw (wektorowych i rastrowych) w projekcie."""
    project = project or QgsProject.instance()
    layers = []
    for layer in project.mapLayers().values():
        if is_supported_vector(layer) or is_supported_raster(layer):
            layers.append(layer)
    return layers


def get_visible_layers(iface, project=None):
    """Zwraca obsługiwane warstwy z włączoną widocznością w drzewie warstw."""
    project = project or QgsProject.instance()
    root = project.layerTreeRoot()
    visible = []
    for layer in project.mapLayers().values():
        if not (is_supported_vector(layer) or is_supported_raster(layer)):
            continue
        node = root.findLayer(layer.id())
        if node is not None and node.isVisible():
            visible.append(layer)
    return visible


def layer_icon(layer):
    """Zwraca małą, standardową ikonę QGIS dla warstwy wektorowej/rastrowej."""
    try:
        from qgis.core import QgsIconUtils
        return QgsIconUtils.iconForLayer(layer)
    except Exception:
        pass
    try:
        if isinstance(layer, QgsRasterLayer):
            return QgsApplication.getThemeIcon("/mIconRaster.svg")
        if isinstance(layer, QgsVectorLayer):
            return QgsApplication.getThemeIcon("/mIconPolygonLayer.svg")
    except Exception:
        pass
    return None


def get_polygon_vector_layers(project=None):
    """Zwraca warstwy wektorowe o geometrii poligonowej/multipoligonowej - kandydatów na maskę."""
    project = project or QgsProject.instance()
    result = []
    for layer in project.mapLayers().values():
        if not is_supported_vector(layer):
            continue
        if layer.geometryType() == QgsWkbTypes.PolygonGeometry:
            result.append(layer)
    return result


# ---------------------------------------------------------------------------
# CRS
# ---------------------------------------------------------------------------

def transform_geometry(geometry, source_crs, dest_crs, project=None):
    """Zwraca kopię geometrii przetransformowaną z source_crs do dest_crs."""
    if source_crs == dest_crs:
        return geometry
    project = project or QgsProject.instance()
    transform = QgsCoordinateTransform(source_crs, dest_crs, project)
    geom = geometry
    geom.transform(transform)
    return geom


def transform_extent(extent, source_crs, dest_crs, project=None):
    """Zwraca prostokąt (QgsRectangle) przetransformowany z source_crs do dest_crs."""
    if source_crs == dest_crs:
        return extent
    project = project or QgsProject.instance()
    transform = QgsCoordinateTransform(source_crs, dest_crs, project)
    return transform.transformBoundingBox(extent)


# ---------------------------------------------------------------------------
# Styl / symbologia
# ---------------------------------------------------------------------------

def copy_style(source_layer, target_layer):
    """
    Kopiuje styl (renderer, przezroczystość itp.) z warstwy źródłowej na
    warstwę docelową, jeśli to możliwe. Działa zarówno dla warstw
    wektorowych, jak i rastrowych - obie obsługują export/importNamedStyle.
    Błąd kopiowania stylu nie powinien przerywać operacji przycinania,
    dlatego wszelkie wyjątki są tu wyciszane.
    """
    try:
        doc = QDomDocument()
        message, ok = source_layer.exportNamedStyle(doc)
        if not ok:
            return False
        target_layer.importNamedStyle(doc)
        target_layer.triggerRepaint()
        return True
    except Exception:
        return False
