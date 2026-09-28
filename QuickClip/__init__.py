# -*- coding: utf-8 -*-
"""
QuickClip
---------
Punkt wejścia wtyczki wymagany przez QGIS. classFactory() jest wywoływane
przez QGIS przy ładowaniu wtyczki i musi zwrócić instancję głównej klasy.
"""


def classFactory(iface):
    from .quickclip import QuickClipPlugin
    return QuickClipPlugin(iface)
