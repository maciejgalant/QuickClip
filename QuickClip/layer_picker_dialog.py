# -*- coding: utf-8 -*-
"""
layer_picker_dialog.py
-----------------------
Osobne, większe i czytelne okno wyboru warstw dla trybu "Wybierz warstwy".

W przeciwieństwie do małej listy wciśniętej w główne, wąskie okno
QuickClip, to okno:
- jest szersze i można je swobodnie powiększać,
- pokazuje pełne nazwy warstw (bez ucinania), z podpowiedzią (tooltip)
  zawierającą nazwę i źródło danych,
- ma wyszukiwarkę filtrującą listę po nazwie,
- ma liczbik "Wybrano: X z Y" oraz przyciski zaznacz/odznacz wszystkie.
"""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QLabel,
    QDialogButtonBox,
)

from qgis.core import QgsRasterLayer

from . import utils


class LayerPickerDialog(QDialog):

    def __init__(self, layers, checked_ids, parent=None):
        """
        layers: lista obsługiwanych warstw (QgsVectorLayer / QgsRasterLayer)
        checked_ids: set() identyfikatorów warstw, które mają być domyślnie
                     zaznaczone po otwarciu okna.
        """
        super().__init__(parent)
        self._layers = layers
        self._checked_ids = set(checked_ids)

        self.setWindowTitle("Wybierz warstwy")
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self.resize(460, 420)

        self._build_ui()
        self._populate()
        self._update_count_label()

    # ------------------------------------------------------------------
    # Budowa interfejsu
    # ------------------------------------------------------------------

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Szukaj warstwy...")
        self.search_edit.setClearButtonEnabled(True)
        layout.addWidget(self.search_edit)

        self.list_widget = QListWidget()
        self.list_widget.setAlternatingRowColors(True)
        self.list_widget.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        layout.addWidget(self.list_widget, 1)

        select_row = QHBoxLayout()
        self.select_all_button = QPushButton("Zaznacz wszystkie")
        self.select_none_button = QPushButton("Odznacz wszystkie")
        self.count_label = QLabel("")
        self.count_label.setStyleSheet("color: gray;")
        select_row.addWidget(self.select_all_button)
        select_row.addWidget(self.select_none_button)
        select_row.addStretch(1)
        select_row.addWidget(self.count_label)
        layout.addLayout(select_row)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self.search_edit.textChanged.connect(self._apply_filter)
        self.select_all_button.clicked.connect(self._select_all)
        self.select_none_button.clicked.connect(self._select_none)
        self.list_widget.itemChanged.connect(self._on_item_changed)

    # ------------------------------------------------------------------
    # Wypełnianie listy
    # ------------------------------------------------------------------

    def _populate(self):
        self.list_widget.blockSignals(True)
        self.list_widget.clear()

        for layer in self._layers:
            kind_label = "Raster" if isinstance(layer, QgsRasterLayer) else "Wektor"
            item = QListWidgetItem(f"[{kind_label}]  {layer.name()}")
            item.setToolTip(f"{layer.name()}\n{layer.source()}")

            icon = utils.layer_icon(layer)
            if icon is not None:
                item.setIcon(icon)

            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            checked = layer.id() in self._checked_ids
            item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, layer.id())
            self.list_widget.addItem(item)

        self.list_widget.blockSignals(False)

    # ------------------------------------------------------------------
    # Wyszukiwanie / filtrowanie
    # ------------------------------------------------------------------

    def _apply_filter(self, text):
        text = text.strip().lower()
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            item.setHidden(bool(text) and text not in item.text().lower())

    # ------------------------------------------------------------------
    # Zaznacz / odznacz wszystkie (tylko widoczne po filtrze)
    # ------------------------------------------------------------------

    def _select_all(self):
        self._set_all_visible(Qt.CheckState.Checked)

    def _select_none(self):
        self._set_all_visible(Qt.CheckState.Unchecked)

    def _set_all_visible(self, state):
        self.list_widget.blockSignals(True)
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if not item.isHidden():
                item.setCheckState(state)
        self.list_widget.blockSignals(False)
        self._update_count_label()

    def _on_item_changed(self, item):
        self._update_count_label()

    def _update_count_label(self):
        total = self.list_widget.count()
        checked = sum(
            1 for i in range(total) if self.list_widget.item(i).checkState() == Qt.CheckState.Checked
        )
        self.count_label.setText(f"Wybrano: {checked} z {total}")

    # ------------------------------------------------------------------
    # Wynik
    # ------------------------------------------------------------------

    def selected_layer_ids(self):
        ids = set()
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                ids.add(item.data(Qt.ItemDataRole.UserRole))
        return ids
