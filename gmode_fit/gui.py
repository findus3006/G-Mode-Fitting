"""PySide6 window for fitting the G mode of one Raman spectrum at a time.

Left: file and x-axis settings, the fit range, the peak model (type, label
and value / bounds / fix per parameter) and the export buttons. Right: the
spectrum with model, components, baseline and residuals, and the results
table. The plot is a ``kpfm_pl`` :class:`~kpfm_pl.gui.canvas.PlotPanel`, so it
has the toolbox' wheel zoom (Shift: x only, Ctrl: y only), middle-drag pan,
Home button and figure/CSV export; left-drag selects the fit range.

Files are opened with *Open…*, Ctrl+O or by dropping them anywhere on the
window.
"""

from __future__ import annotations

import csv
import datetime as _dt
import sys
from pathlib import Path

import numpy as np
from matplotlib.widgets import SpanSelector
from PySide6.QtCore import QEvent, QSettings, Qt
from PySide6.QtCore import Signal as QtSignal
from PySide6.QtGui import QAction, QColor, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDockWidget,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

try:
    from kpfm_pl.core import Signal
    from kpfm_pl.gui.canvas import PlotPanel
    from kpfm_pl.gui.context import AppContext
    from kpfm_pl.gui.export import ExportPayload, build_metadata, write_table_csv
    from kpfm_pl.gui.logcapture import install as install_log_capture
except ImportError as exc:  # pragma: no cover - start-up message only
    raise SystemExit(
        f"gmode_fit needs the kpfm_pl toolbox with its GUI extra ({exc}).\n"
        "Install it from its folder with:  pip install -e .[gui]"
    ) from exc

from . import __version__
from .fitting import (
    PRESETS,
    FitResult,
    Peak,
    Param,
    auto_guess,
    default_range,
    fit,
    normalize_label,
    preset,
    start_model,
)
from .io import Spectrum, load_spectrum
from .lineshapes import BASELINES, PEAK_KINDS

__all__ = ["MainWindow", "main"]

_LABELS = ("G-", "G+", "D'", "other")
_COMP_COLOURS = ("tab:blue", "tab:green", "tab:purple", "tab:orange", "tab:brown",
                 "tab:pink", "tab:olive", "tab:cyan")
_ANALYSIS = "Raman G-mode fit"

_PARAM_TIPS = {
    "area": "Integrated intensity of the line (counts·cm⁻¹). For a BWF this is the "
            "Lorentzian-equivalent area π·I₀·Γ/2, because the BWF integral itself "
            "diverges.",
    "center": "Line position ω₀. Leave Min/Max empty to keep it inside the fit range.\n"
              "For a BWF the maximum lies at ω₀ + Γ/(2q), not at ω₀.",
    "fwhm": "Full width at half maximum.",
    "fwhm_l": "Lorentzian (intrinsic) FWHM of the Voigt profile.",
    "fwhm_g": "Gaussian FWHM of the Voigt profile, usually the instrument resolution. "
              "Fix it when the instrument function is known; free, it is strongly "
              "correlated with the Lorentzian width.",
    "inv_q": "Breit-Wigner-Fano asymmetry 1/q. Negative: tail towards low wavenumbers "
             "(metallic tubes, typically −0.1 … −0.5). 0 gives a Lorentzian.",
}


def _parse(text: str, *, blank_ok: bool) -> float | None:
    t = text.strip().replace(",", ".").replace("−", "-")
    if not t:
        if blank_ok:
            return None
        raise ValueError("empty")
    return float(t)


def _fmt(value: float | None) -> str:
    return "" if value is None else f"{value:.6g}"


def fmt_pm(value: float, error: float, fixed: bool = False) -> str:
    """``value ± error`` rounded to two significant digits of the error."""
    if value is None or not np.isfinite(value):
        return "–"
    if fixed:
        return f"{value:.5g} (fixed)"
    if error is None or not np.isfinite(error) or error <= 0:
        return f"{value:.5g}"
    digits = int(np.clip(1 - np.floor(np.log10(error)), 0, 6))
    return f"{value:.{digits}f} ± {error:.{digits}f}"


# ===================================================================== peaks
class PeakEditor(QGroupBox):
    """Editor of one :class:`Peak`: type, label and value/min/max/fix per parameter."""

    changed = QtSignal()
    remove_requested = QtSignal(object)

    def __init__(self, peak: Peak, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.kind_box = QComboBox()
        self.kind_box.addItems(list(PEAK_KINDS))
        self.kind_box.setToolTip("Line shape. Use BWF for the G⁻ line of metallic tubes.")
        self.label_box = QComboBox()
        self.label_box.setEditable(True)
        self.label_box.addItems(_LABELS)
        self.label_box.setToolTip("G- and G+ are used for the area ratio A(G⁻)/A(G⁺) and "
                                  "the summary.\nSeveral peaks with the same label are "
                                  "summed. Auto-guess places G+ on the highest maximum and "
                                  "G- on the strongest signal below it.")
        remove = QToolButton()
        remove.setText("✕")
        remove.setToolTip("Remove this peak")
        remove.clicked.connect(lambda: self.remove_requested.emit(self))

        header = QHBoxLayout()
        header.addWidget(QLabel("Type"))
        header.addWidget(self.kind_box)
        header.addWidget(QLabel("Label"))
        header.addWidget(self.label_box, 1)
        header.addWidget(remove)
        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(4)
        self.grid.setVerticalSpacing(2)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.addLayout(header)
        layout.addLayout(self.grid)

        self._kind = None
        self.rows: dict[str, dict] = {}
        self.set_peak(peak)
        self.kind_box.currentTextChanged.connect(self._kind_changed)
        self.label_box.currentTextChanged.connect(lambda _t: self.changed.emit())

    # ------------------------------------------------------------- building
    def _build_rows(self, kind: str) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.rows = {}
        for col, text in enumerate(("", "Value", "Min", "Max", "Fix", "Fit ± 1σ")):
            head = QLabel(f"<small><b>{text}</b></small>")
            self.grid.addWidget(head, 0, col)
        spec = PEAK_KINDS[kind]
        for r, (name, label, unit) in enumerate(zip(spec.params, spec.labels, spec.units), 1):
            title = QLabel(f"{label}" + (f" <small>({unit})</small>" if unit else ""))
            title.setToolTip(_PARAM_TIPS[name])
            value, lo, hi = QLineEdit(), QLineEdit(), QLineEdit()
            for edit in (value, lo, hi):
                edit.setMinimumWidth(56)
                edit.setAcceptDrops(False)
                edit.editingFinished.connect(self._edited)
            value.setToolTip(_PARAM_TIPS[name] + "\n\nStart value; replaced by the fit result.")
            lo.setPlaceholderText("−∞")
            hi.setPlaceholderText("+∞")
            lo.setToolTip("Lower bound (empty: none).")
            hi.setToolTip("Upper bound (empty: none).")
            fix = QCheckBox()
            fix.setToolTip("Keep this parameter at its value during the fit.")
            fix.toggled.connect(lambda _c: self._edited())
            result = QLabel("")
            result.setStyleSheet("color: #555")
            result.setMinimumWidth(90)
            for col, w in enumerate((title, value, lo, hi, fix, result)):
                self.grid.addWidget(w, r, col)
            self.rows[name] = {"value": value, "min": lo, "max": hi, "fix": fix, "result": result}
        self.grid.setColumnStretch(1, 2)
        self.grid.setColumnStretch(2, 1)
        self.grid.setColumnStretch(3, 1)
        self._kind = kind

    def set_peak(self, peak: Peak, errors: dict[str, float] | None = None) -> None:
        """Show ``peak``; ``errors`` (from a fit) fill the result column."""
        if peak.kind != self._kind:
            self._build_rows(peak.kind)
        for w in (self.kind_box, self.label_box):
            w.blockSignals(True)
        self.kind_box.setCurrentText(peak.kind)
        self.label_box.setCurrentText(peak.label)
        for w in (self.kind_box, self.label_box):
            w.blockSignals(False)
        for name, row in self.rows.items():
            p = peak.params[name]
            row["fix"].blockSignals(True)
            row["value"].setText(_fmt(p.value))
            row["min"].setText(_fmt(p.min))
            row["max"].setText(_fmt(p.max))
            row["fix"].setChecked(p.fixed)
            row["fix"].blockSignals(False)
            for key in ("value", "min", "max"):
                row[key].setStyleSheet("")
            if errors is None:
                row["result"].setText("")
            else:
                row["result"].setText(fmt_pm(p.value, errors.get(name, np.nan), p.fixed))

    def peak(self) -> Peak:
        """The peak as entered; raises ``ValueError`` naming the bad field."""
        params = {}
        label = self.label_box.currentText().strip()
        for name, row in self.rows.items():
            try:
                value = _parse(row["value"].text(), blank_ok=False)
                lo = _parse(row["min"].text(), blank_ok=True)
                hi = _parse(row["max"].text(), blank_ok=True)
            except ValueError:
                raise ValueError(f"Peak '{label or self.kind_box.currentText()}': "
                                 f"invalid number for {name}.") from None
            params[name] = Param(value, lo, hi, row["fix"].isChecked())
        return Peak(self.kind_box.currentText(), label, params)

    # -------------------------------------------------------------- signals
    def _edited(self) -> None:
        for row in self.rows.values():
            row["result"].setText("")
            for key in ("value", "min", "max"):
                try:
                    _parse(row[key].text(), blank_ok=key != "value")
                    row[key].setStyleSheet("")
                except ValueError:
                    row[key].setStyleSheet("background: #ffd6d6")
        self.changed.emit()

    def _kind_changed(self, kind: str) -> None:
        try:
            old = self.peak()
        except ValueError:
            old = Peak.create(self._kind, self.label_box.currentText())
        self.set_peak(old.converted(kind))
        self.changed.emit()


# ================================================================ main window
class MainWindow(QMainWindow):
    """The G-mode fitting window."""

    def __init__(self, settings: QSettings | None = None) -> None:
        super().__init__()
        self.setWindowTitle(f"G-mode fit {__version__}")
        self.settings = settings or QSettings("gmode_fit", "gui")
        self.ctx = AppContext(self, settings=self.settings)
        self.spectrum: Spectrum | None = None
        self._path: Path | None = None
        self.result: FitResult | None = None
        self._pre_fit: list[Peak] | None = None
        self.editors: list[PeakEditor] = []
        self._artists: list = []
        self._span = None
        self._ax = self._axr = None
        self._busy = False

        self._build_ui()
        self.ctx.log.message.connect(self._log)
        self.set_peaks(preset("metallic"))
        self.baseline_box.setCurrentText(str(self.settings.value("baseline", "linear")))
        self.plot.show_message("Open a spectrum (Ctrl+O) or drop a file onto the window.")
        self.setAcceptDrops(True)
        QApplication.instance().installEventFilter(self)

    # ================================================================== UI
    def _build_ui(self) -> None:
        # ---- file
        open_button = QPushButton("Open spectrum…")
        open_button.clicked.connect(self.open_dialog)
        self.file_label = QLabel("<i>no file – or drop one onto the window</i>")
        self.file_label.setWordWrap(True)
        self.laser_spin = QDoubleSpinBox()
        self.laser_spin.setRange(0, 2000)
        self.laser_spin.setDecimals(3)
        self.laser_spin.setSuffix(" nm")
        self.laser_spin.setSpecialValueText("unknown")
        self.laser_spin.setKeyboardTracking(False)
        self.laser_spin.setToolTip("Excitation wavelength, read from the file name "
                                   "(e.g. '_532nm_'). Needed to convert a wavelength axis.")
        self.unit_box = QComboBox()
        for key, text in (("auto", "auto-detect"), ("nm", "wavelength (nm)"),
                          ("cm-1", "Raman shift (cm⁻¹)")):
            self.unit_box.addItem(text, key)
        self.unit_box.setToolTip("Unit of the file's first column. Auto: a wavelength when "
                                 "the values lie up to 4000 cm⁻¹ above the laser line.")
        self.offset_spin = QDoubleSpinBox()
        self.offset_spin.setRange(-1000, 1000)
        self.offset_spin.setDecimals(2)
        self.offset_spin.setSingleStep(0.5)
        self.offset_spin.setSuffix(" cm⁻¹")
        self.offset_spin.setKeyboardTracking(False)
        self.offset_spin.setToolTip("Calibration correction added to the Raman shift. "
                                    "It is remembered per laser wavelength.")
        self.axis_label = QLabel("")
        self.axis_label.setStyleSheet("color: #555")
        self.axis_label.setWordWrap(True)
        self.laser_spin.valueChanged.connect(lambda _v: self._axis_changed("laser"))
        self.unit_box.currentIndexChanged.connect(lambda _i: self._axis_changed("unit"))
        self.offset_spin.valueChanged.connect(lambda _v: self._axis_changed("offset"))

        file_box = QGroupBox("1  Spectrum")
        form = QFormLayout(file_box)
        form.addRow(open_button)
        form.addRow(self.file_label)
        form.addRow("Laser", self.laser_spin)
        form.addRow("File x axis", self.unit_box)
        form.addRow("Shift offset", self.offset_spin)
        form.addRow(self.axis_label)

        # ---- range
        self.range_min = QDoubleSpinBox()
        self.range_max = QDoubleSpinBox()
        for spin in (self.range_min, self.range_max):
            spin.setRange(-1e5, 1e5)
            spin.setDecimals(1)
            spin.setSuffix(" cm⁻¹")
            spin.setKeyboardTracking(False)
            spin.valueChanged.connect(lambda _v: self._range_from_spins())
        full = QPushButton("Full range")
        full.setToolTip("Whole spectrum without the outermost 3 points (often spikes).")
        full.clicked.connect(self._full_range)
        range_box = QGroupBox("2  Fit range  (left-drag on the plot)")
        row = QHBoxLayout(range_box)
        row.addWidget(self.range_min, 1)
        row.addWidget(QLabel("to"))
        row.addWidget(self.range_max, 1)
        row.addWidget(full)

        # ---- model
        self.preset_box = QComboBox()
        for key, (text, _f) in PRESETS.items():
            self.preset_box.addItem(text, key)
        self.preset_box.setCurrentIndex(self.preset_box.findData("metallic"))
        apply_preset = QPushButton("Use preset")
        apply_preset.setToolTip("Replace the peaks below by the preset (then auto-guess).")
        apply_preset.clicked.connect(self.apply_preset)
        self.baseline_box = QComboBox()
        self.baseline_box.addItems(list(BASELINES))
        self.baseline_box.setToolTip("Polynomial background fitted together with the peaks.")
        self.baseline_box.currentTextChanged.connect(self._baseline_changed)
        add_peak = QPushButton("+ Add peak")
        add_peak.clicked.connect(lambda: self.add_peak(Peak.create("Voigt", "other",
                                                                    center=self._range_mid())))
        guess = QPushButton("Auto-guess start values")
        guess.setToolTip("Positions, widths and areas from the data in the fit range. "
                         "Fixed parameters are kept.")
        guess.clicked.connect(self.auto_guess)
        self.guess_on_load = QCheckBox("Auto-guess when a file is loaded")
        self.guess_on_load.setChecked(self.settings.value("guess_on_load", True, type=bool))
        self.fit_button = QPushButton("Fit")
        self.fit_button.setStyleSheet("font-weight: bold; padding: 6px")
        self.fit_button.setShortcut(QKeySequence("Ctrl+F"))
        self.fit_button.setToolTip("Fit the model in the selected range (Ctrl+F). The fitted "
                                   "values become the new start values.")
        self.fit_button.clicked.connect(self.run_fit)
        revert = QPushButton("Revert")
        revert.setToolTip("Restore the start values used for the last fit.")
        revert.clicked.connect(self.revert)

        model_box = QGroupBox("3  Model")
        mlay = QVBoxLayout(model_box)
        r1 = QHBoxLayout()
        r1.addWidget(self.preset_box, 1)
        r1.addWidget(apply_preset)
        mlay.addLayout(r1)
        r2 = QHBoxLayout()
        r2.addWidget(QLabel("Baseline"))
        r2.addWidget(self.baseline_box, 1)
        r2.addWidget(add_peak)
        mlay.addLayout(r2)
        self.peak_layout = QVBoxLayout()
        self.peak_layout.setSpacing(4)
        mlay.addLayout(self.peak_layout)
        r3 = QHBoxLayout()
        r3.addWidget(guess, 1)
        r3.addWidget(revert)
        mlay.addLayout(r3)
        mlay.addWidget(self.guess_on_load)
        mlay.addWidget(self.fit_button)

        # ---- export
        export_results = QPushButton("Export results (CSV)…")
        export_results.setToolTip("Peak table with values, errors and the fit settings.")
        export_results.clicked.connect(self.export_results)
        append = QPushButton("Append to summary CSV")
        append.setToolTip("Add one row (G⁻, G⁺, ratio, quality) for this file to the "
                          "summary table, e.g. to compare samples and lasers.")
        append.clicked.connect(self.append_summary)
        choose = QToolButton()
        choose.setText("…")
        choose.setToolTip("Choose another summary file")
        choose.clicked.connect(lambda: self._choose_summary() and None)
        self.summary_label = QLabel()
        self.summary_label.setStyleSheet("color: #555")
        self.summary_label.setWordWrap(True)
        self._show_summary_path()
        export_box = QGroupBox("4  Export")
        elay = QVBoxLayout(export_box)
        elay.addWidget(export_results)
        r4 = QHBoxLayout()
        r4.addWidget(append, 1)
        r4.addWidget(choose)
        elay.addLayout(r4)
        elay.addWidget(self.summary_label)
        elay.addWidget(QLabel("<small>Figure and curves: buttons above the plot.</small>"))

        controls = QWidget()
        clay = QVBoxLayout(controls)
        for box in (file_box, range_box, model_box, export_box):
            clay.addWidget(box)
        clay.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(controls)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(560)

        # ---- plot + results
        self.plot = PlotPanel(self.ctx, navigation="minimal", figsize=(8, 6))
        self.plot.set_export_provider(self.export_payload)
        self.plot.set_figure_provider(self.figure_info)
        self.plot.toolbar.setToolTip("Left-drag: fit range | Wheel: zoom (Shift: x, Ctrl: y) "
                                     "| Middle-drag: pan | Home: reset view")
        self.result_label = QLabel("")
        self.result_label.setWordWrap(True)
        self.result_label.setTextFormat(Qt.TextFormat.RichText)
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            ["Label", "Type", "Maximum (cm⁻¹)", "ω₀ (cm⁻¹)", "FWHM (cm⁻¹)",
             "Area (cts·cm⁻¹)", "Area share", "1/q"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        results = QWidget()
        rlay = QVBoxLayout(results)
        rlay.setContentsMargins(0, 0, 0, 0)
        rlay.addWidget(self.result_label)
        rlay.addWidget(self.table, 1)
        right = QSplitter(Qt.Orientation.Vertical)
        right.addWidget(self.plot)
        right.addWidget(results)
        right.setStretchFactor(0, 4)
        right.setStretchFactor(1, 1)
        right.setSizes([700, 190])

        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(scroll)
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        split.setSizes([600, 900])
        self.setCentralWidget(split)

        # ---- log
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(2000)
        dock = QDockWidget("Log", self)
        dock.setObjectName("log")
        dock.setWidget(self.log_view)
        dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable
                         | QDockWidget.DockWidgetFeature.DockWidgetFloatable)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)
        self.resizeDocks([dock], [110], Qt.Orientation.Vertical)

        # ---- menu
        menu = self.menuBar().addMenu("&File")
        act = QAction("&Open spectrum…", self, shortcut=QKeySequence.StandardKey.Open)
        act.triggered.connect(self.open_dialog)
        menu.addAction(act)
        act = QAction("E&xit", self, shortcut=QKeySequence("Ctrl+Q"))
        act.triggered.connect(self.close)
        menu.addAction(act)
        help_menu = self.menuBar().addMenu("&Help")
        act = QAction("&How to use", self)
        act.triggered.connect(self._show_help)
        help_menu.addAction(act)

    def _log(self, text: str, level: str) -> None:
        colour = {"warning": "#b36b00", "error": "#c00000"}.get(level, "#222")
        stamp = _dt.datetime.now().strftime("%H:%M:%S")
        self.log_view.appendHtml(f'<span style="color:{colour}">{stamp}  '
                                 f'{text.replace("<", "&lt;")}</span>')
        if level != "info":
            self.statusBar().showMessage(text, 8000)

    def _show_help(self) -> None:
        QMessageBox.information(self, "How to use", (
            "1. Open a spectrum (Ctrl+O) or drop a .txt file onto the window. A wavelength axis "
            "is converted to Raman shift with the laser wavelength from the file name. Set the "
            "shift offset to correct the calibration.\n\n"
            "2. Select the fit range by left-dragging on the plot (or type it).\n\n"
            "3. Choose a preset (semiconducting: two Voigts, metallic: BWF G⁻ + Voigt G⁺) or "
            "build the model with '+ Add peak'. Auto-guess fills the start values. For every "
            "parameter you can enter bounds and fix it (e.g. the Gaussian Voigt width when the "
            "instrument resolution is known).\n\n"
            "4. Fit (Ctrl+F). The fitted values become the new start values; Revert restores "
            "the previous ones. Areas are the full integrals; for a BWF the Lorentzian-"
            "equivalent area π·I₀·Γ/2. Errors are 1σ including parameter correlations.\n\n"
            "Plot: wheel zoom (Shift: x only, Ctrl: y only), middle-drag pan, Home resets."))

    # ================================================================ files
    def open_dialog(self) -> None:
        path = self.ctx.open_file_dialog("Open Raman spectrum", "Text files (*.txt *.dat *.csv)")
        if path:
            self.load_file(path)

    @staticmethod
    def _dropped_paths(event) -> list[str]:
        mime = event.mimeData()
        if mime is None or not mime.hasUrls():
            return []
        return [u.toLocalFile() for u in mime.urls() if u.isLocalFile()]

    def _handle_drag(self, event) -> bool:
        """Accept a file drag; on drop load the (first) file. ``True`` if handled."""
        paths = self._dropped_paths(event)
        if not paths:
            return False
        event.acceptProposedAction()
        if event.type() == QEvent.Type.Drop:
            if len(paths) > 1:
                self.ctx.log.warning(f"{len(paths)} files dropped; loading only "
                                     f"{Path(paths[0]).name}.")
            self.load_file(paths[0])
        return True

    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt API
        self._handle_drag(event)

    def dragMoveEvent(self, event) -> None:  # noqa: N802 - Qt API
        self._handle_drag(event)

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt API
        self._handle_drag(event)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - Qt API
        # Child widgets that take drops themselves (text fields) would swallow a
        # file; route file drops over them to the window as well.
        if (event.type() in (QEvent.Type.DragEnter, QEvent.Type.DragMove, QEvent.Type.Drop)
                and obj is not self and isinstance(obj, QWidget) and obj.window() is self):
            if self._handle_drag(event):
                return True
        return super().eventFilter(obj, event)

    def load_file(self, path: str | Path) -> bool:
        """Load ``path``; keeps the peak model, optionally auto-guesses."""
        path = Path(path)
        if path.is_dir():
            self.ctx.log.warning(f"{path.name} is a folder; drop a spectrum file.")
            return False
        try:
            spec = load_spectrum(path, laser_nm=None, unit=self.unit_box.currentData(),
                                 offset=0.0)
        except Exception as exc:
            if "laser wavelength" in str(exc) and self.laser_spin.value() > 0:
                try:
                    spec = load_spectrum(path, laser_nm=self.laser_spin.value(),
                                         unit=self.unit_box.currentData())
                except Exception as exc2:
                    return self._load_failed(path, exc2)
            else:
                return self._load_failed(path, exc)
        self.ctx.remember_dir(path)
        self._busy = True
        try:
            if spec.laser_nm is not None:
                self.laser_spin.setValue(spec.laser_nm)
            self.offset_spin.setValue(self._stored_offset())
        finally:
            self._busy = False
        self.spectrum = None
        self._path = path
        if not self._reload_axis():
            return False
        self.result = None
        self._pre_fit = None
        lo, hi = default_range(self.spectrum.shift)
        self._set_range(lo, hi, redraw=False)
        self._setup_plot()
        self.file_label.setText(f"<b>{path.name}</b><br><small>{path.parent}</small>")
        self.setWindowTitle(f"{path.name} – G-mode fit {__version__}")
        self.ctx.log.info(f"Loaded {path.name} ({len(self.spectrum.y)} points, x axis in "
                          f"{self.spectrum.unit}).")
        if self.guess_on_load.isChecked():
            self.auto_guess()
        else:
            self._model_changed()
        return True

    def _load_failed(self, path: Path, exc: Exception) -> bool:
        self.ctx.log.error(f"Could not load {path.name}: {exc}")
        QMessageBox.warning(self, "Open spectrum", f"Could not load {path.name}:\n{exc}")
        return False

    def _stored_offset(self) -> float:
        laser = self.laser_spin.value()
        if laser <= 0:
            return self.offset_spin.value()
        return float(self.settings.value(f"offset/{laser:g}", 0.0, type=float))

    def _reload_axis(self) -> bool:
        """Re-read the current file with the laser / unit / offset fields."""
        laser = self.laser_spin.value() or None
        try:
            spec = load_spectrum(self._path, laser_nm=laser, unit=self.unit_box.currentData(),
                                 offset=self.offset_spin.value())
        except Exception as exc:
            self.ctx.log.error(str(exc))
            return False
        self.spectrum = spec
        if spec.unit == "nm":
            self.axis_label.setText(
                f"File: wavelength {spec.raw_x.min():.2f}–{spec.raw_x.max():.2f} nm → "
                f"{spec.shift.min():.1f}–{spec.shift.max():.1f} cm⁻¹")
        else:
            self.axis_label.setText(f"File: Raman shift {spec.shift.min() - spec.offset:.1f}–"
                                    f"{spec.shift.max() - spec.offset:.1f} cm⁻¹")
        return True

    def _axis_changed(self, what: str) -> None:
        if self._busy or self.spectrum is None:
            if what == "offset" and not self._busy:
                self._remember_offset()
            return
        old_offset = self.spectrum.offset
        if what == "laser":
            self._busy = True
            try:
                self.offset_spin.setValue(self._stored_offset())
            finally:
                self._busy = False
        if what == "offset":
            self._remember_offset()
        if not self._reload_axis():
            return
        lo, hi = self._range()
        if what == "offset":
            delta = self.spectrum.offset - old_offset
            self._set_range(lo + delta, hi + delta, redraw=False)
        else:
            self._set_range(*default_range(self.spectrum.shift), redraw=False)
        self.result = None
        self._setup_plot()
        self._model_changed()

    def _remember_offset(self) -> None:
        laser = self.laser_spin.value()
        if laser > 0:
            self.settings.setValue(f"offset/{laser:g}", self.offset_spin.value())

    # ================================================================ range
    def _range(self) -> tuple[float, float]:
        return self.range_min.value(), self.range_max.value()

    def _range_mid(self) -> float:
        lo, hi = self._range()
        return 0.5 * (lo + hi) if hi > lo else 1590.0

    def _set_range(self, lo: float, hi: float, *, redraw: bool = True) -> None:
        lo, hi = sorted((lo, hi))
        for spin, v in ((self.range_min, lo), (self.range_max, hi)):
            spin.blockSignals(True)
            spin.setValue(v)
            spin.blockSignals(False)
        if redraw:
            self._model_changed()

    def _range_from_spins(self) -> None:
        if self.range_min.value() >= self.range_max.value():
            return
        self._model_changed()

    def _full_range(self) -> None:
        if self.spectrum is not None:
            self._set_range(*default_range(self.spectrum.shift))

    # ================================================================ model
    def peaks(self) -> list[Peak]:
        return [e.peak() for e in self.editors]

    def set_peaks(self, peaks: list[Peak], errors: list[dict] | None = None) -> None:
        """Show ``peaks``, reusing editors where possible."""
        while len(self.editors) > len(peaks):
            self._drop_editor(self.editors[-1])
        for i, peak in enumerate(peaks):
            if i < len(self.editors):
                self.editors[i].set_peak(peak, None if errors is None else errors[i])
            else:
                self._new_editor(peak)
        self._renumber()

    def _new_editor(self, peak: Peak) -> PeakEditor:
        editor = PeakEditor(peak)
        editor.changed.connect(self._model_changed)
        editor.remove_requested.connect(self.remove_peak)
        self.editors.append(editor)
        self.peak_layout.addWidget(editor)
        return editor

    def _drop_editor(self, editor: PeakEditor) -> None:
        self.editors.remove(editor)
        self.peak_layout.removeWidget(editor)
        editor.deleteLater()

    def _renumber(self) -> None:
        for i, e in enumerate(self.editors, 1):
            e.setTitle(f"Peak {i}")

    def add_peak(self, peak: Peak) -> None:
        self._new_editor(peak)
        self._renumber()
        self._model_changed()

    def remove_peak(self, editor: PeakEditor) -> None:
        self._drop_editor(editor)
        self._renumber()
        self._model_changed()

    def apply_preset(self) -> None:
        self.set_peaks(preset(self.preset_box.currentData()))
        if self.spectrum is not None:
            self.auto_guess()
        else:
            self._model_changed()

    def _baseline_changed(self, text: str) -> None:
        self.settings.setValue("baseline", text)
        self._model_changed()

    def _current_peaks(self, action: str) -> list[Peak] | None:
        try:
            return self.peaks()
        except ValueError as exc:
            self.ctx.log.error(f"{action}: {exc}")
            return None

    def auto_guess(self) -> None:
        if self.spectrum is None:
            return
        peaks = self._current_peaks("Auto-guess")
        if peaks is None:
            return
        guessed = auto_guess(self.spectrum.shift, self.spectrum.y, peaks,
                             self.baseline_box.currentText(), self._range())
        self.set_peaks(guessed)
        self.result = None
        self._model_changed()

    def run_fit(self) -> None:
        if self.spectrum is None:
            self.ctx.log.warning("Load a spectrum first.")
            return
        peaks = self._current_peaks("Fit")
        if peaks is None:
            return
        if not peaks:
            self.ctx.log.warning("Add at least one peak.")
            return
        try:
            result = fit(self.spectrum.shift, self.spectrum.y, peaks,
                         self.baseline_box.currentText(), self._range())
        except Exception as exc:
            self.ctx.log.error(f"Fit failed: {exc}")
            QMessageBox.warning(self, "Fit", f"The fit failed:\n{exc}")
            return
        self._pre_fit = peaks
        self.result = result
        self.set_peaks(result.peaks, result.errors)
        level = self.ctx.log.info if result.success else self.ctx.log.warning
        level(f"Fit {'converged' if result.success else 'did not converge'} "
              f"({result.nfev} evaluations): R² = {result.r2:.5f}, "
              f"χ²_red = {result.redchi:.4g}.")
        if result.at_bounds:
            self.ctx.log.warning("At a bound (error unreliable; widen the bound or fix the "
                                 "parameter): " + ", ".join(result.at_bounds))
        self._update_plot()
        self._update_results()

    def revert(self) -> None:
        if self._pre_fit is None:
            return
        self.set_peaks(self._pre_fit)
        self.result = None
        self._model_changed()

    def _model_changed(self) -> None:
        """Start values / range / baseline changed: the shown fit is no longer valid."""
        if self.result is not None:
            self.result = None
        self._update_plot()
        self._update_results()

    # ================================================================= plot
    def _setup_plot(self) -> None:
        """New axes for a (re)loaded spectrum; later updates keep the view."""
        spec = self.spectrum
        panel = self.plot
        panel.clear()
        self._artists = []
        ax, axr = panel.figure.subplots(2, 1, sharex=True, height_ratios=[3, 1])
        self._ax, self._axr = ax, axr
        ax.plot(spec.shift, spec.y, color="0.2", lw=0.8, label="Data", zorder=3)
        ax.set_ylabel("Intensity (counts)")
        ax.set_title(spec.name, fontsize=10)
        axr.axhline(0, color="0.5", lw=0.8)
        axr.set_ylabel("Residual")
        axr.set_xlabel("Raman shift (cm⁻¹)")
        ax.set_xlim(spec.shift.min(), spec.shift.max())
        ax.margins(y=0.08)
        ax.tick_params(labelbottom=False)

        def on_select(lo: float, hi: float) -> None:
            if hi - lo > 0:
                self._set_range(lo, hi)

        self._span = SpanSelector(ax, on_select, "horizontal", useblit=True, button=1,
                                  minspan=0.5, interactive=False,
                                  props={"alpha": 0.2, "facecolor": "tab:orange"})
        panel.draw()

    def _update_plot(self) -> None:
        if self.spectrum is None or self._ax is None:
            return
        ax, axr = self._ax, self._axr
        for artist in self._artists:
            artist.remove()
        self._artists = []
        lo, hi = self._range()
        for a in (ax, axr):
            self._artists.append(a.axvspan(lo, hi, color="tab:orange", alpha=0.08, zorder=0,
                                           lw=0))
        curves = self._curves()
        if curves is not None:
            x, y, total, comps, base, peaks, fitted = curves
            style = "-" if fitted else "--"
            for i, (peak, comp) in enumerate(zip(peaks, comps)):
                colour = _COMP_COLOURS[i % len(_COMP_COLOURS)]
                name = f"{peak.label or 'peak'} ({peak.kind})"
                self._artists.append(ax.fill_between(x, base, base + comp, color=colour,
                                                     alpha=0.18, lw=0, zorder=1))
                self._artists += ax.plot(x, base + comp, color=colour, lw=1.2, ls=style,
                                         label=name, zorder=2)
            if len(base):
                self._artists += ax.plot(x, base, color="0.5", lw=1, ls=":", label="Baseline")
            self._artists += ax.plot(x, total, color="tab:red", lw=1.6, ls=style,
                                     label="Fit" if fitted else "Start model", zorder=4)
            self._artists += axr.plot(x, y - total, color="tab:red" if fitted else "0.5",
                                      lw=0.8)
            res = y - total
            if len(res):
                pad = 0.1 * (np.ptp(res) or 1.0)
                axr.set_ylim(res.min() - pad, res.max() + pad)
        legend = ax.legend(fontsize=8, loc="best")
        self._artists.append(legend)
        self.plot.canvas.draw_idle()

    def _curves(self):
        """``(x, y, total, comps, base, peaks, fitted)`` of the result or the start model."""
        if self.result is not None:
            r = self.result
            return r.x, r.y, r.best, r.components, r.baseline_curve, r.peaks, True
        try:
            peaks = self.peaks()
        except ValueError:
            return None
        lo, hi = self._range()
        if hi <= lo:
            return None
        x, y, total, comps, base, _c, _r = start_model(
            self.spectrum.shift, self.spectrum.y, peaks, self.baseline_box.currentText(), (lo, hi))
        if len(x) < 2:
            return None
        return x, y, total, comps, base, peaks, False

    # ============================================================== results
    def _update_results(self) -> None:
        r = self.result
        if r is None:
            self.table.setRowCount(0)
            self.result_label.setText("<i>No fit yet – adjust the start values and press "
                                      "Fit (Ctrl+F). Dashed: start model.</i>"
                                      if self.spectrum is not None else "")
            return
        self.table.setRowCount(len(r.peaks))
        total_area = sum(p.params["area"].value for p in r.peaks)
        for i, peak in enumerate(r.peaks):
            d = r.derived(i)
            err = r.errors[i]
            fwhm_name = "fwhm" if "fwhm" in peak.params else None
            cells = [
                peak.label, peak.kind,
                fmt_pm(*d["position_max"]),
                fmt_pm(peak.params["center"].value, err["center"], peak.params["center"].fixed),
                fmt_pm(*d["fwhm_total"], fixed=bool(fwhm_name and peak.params["fwhm"].fixed)),
                fmt_pm(peak.params["area"].value, err["area"], peak.params["area"].fixed),
                f"{100 * peak.params['area'].value / total_area:.1f} %" if total_area else "–",
                fmt_pm(peak.params["inv_q"].value, err["inv_q"], peak.params["inv_q"].fixed)
                if "inv_q" in peak.params else "",
            ]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if col == 0:
                    item.setForeground(QColor(_COMP_COLOURS[i % len(_COMP_COLOURS)]))
                self.table.setItem(i, col, item)
        ratio, ratio_err = r.ratio()
        parts = []
        if np.isfinite(ratio):
            parts.append(f"<b>A(G⁻)/A(G⁺) = {fmt_pm(ratio, ratio_err)}</b>")
        else:
            parts.append("<i>Label one peak G- and one G+ for the area ratio.</i>")
        parts.append(f"R² = {r.r2:.5f}")
        parts.append(f"χ²<sub>red</sub> = {r.redchi:.4g}")
        parts.append(f"{len(r.x)} points, {r.n_free} free parameters")
        if not r.success:
            parts.append(f"<span style='color:#c00000'>not converged: {r.message}</span>")
        if r.at_bounds:
            parts.append("<span style='color:#b36b00'>at bound: "
                         + ", ".join(r.at_bounds) + "</span>")
        self.result_label.setText(" &nbsp;|&nbsp; ".join(parts))

    def _parameters(self) -> dict:
        lo, hi = self._range()
        spec = self.spectrum
        try:
            peaks = self.result.peaks if self.result else self.peaks()
        except ValueError:
            peaks = []
        params = {
            "laser_nm": spec.laser_nm if spec else None,
            "file_x_unit": spec.unit if spec else None,
            "shift_offset_cm-1": self.offset_spin.value(),
            "range_cm-1": [lo, hi],
            "baseline": self.baseline_box.currentText(),
            "model": self._model_text(peaks),
        }
        # Start/fitted value, bounds and fixed flag of every parameter.
        for i, peak in enumerate(peaks, 1):
            params[f"peak{i}"] = {"label": peak.label, "type": peak.kind,
                                  **{n: [p.value, p.min, p.max, p.fixed]
                                     for n, p in peak.params.items()}}
        return params

    @staticmethod
    def _model_text(peaks: list[Peak]) -> str:
        return " + ".join(f"{p.kind}({p.label})" if p.label else p.kind for p in peaks)

    def _metadata(self) -> dict:
        r = self.result
        results = r.summary() if r is not None else None
        if r is not None:
            results["baseline_coeffs"] = list(r.baseline_coeffs)
            results["baseline_x_ref"] = r.x_ref
        return build_metadata(_ANALYSIS, sources=[self.spectrum.path] if self.spectrum else [],
                              parameters=self._parameters(), results=results,
                              software=f"gmode_fit {__version__}")

    def _stem(self) -> str:
        return self.spectrum.path.stem if self.spectrum else "gmode_fit"

    def export_payload(self) -> ExportPayload | None:
        """Curves in the fit range for the plot's *Export data* button."""
        curves = self._curves() if self.spectrum is not None else None
        if curves is None:
            return None
        x, y, total, comps, base, peaks, fitted = curves
        units = {"x": "cm-1", "y": "counts"}
        signals = [Signal(x, y, "data", units), Signal(x, total, "fit" if fitted else "start model",
                                                       units)]
        if len(base):
            signals.append(Signal(x, base, "baseline", units))
        for i, (peak, comp) in enumerate(zip(peaks, comps), 1):
            signals.append(Signal(x, comp, f"peak{i} {peak.label} {peak.kind}".strip(), units))
        signals.append(Signal(x, y - total, "residual", units))
        return ExportPayload(self._metadata(), signals=signals,
                             default_name=f"{self._stem()}_curves")

    def figure_info(self):
        if self.spectrum is None:
            return None
        return f"{self._stem()}_fit", self._metadata()

    def export_results(self) -> None:
        if self.result is None:
            QMessageBox.information(self, "Export results", "Fit the spectrum first.")
            return
        path = self.ctx.save_file_dialog("Export results", f"{self._stem()}_fit.csv",
                                         "CSV file (*.csv)")
        if not path:
            return
        path = Path(path).with_suffix(".csv")
        try:
            write_table_csv(path, self.result.table(), self._metadata())
        except Exception as exc:
            QMessageBox.warning(self, "Export results", f"Could not write the file:\n{exc}")
            return
        self.ctx.log.info(f"Results exported: {path}")

    # -------------------------------------------------------------- summary
    def _summary_path(self) -> Path | None:
        value = self.settings.value("summary_path", "")
        return Path(value) if value else None

    def _show_summary_path(self) -> None:
        path = self._summary_path()
        self.summary_label.setText(f"<small>Summary file: {path}</small>" if path else
                                   "<small>Summary file: not chosen yet</small>")

    def _choose_summary(self) -> Path | None:
        start = str(self._summary_path() or Path(self.ctx.last_dir) / "gmode_summary.csv")
        path, _ = QFileDialog.getSaveFileName(
            self, "Summary CSV (rows are appended)", start, "CSV file (*.csv)",
            options=QFileDialog.Option.DontConfirmOverwrite)
        if not path:
            return None
        path = Path(path).with_suffix(".csv")
        self.settings.setValue("summary_path", str(path))
        self._show_summary_path()
        return path

    def summary_row(self) -> dict:
        """The row added to the summary CSV for the current fit."""
        lo, hi = self._range()
        spec = self.spectrum
        row = {
            "file": spec.name,
            "folder": str(spec.path.parent),
            "fitted": _dt.datetime.now().isoformat(timespec="seconds"),
            "laser_nm": spec.laser_nm,
            "shift_offset_cm-1": self.offset_spin.value(),
            "range_min_cm-1": lo,
            "range_max_cm-1": hi,
            "baseline": self.result.baseline,
            "model": self._model_text(self.result.peaks),
        }
        row.update(self.result.summary())
        return row

    def append_summary(self) -> None:
        if self.result is None:
            QMessageBox.information(self, "Summary", "Fit the spectrum first.")
            return
        path = self._summary_path() or self._choose_summary()
        if path is None:
            return
        try:
            append_row(path, self.summary_row())
        except Exception as exc:
            QMessageBox.warning(self, "Summary", f"Could not write {path}:\n{exc}")
            return
        self.ctx.log.info(f"Added {self.spectrum.name} to {path.name}.")

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        self.settings.setValue("guess_on_load", self.guess_on_load.isChecked())
        QApplication.instance().removeEventFilter(self)
        super().closeEvent(event)


def _cell(value) -> str:
    if isinstance(value, (float, np.floating)):
        return "" if not np.isfinite(value) else repr(float(value))
    return "" if value is None else str(value)


def append_row(path: str | Path, row: dict) -> Path:
    """Append ``row`` to a CSV; a new file gets a header, an existing one keeps its columns.

    Columns of ``row`` missing from an existing header are appended to the
    header line (the file is rewritten), so older rows get empty cells.
    """
    path = Path(path)
    if path.exists() and path.stat().st_size > 0:
        with open(path, newline="", encoding="utf-8") as fh:
            rows = list(csv.reader(fh))
        header = rows[0]
        missing = [k for k in row if k not in header]
        if missing:
            header = header + missing
            with open(path, "w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow(header)
                writer.writerows(r + [""] * (len(header) - len(r)) for r in rows[1:])
        with open(path, "a", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerow([_cell(row.get(k)) for k in header])
    else:
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(list(row))
            writer.writerow([_cell(v) for v in row.values()])
    return path


def main(argv: list[str] | None = None) -> int:
    """Start the window; an optional file argument is loaded right away."""
    argv = sys.argv if argv is None else argv
    app = QApplication.instance() or QApplication(argv)
    app.setApplicationName("G-mode fit")
    window = MainWindow()
    install_log_capture(window.ctx.log)
    window.resize(1500, 950)
    window.show()
    files = [a for a in argv[1:] if Path(a).is_file()]
    if files:
        window.load_file(files[0])
    return app.exec()
