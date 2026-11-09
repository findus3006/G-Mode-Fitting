import csv

import numpy as np
import pytest
from matplotlib.backend_bases import MouseButton, MouseEvent
from PySide6.QtCore import QMimeData, QPointF, QSettings, Qt, QUrl
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QApplication

from gmode_fit.gui import MainWindow, append_row

from conftest import DATA, needs_data


@pytest.fixture
def window(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr("PySide6.QtWidgets.QMessageBox.warning", lambda *a, **k: None)
    monkeypatch.setattr("PySide6.QtWidgets.QMessageBox.information", lambda *a, **k: None)
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    w = MainWindow(settings)
    qtbot.addWidget(w)
    w.resize(1400, 900)
    w.show()
    return w


@needs_data
def test_load_guess_fit(window):
    assert window.load_file(DATA / "Probe1_633nm_G.txt")
    assert window.spectrum.unit == "cm-1"
    assert len(window.editors) == 2
    window.run_fit()
    r = window.result
    assert r is not None and r.success
    assert window.table.rowCount() == 2
    assert "A(G⁻)/A(G⁺)" in window.result_label.text()
    # fitted values were written back as start values
    assert window.peaks()[1].params["center"].value == pytest.approx(
        r.peaks[1].params["center"].value)


@needs_data
def test_offset_shifts_axis_and_range(window):
    window.load_file(DATA / "Probe2_532nm_G.txt")
    assert window.laser_spin.value() == 532.0
    x0 = window.spectrum.shift.copy()
    lo, hi = window._range()
    window.offset_spin.setValue(-16.0)
    assert np.allclose(window.spectrum.shift, x0 - 16.0)
    assert window._range() == pytest.approx((lo - 16.0, hi - 16.0))
    # remembered per laser
    assert window.settings.value("offset/532", type=float) == -16.0


@needs_data
def test_span_selection_sets_range(window):
    window.load_file(DATA / "Probe2_532nm_G.txt")
    ax = window._ax
    canvas = window.plot.canvas
    canvas.draw()

    def event(name, xdata):
        x, y = ax.transData.transform((xdata, np.mean(ax.get_ylim())))
        return MouseEvent(name, canvas, x, y, button=MouseButton.LEFT)

    canvas.callbacks.process("button_press_event", event("button_press_event", 1550))
    canvas.callbacks.process("motion_notify_event", event("motion_notify_event", 1640))
    canvas.callbacks.process("button_release_event", event("button_release_event", 1640))
    lo, hi = window._range()
    assert lo == pytest.approx(1550, abs=1) and hi == pytest.approx(1640, abs=1)


@needs_data
def test_change_type_and_fix(window):
    window.load_file(DATA / "Probe2_532nm_G.txt")
    ed = window.editors[0]
    ed.kind_box.setCurrentText("Lorentz")
    assert window.peaks()[0].kind == "Lorentz"
    ed2 = window.editors[1]
    ed2.rows["fwhm_g"]["value"].setText("2.5")
    ed2.rows["fwhm_g"]["fix"].setChecked(True)
    window.run_fit()
    assert window.result.peaks[1].params["fwhm_g"].value == 2.5


@needs_data
def test_add_remove_peak_and_invalid_value(window):
    window.load_file(DATA / "Probe2_532nm_G.txt")
    window.add_peak(window.peaks()[0].converted("Gauss"))
    assert len(window.editors) == 3
    window.remove_peak(window.editors[2])
    assert len(window.editors) == 2
    window.editors[0].rows["area"]["value"].setText("abc")
    window.run_fit()
    assert window.result is None


def _drop(path):
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path))])
    event = QDropEvent(QPointF(10, 10), Qt.DropAction.CopyAction, mime,
                       Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    return event, mime          # keep mime alive as long as the event


@needs_data
def test_drop_file(window):
    # Qt delivers drops only during a real drag, so call the handlers directly.
    event, _mime = _drop(DATA / "Probe2_633nm_G.txt")
    window.dropEvent(event)
    assert window.spectrum.name == "Probe2_633nm_G.txt"
    # a drop over a text field (which would take the text itself) also loads the file
    event, _mime = _drop(DATA / "Probe1_633nm_G.txt")
    assert window.eventFilter(window.editors[0].label_box.lineEdit(), event)
    assert window.spectrum.name == "Probe1_633nm_G.txt"


@needs_data
def test_exports(window, tmp_path, monkeypatch):
    window.load_file(DATA / "Probe1_532nm_G.txt")
    window.run_fit()
    out = tmp_path / "res.csv"
    monkeypatch.setattr(window.ctx, "save_file_dialog", lambda *a: str(out))
    window.export_results()
    text = out.read_text(encoding="utf-8")
    assert text.startswith("#") and "inv_q_err" in text
    payload = window.export_payload()
    assert payload.signals[0].label == "data" and payload.signals[-1].label == "residual"

    summary = tmp_path / "summary.csv"
    window.settings.setValue("summary_path", str(summary))
    window.append_summary()
    window.load_file(DATA / "Probe2_532nm_G.txt")
    window.run_fit()
    window.append_summary()
    rows = list(csv.DictReader(summary.open(encoding="utf-8")))
    assert [r["file"] for r in rows] == ["Probe1_532nm_G.txt", "Probe2_532nm_G.txt"]
    assert float(rows[0]["ratio_Gminus_Gplus"]) > 0


def test_append_row_adds_new_columns(tmp_path):
    p = tmp_path / "s.csv"
    append_row(p, {"a": 1, "b": 2.0})
    append_row(p, {"a": 3, "c": "x"})
    rows = list(csv.DictReader(p.open()))
    assert rows == [{"a": "1", "b": "2.0", "c": ""}, {"a": "3", "b": "", "c": "x"}]
