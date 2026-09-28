# -*- coding: utf-8 -*-
"""
quickclip_dialog.py
--------------------
Kompaktowe, nie-modalne okno dialogowe wtyczki QuickClip.

Filozofia: otwórz -> wybierz -> przytnij -> gotowe. Okno chowa się na
czas ręcznego rysowania obszaru na mapie i pojawia się ponownie po
zakończeniu rysowania.
"""

import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QRadioButton,
    QButtonGroup,
    QComboBox,
    QLineEdit,
    QPushButton,
    QCheckBox,
    QLabel,
    QProgressBar,
    QFileDialog,
    QMessageBox,
    QApplication,
    QWidget,
)
from qgis.core import QgsProject

from . import utils
from . import clip_engine
from .area_map_tool import AreaMapTool
from .layer_picker_dialog import LayerPickerDialog


class QuickClipDialog(QDialog):

    AREA_EXTENT = "extent"
    AREA_MASK_LAYER = "mask_layer"
    AREA_DRAW = "draw"

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self.project = QgsProject.instance()

        self.setWindowTitle("QuickClip")
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self.setMinimumWidth(300)
        self.setMaximumWidth(340)

        self._area_map_tool = None
        self._previous_map_tool = None
        self._mask_geometry = None
        self._mask_geometry_crs = None
        self._last_errors = []
        self._last_skipped = []
        self._picked_layer_ids = None  # None => wszystkie obsługiwane warstwy

        self._build_ui()
        self._connect_signals()
        self._load_settings()
        self._update_layers_section()
        self._update_area_section()

    # ------------------------------------------------------------------
    # Budowa interfejsu
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # --- Warstwy ---
        layers_box = QGroupBox("Warstwy")
        layers_layout = QVBoxLayout()
        layers_layout.setSpacing(3)

        self.radio_visible_layers = QRadioButton("Widoczne warstwy")
        self.radio_pick_layers = QRadioButton("Wybierz warstwy")
        self.radio_visible_layers.setChecked(True)

        self.layers_group = QButtonGroup(self)
        self.layers_group.addButton(self.radio_visible_layers)
        self.layers_group.addButton(self.radio_pick_layers)

        layers_layout.addWidget(self.radio_visible_layers)
        layers_layout.addWidget(self.radio_pick_layers)

        pick_row = QHBoxLayout()
        pick_row.setContentsMargins(18, 0, 0, 0)
        self.pick_layers_button = QPushButton("Wybierz warstwy...")
        self.pick_summary_label = QLabel("")
        self.pick_summary_label.setStyleSheet("color: gray;")
        pick_row.addWidget(self.pick_layers_button)
        pick_row.addWidget(self.pick_summary_label, 1)
        self.pick_row_widget = QWidget()
        self.pick_row_widget.setLayout(pick_row)
        self.pick_row_widget.setVisible(False)
        layers_layout.addWidget(self.pick_row_widget)

        layers_box.setLayout(layers_layout)
        root.addWidget(layers_box)

        # --- Obszar ---
        area_box = QGroupBox("Obszar")
        area_layout = QVBoxLayout()
        area_layout.setSpacing(3)

        self.radio_area_view = QRadioButton("Widok mapy")
        self.radio_area_mask = QRadioButton("Warstwa wektorowa")
        self.radio_area_draw = QRadioButton("Narysuj obszar")
        self.radio_area_view.setChecked(True)

        self.area_group = QButtonGroup(self)
        self.area_group.addButton(self.radio_area_view)
        self.area_group.addButton(self.radio_area_mask)
        self.area_group.addButton(self.radio_area_draw)

        area_layout.addWidget(self.radio_area_view)
        area_layout.addWidget(self.radio_area_mask)

        mask_row = QHBoxLayout()
        mask_row.setContentsMargins(18, 0, 0, 0)
        mask_row.addWidget(QLabel("Maska:"))
        self.mask_combo = QComboBox()
        mask_row.addWidget(self.mask_combo, 1)
        self.mask_row_widget = QWidget()
        self.mask_row_widget.setLayout(mask_row)
        self.mask_row_widget.setVisible(False)
        area_layout.addWidget(self.mask_row_widget)

        area_layout.addWidget(self.radio_area_draw)

        draw_row = QHBoxLayout()
        draw_row.setContentsMargins(18, 0, 0, 0)
        self.draw_button = QPushButton("Narysuj")
        self.draw_status_label = QLabel("")
        draw_row.addWidget(self.draw_button)
        draw_row.addWidget(self.draw_status_label, 1)
        self.draw_row_widget = QWidget()
        self.draw_row_widget.setLayout(draw_row)
        self.draw_row_widget.setVisible(False)
        area_layout.addWidget(self.draw_row_widget)

        area_box.setLayout(area_layout)
        root.addWidget(area_box)

        # --- Zapis ---
        save_box = QGroupBox("Zapis")
        save_layout = QVBoxLayout()
        save_layout.setSpacing(3)

        output_row = QHBoxLayout()
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("Domyślnie: folder obok projektu / QuickClip_wyniki")
        self.browse_button = QPushButton("...")
        self.browse_button.setFixedWidth(28)
        output_row.addWidget(self.output_edit, 1)
        output_row.addWidget(self.browse_button)
        save_layout.addLayout(output_row)

        self.add_to_project_checkbox = QCheckBox("Dodaj wyniki do projektu")
        self.add_to_project_checkbox.setChecked(True)
        save_layout.addWidget(self.add_to_project_checkbox)

        save_box.setLayout(save_layout)
        root.addWidget(save_box)

        # --- Przycisk główny ---
        self.clip_button = QPushButton("PRZYTNIJ")
        self.clip_button.setMinimumHeight(32)
        font = self.clip_button.font()
        font.setBold(True)
        self.clip_button.setFont(font)
        root.addWidget(self.clip_button)

        # --- Status / postęp ---
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setVisible(False)
        root.addWidget(self.progress_bar)

        status_row = QHBoxLayout()
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: gray; font-size: 10px;")
        self.details_button = QPushButton("Szczegóły")
        self.details_button.setFlat(True)
        self.details_button.setStyleSheet("font-size: 10px;")
        self.details_button.setVisible(False)
        status_row.addWidget(self.status_label, 1)
        status_row.addWidget(self.details_button)
        root.addLayout(status_row)

    def _connect_signals(self):
        self.radio_visible_layers.toggled.connect(self._update_layers_section)
        self.radio_pick_layers.toggled.connect(self._update_layers_section)

        self.radio_area_view.toggled.connect(self._update_area_section)
        self.radio_area_mask.toggled.connect(self._update_area_section)
        self.radio_area_draw.toggled.connect(self._update_area_section)

        self.pick_layers_button.clicked.connect(self._open_layer_picker)
        self.browse_button.clicked.connect(self._browse_output_folder)
        self.draw_button.clicked.connect(self._start_drawing)
        self.clip_button.clicked.connect(self._on_clip_clicked)
        self.details_button.clicked.connect(self._show_error_details)

    def _load_settings(self):
        last_folder = utils.get_last_output_folder()
        if last_folder:
            self.output_edit.setText(last_folder)

    # ------------------------------------------------------------------
    # Aktualizacja widoczności sekcji zależnie od wybranych opcji
    # ------------------------------------------------------------------

    def _update_layers_section(self):
        show_row = self.radio_pick_layers.isChecked()
        self.pick_row_widget.setVisible(show_row)
        if show_row:
            self._update_pick_summary()

    def _update_pick_summary(self):
        total = len(utils.get_supported_layers(self.project))
        if self._picked_layer_ids is None:
            selected = total
        else:
            selected = len(self._picked_layer_ids)
        self.pick_summary_label.setText(f"Wybrano: {selected} z {total}")

    def _open_layer_picker(self):
        layers = utils.get_supported_layers(self.project)
        if not layers:
            QMessageBox.information(self, "QuickClip", "Projekt nie zawiera żadnych obsługiwanych warstw.")
            return

        checked_ids = self._picked_layer_ids
        if checked_ids is None:
            checked_ids = {layer.id() for layer in layers}

        dialog = LayerPickerDialog(layers, checked_ids, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._picked_layer_ids = dialog.selected_layer_ids()
            self._update_pick_summary()

    def _update_area_section(self):
        self.mask_row_widget.setVisible(self.radio_area_mask.isChecked())
        self.draw_row_widget.setVisible(self.radio_area_draw.isChecked())
        if self.radio_area_mask.isChecked():
            self._populate_mask_combo()

    def _populate_mask_combo(self):
        self.mask_combo.clear()
        for layer in utils.get_polygon_vector_layers(self.project):
            self.mask_combo.addItem(layer.name(), layer.id())

    # ------------------------------------------------------------------
    # Folder wynikowy
    # ------------------------------------------------------------------

    def _browse_output_folder(self):
        start_dir = self.output_edit.text().strip() or utils.get_last_output_folder()
        folder = QFileDialog.getExistingDirectory(self, "Wybierz folder wynikowy", start_dir)
        if folder:
            self.output_edit.setText(folder)

    # ------------------------------------------------------------------
    # Rysowanie obszaru na mapie
    # ------------------------------------------------------------------

    def _start_drawing(self):
        if self._area_map_tool is None:
            self._area_map_tool = AreaMapTool(self.canvas)
            self._area_map_tool.geometryCaptured.connect(self._on_geometry_captured)
            self._area_map_tool.captureCanceled.connect(self._on_drawing_canceled)

        self._previous_map_tool = self.canvas.mapTool()
        self.hide()
        self.canvas.setMapTool(self._area_map_tool)
        self.iface.statusBarIface().showMessage(
            "QuickClip: kliknij kolejne wierzchołki obszaru, dwuklik kończy rysowanie "
            "(Backspace - cofnij punkt, Esc - anuluj)."
        )

    def _restore_previous_tool(self):
        if self._previous_map_tool is not None:
            self.canvas.setMapTool(self._previous_map_tool)
        else:
            self.canvas.unsetMapTool(self._area_map_tool)
        self.iface.statusBarIface().clearMessage()

    def _on_geometry_captured(self, geometry, crs):
        self._mask_geometry = geometry
        self._mask_geometry_crs = crs
        self._restore_previous_tool()
        self.show()
        self.raise_()
        self.activateWindow()
        self.draw_button.setText("Narysuj ponownie")
        self.draw_status_label.setText("✓ Obszar wybrany")
        self.draw_status_label.setStyleSheet("color: green;")

    def _on_drawing_canceled(self):
        self._restore_previous_tool()
        self.show()
        self.raise_()
        self.activateWindow()
        if self._mask_geometry is None:
            self.draw_status_label.setText("Anulowano")
            self.draw_status_label.setStyleSheet("color: gray;")

    # ------------------------------------------------------------------
    # Zbieranie danych wejściowych do przycięcia
    # ------------------------------------------------------------------

    def _selected_layers(self):
        if self.radio_visible_layers.isChecked():
            return utils.get_visible_layers(self.iface, self.project)

        all_layers = utils.get_supported_layers(self.project)
        if self._picked_layer_ids is None:
            return all_layers
        return [layer for layer in all_layers if layer.id() in self._picked_layer_ids]

    def _area_mode(self):
        if self.radio_area_view.isChecked():
            return self.AREA_EXTENT
        if self.radio_area_mask.isChecked():
            return self.AREA_MASK_LAYER
        return self.AREA_DRAW

    # ------------------------------------------------------------------
    # Główna operacja - PRZYTNIJ
    # ------------------------------------------------------------------

    def _on_clip_clicked(self):
        layers = self._selected_layers()
        if not layers:
            QMessageBox.warning(self, "QuickClip", "Nie wybrano żadnej warstwy do przycięcia.")
            return

        output_folder = self.output_edit.text().strip()
        if not output_folder:
            # Pole folderu nie jest wymagane - jeśli puste, użyj sensownego
            # folderu domyślnego (obok projektu, ew. katalog domowy).
            output_folder = utils.get_default_output_folder(self.project)
            self.output_edit.setText(output_folder)

        if not os.path.isdir(output_folder):
            try:
                os.makedirs(output_folder, exist_ok=True)
            except OSError as exc:
                QMessageBox.critical(self, "QuickClip", f"Nie udało się utworzyć folderu wynikowego:\n{exc}")
                return

        area_mode = self._area_mode()
        extent = extent_crs = mask_geometry = mask_crs = None

        if area_mode == self.AREA_EXTENT:
            # Extent pobierany DOKŁADNIE w momencie kliknięcia PRZYTNIJ.
            extent = self.canvas.extent()
            extent_crs = self.canvas.mapSettings().destinationCrs()
            engine_mode = "extent"

        elif area_mode == self.AREA_MASK_LAYER:
            mask_layer_id = self.mask_combo.currentData()
            mask_layer = self.project.mapLayer(mask_layer_id) if mask_layer_id else None
            if mask_layer is None:
                QMessageBox.warning(self, "QuickClip", "Wybierz warstwę wektorową jako maskę.")
                return
            try:
                mask_geometry, mask_crs = clip_engine.dissolve_layer_geometry(mask_layer)
            except ValueError as exc:
                QMessageBox.warning(self, "QuickClip", str(exc))
                return
            engine_mode = "mask"

        else:  # AREA_DRAW
            if self._mask_geometry is None:
                QMessageBox.warning(self, "QuickClip", "Najpierw narysuj obszar na mapie.")
                return
            mask_geometry = self._mask_geometry
            mask_crs = self._mask_geometry_crs
            engine_mode = "mask"

        utils.set_last_output_folder(output_folder)
        self._run_clip(
            layers=layers,
            engine_mode=engine_mode,
            output_folder=output_folder,
            extent=extent,
            extent_crs=extent_crs,
            mask_geometry=mask_geometry,
            mask_crs=mask_crs,
        )

    def _run_clip(self, layers, engine_mode, output_folder, extent, extent_crs, mask_geometry, mask_crs):
        self._set_busy(True, total=len(layers))

        def progress_callback(index, total, layer_name):
            self.progress_bar.setMaximum(total)
            self.progress_bar.setValue(index - 1)
            self.status_label.setText(f"Przycinanie: {layer_name}")
            self.status_label.setStyleSheet("color: gray; font-size: 10px;")
            QApplication.processEvents()

        results = clip_engine.run_quickclip(
            layers=layers,
            area_mode=engine_mode,
            output_folder=output_folder,
            add_to_project=self.add_to_project_checkbox.isChecked(),
            extent=extent,
            extent_crs=extent_crs,
            mask_geometry=mask_geometry,
            mask_crs=mask_crs,
            progress_callback=progress_callback,
            project=self.project,
        )

        self.progress_bar.setValue(self.progress_bar.maximum())
        self._set_busy(False)
        self._show_summary(results)

    def _set_busy(self, busy, total=0):
        self.clip_button.setEnabled(not busy)
        self.progress_bar.setVisible(busy)
        if busy:
            self.progress_bar.setMaximum(max(total, 1))
            self.progress_bar.setValue(0)

    def _show_summary(self, results):
        ok = [r for r in results if r.success]
        skipped = [r for r in results if r.skipped]
        failed = [r for r in results if r.error and not r.skipped]
        self._last_errors = failed
        self._last_skipped = skipped

        base = f"✓ Przycięto {len(ok)} warstw" if len(ok) != 1 else "✓ Przycięto 1 warstwę"
        if skipped:
            base += f"  (pominięto {len(skipped)} - poza obszarem)"

        if not failed:
            self.status_label.setText(base)
            self.status_label.setStyleSheet("color: green; font-size: 10px;")
        else:
            self.status_label.setText(f"{base}    ⚠ {len(failed)} błędy")
            self.status_label.setStyleSheet("color: darkorange; font-size: 10px;")

        self.details_button.setVisible(bool(failed) or bool(skipped))

    def _show_error_details(self):
        if not self._last_errors and not self._last_skipped:
            return
        lines = []
        if self._last_skipped:
            lines.append("Pominięte (poza zaznaczonym obszarem):")
            lines.extend(f"  • {r.layer_name}" for r in self._last_skipped)
        if self._last_errors:
            if lines:
                lines.append("")
            lines.append("Błędy:")
            lines.extend(f"  • {r.layer_name}: {r.error}" for r in self._last_errors)
        QMessageBox.information(self, "QuickClip - szczegóły", "\n".join(lines))

    # ------------------------------------------------------------------
    # Zamknięcie okna - porządki
    # ------------------------------------------------------------------

    def closeEvent(self, event):
        if self._area_map_tool is not None and self.canvas.mapTool() == self._area_map_tool:
            self._restore_previous_tool()
        super().closeEvent(event)
