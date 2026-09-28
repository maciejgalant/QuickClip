# -*- coding: utf-8 -*-
"""
quickclip.py
------------
Główna klasa wtyczki QuickClip. Dodaje przycisk do paska narzędzi
i menu Wtyczki, który otwiera niewielkie, nie-modalne okno QuickClip.
"""

import os

from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction

from .quickclip_dialog import QuickClipDialog

PLUGIN_NAME = "QuickClip"


class QuickClipPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.action = None
        self.dialog = None

    # ------------------------------------------------------------------
    # Metody wymagane przez QGIS
    # ------------------------------------------------------------------

    def initGui(self):
        icon_path = os.path.join(self.plugin_dir, "icons", "icon.png")
        icon = QIcon(icon_path) if os.path.exists(icon_path) else QIcon()

        self.action = QAction(icon, PLUGIN_NAME, self.iface.mainWindow())
        self.action.setToolTip("QuickClip - szybkie przycinanie wielu warstw jednocześnie")
        self.action.triggered.connect(self.show_dialog)

        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu(PLUGIN_NAME, self.action)

    def unload(self):
        if self.dialog is not None:
            self.dialog.close()
            self.dialog = None

        if self.action is not None:
            self.iface.removePluginMenu(PLUGIN_NAME, self.action)
            self.iface.removeToolBarIcon(self.action)
            self.action = None

    # ------------------------------------------------------------------
    # Otwieranie okna
    # ------------------------------------------------------------------

    def show_dialog(self):
        if self.dialog is None:
            self.dialog = QuickClipDialog(self.iface, parent=self.iface.mainWindow())

        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()
