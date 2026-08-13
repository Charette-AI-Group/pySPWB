"""WAV integration with the Time Processing window."""
import os

import numpy as np
import pytest
from scipy.io import wavfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6.QtWidgets import QApplication

from spwb import Signal
from spwb.gui.bridge import WindowManager
from spwb.gui.time_processing import TimeProcessingWindow
from spwb.processing.io import SAVE_OPTIONS, read_wave

FS = 8000


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp):
    w = TimeProcessingWindow(WindowManager())
    yield w
    w.close()


def make_wav(path, amp=1.0, n=1000, channels=1):
    t = np.arange(n) / FS
    y = np.sin(2 * np.pi * 200 * t) * amp
    data = np.round(np.clip(y, -1, 1) * 32767).astype(np.int16)
    if channels > 1:
        data = np.column_stack([data] * channels)
    wavfile.write(str(path), FS, data)
    return path


def test_loading_a_wave_populates_the_window(window, tmp_path):
    window._load_waves([str(make_wav(tmp_path / "tone.wav"))])
    assert len(window.store) == 1
    assert window.tree.topLevelItemCount() == 1
    assert len(window.plot.plotItem.listDataItems()) == 1
    assert next(iter(window.store)).x_unit == "sec"


def test_status_reports_a_missing_scale_factor(window, tmp_path):
    window._load_waves([str(make_wav(tmp_path / "plain.wav"))])
    assert "no scale factor" in window.statusBar().currentMessage()


def test_status_reports_an_applied_scale_factor(window, tmp_path):
    window._load_waves([str(make_wav(tmp_path / "a_scale_9.81_m-per-s2.wav"))])
    assert "carried a scale factor" in window.statusBar().currentMessage()
    sig = next(iter(window.store))
    assert np.abs(sig.y).max() == pytest.approx(9.81, rel=1e-3)
    assert sig.y_unit == "m/s2"


def test_loading_several_files_keeps_names_unique(window, tmp_path):
    paths = [str(make_wav(tmp_path / f"{n}.wav", channels=2))
             for n in ("one", "two")]
    window._load_waves(paths)
    names = [s.name for s in window.store]
    assert len(names) == len(set(names)) == 4


def test_bad_file_is_reported_not_crashed(window, tmp_path, monkeypatch):
    bad = tmp_path / "broken.wav"
    bad.write_bytes(b"not a wave file at all")
    shown = {}
    monkeypatch.setattr(
        "spwb.gui.time_processing.QMessageBox.critical",
        lambda *args, **kw: shown.setdefault("msg", args[2]))
    window._load_waves([str(bad)])
    assert "Could not read" in shown["msg"]
    assert len(window.store) == 0


# -- saving ------------------------------------------------------------------
def _save(window, monkeypatch, tmp_path, name, option=None):
    monkeypatch.setattr(
        "spwb.gui.time_processing.QFileDialog.getSaveFileName",
        lambda *a, **k: (str(tmp_path / name), ""))
    if option is not None:
        monkeypatch.setattr(
            "spwb.gui.time_processing.QInputDialog.getItem",
            lambda *a, **k: (option, True))
    window.save_wave()


def test_save_and_reload_preserves_engineering_units(window, monkeypatch,
                                                     tmp_path):
    t = np.arange(2000) / FS
    window.store.add(Signal("accel", 9.81 * np.sin(2 * np.pi * 200 * t),
                            1 / FS, y_unit="m/s2"))
    _save(window, monkeypatch, tmp_path, "out.wav")
    written = list(tmp_path.glob("*.wav"))
    assert len(written) == 1 and "scale" in written[0].name

    (back,) = read_wave(written[0])
    assert back.y_unit == "m/s2"
    assert np.abs(back.y).max() == pytest.approx(9.81, rel=1e-3)


def test_save_offers_options_only_for_multiple_signals(window, monkeypatch,
                                                       tmp_path):
    t = np.arange(500) / FS
    for name in ("a", "b"):
        window.store.add(Signal(name, np.sin(2 * np.pi * 200 * t), 1 / FS))
    asked = {}
    monkeypatch.setattr(
        "spwb.gui.time_processing.QInputDialog.getItem",
        lambda *a, **k: (asked.setdefault("choices", a[3]) and None)
        or (SAVE_OPTIONS[1], True))
    _save(window, monkeypatch, tmp_path, "multi.wav")
    # 2 signals -> both stereo options offered as well
    assert len(asked["choices"]) == 4
    assert len(list(tmp_path.glob("*.wav"))) == 1     # concatenated


def test_save_refuses_mixed_sample_rates(window, monkeypatch, tmp_path):
    window.store.add(Signal("a", np.zeros(100), 1 / 8000))
    window.store.add(Signal("b", np.zeros(100), 1 / 44100))
    shown = {}
    monkeypatch.setattr(
        "spwb.gui.time_processing.QMessageBox.warning",
        lambda *args, **kw: shown.setdefault("msg", args[2]))
    window.save_wave()
    assert "one sample rate" in shown["msg"]
    assert list(tmp_path.glob("*.wav")) == []


def test_save_with_nothing_visible_is_reported(window, monkeypatch, tmp_path):
    shown = {}
    monkeypatch.setattr(
        "spwb.gui.time_processing.QMessageBox.information",
        lambda *args, **kw: shown.setdefault("msg", args[2]))
    window.save_wave()
    assert "No signals" in shown["msg"]


def test_full_round_trip_through_the_window(window, monkeypatch, tmp_path):
    """Load a WAV, save it back, reload: amplitude and unit survive."""
    src = make_wav(tmp_path / "src_scale_2.50_Pa.wav")
    window._load_waves([str(src)])
    original = next(iter(window.store))
    _save(window, monkeypatch, tmp_path, "again.wav")

    written = [p for p in tmp_path.glob("again*.wav")]
    assert len(written) == 1
    (back,) = read_wave(written[0])
    assert back.y_unit == "Pa"
    np.testing.assert_allclose(back.y, original.y, atol=2.5 / 32767 * 4)
