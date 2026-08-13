"""Time-Frequency window - offscreen logic tests."""
import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6.QtWidgets import QApplication

from spwb import Signal
from spwb.gui.bridge import WindowManager
from spwb.gui.tfa_analysis import TimeFrequencyWindow
from spwb.gui.time_processing import TimeProcessingWindow

FS = 1024.0
N = 8192
DT = 1.0 / FS


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def manager(qapp):
    return WindowManager()


def tone(name="tone", f=128.0, amp=1.0, unit="Pa"):
    t = np.arange(N) * DT
    return Signal(name, amp * np.sin(2 * np.pi * f * t), DT, y_unit=unit)


def chirp(name="chirp"):
    t = np.arange(N) * DT
    return Signal(name, np.sin(2 * np.pi * (50 * t + 175 / t[-1] * t ** 2)),
                  DT)


@pytest.fixture
def window(manager, qapp):
    w = TimeFrequencyWindow(manager)
    # give the widget real geometry: the click test needs the view transform
    # to be invertible, which requires a laid-out viewport
    w.resize(1200, 800)
    w.show()
    qapp.processEvents()
    w.store.add(tone())
    w.block_size.setCurrentText("256")
    yield w
    w.close()


def test_window_name_uses_the_tfa_prefix(manager):
    w = TimeFrequencyWindow(manager)
    assert w.window_name == "TFA 00"
    w.close()


def test_empty_window_reports_and_does_not_crash(manager):
    w = TimeFrequencyWindow(manager)
    assert w._spectrogram is None
    assert "Import a signal" in w.statusBar().currentMessage()
    w.close()


def test_adding_a_signal_computes_a_spectrogram(window):
    assert window.channel.count() == 1
    spec = window._spectrogram
    assert spec is not None
    assert spec.n_bins == 128                        # block 256 -> 128 bins
    assert spec.df == pytest.approx(FS / 256)
    assert window.image.image is not None


def test_channel_selector_switches_signals(window):
    window.store.add(chirp())
    assert window.channel.count() == 2
    window.channel.setCurrentIndex(1)
    assert window.selected_signal.name == "chirp"
    ridge = window._spectrogram.freqs[
        window._spectrogram.data[3:-3].argmax(axis=1)]
    assert ridge[-1] > ridge[0]                      # the chirp climbs


def test_block_size_and_overlap_reach_the_result(window):
    window.block_size.setCurrentText("512")
    assert window._spectrogram.n_bins == 256
    assert window._spectrogram.attributes["TFA_Block_Size"] == 512
    window.overlap.setValue(50)
    assert window._spectrogram.attributes["TFA_Hop"] == 256


def test_window_type_reaches_the_result(window):
    window.window_box.setCurrentText("Flat Top")
    assert window._spectrogram.attributes["TFA_Window_Type"] == "flat_top"


def test_normalize_checkbox_reaches_the_result(window):
    window.normalize.setChecked(True)
    assert window._spectrogram.attributes["TFA_Normalized"] is True


def test_too_large_a_block_is_reported_not_crashed(manager):
    w = TimeFrequencyWindow(manager)
    w.store.add(Signal("short", np.zeros(200), DT))
    w.block_size.setCurrentText("1024")
    assert w._spectrogram is None
    assert "exceeds" in w.statusBar().currentMessage()
    w.block_size.setCurrentText("128")               # recovers
    assert w._spectrogram is not None
    w.close()


# -- the cursor and its two sections -----------------------------------------
def test_cursor_starts_centred_and_drives_both_sections(window):
    spec = window._spectrogram
    assert window.v_line.value() == pytest.approx(float(np.median(spec.times)))
    assert window.h_line.value() == pytest.approx(float(np.median(spec.freqs)))
    assert len(window.time_curve.getData()[0]) == spec.n_bins
    assert len(window.freq_curve.getData()[0]) == spec.n_frames


def test_moving_the_cursor_updates_the_sections(window):
    """On the tone: high and steady. Off the tone: much lower."""
    window.db_on.setChecked(False)                   # compare in linear units
    window.h_line.setValue(128.0)
    _, on_tone = window.freq_curve.getData()
    assert len(on_tone) == window._spectrogram.n_frames
    interior = on_tone[3:-3]
    assert interior.std() < interior.mean() * 0.1    # steady across time

    window.h_line.setValue(400.0)                    # away from the tone
    _, off_tone = window.freq_curve.getData()
    assert off_tone[3:-3].mean() < interior.mean() * 1e-3


def test_time_section_peaks_at_the_tone_frequency(window):
    window.v_line.setValue(4.0)
    freqs, values = window.time_curve.getData()
    assert freqs[int(np.argmax(values))] == pytest.approx(
        128.0, abs=window._spectrogram.df)


def test_cursor_label_reports_the_snapped_point(window):
    window.v_line.setValue(2.0)
    window.h_line.setValue(128.0)
    text = window.cursor_label.text()
    assert "Cursor:" in text and "Hz" in text and "dB" in text


def test_clicking_the_plot_moves_the_crosshair(window, qapp):
    """A click anywhere on the spectrogram repositions both cursor lines."""
    class FakeEvent:
        def __init__(self, pos):
            self._pos = pos

        def scenePos(self):
            return self._pos

    qapp.processEvents()          # let the view settle after the image is set
    view = window.image_plot.plotItem.vb
    target = view.mapViewToScene(pg_point(3.0, 200.0))
    assert window.image_plot.sceneBoundingRect().contains(target)
    window._on_click(FakeEvent(target))
    assert window.v_line.value() == pytest.approx(3.0, abs=0.5)
    assert window.h_line.value() == pytest.approx(200.0, abs=20.0)


def test_clicking_outside_the_plot_is_ignored(window, qapp):
    class FakeEvent:
        def __init__(self, pos):
            self._pos = pos

        def scenePos(self):
            return self._pos

    qapp.processEvents()
    before = window.v_line.value()
    window._on_click(FakeEvent(pg_point(-500.0, -500.0)))
    assert window.v_line.value() == before


def pg_point(x, y):
    from PySide6.QtCore import QPointF
    return QPointF(x, y)


# -- dB display --------------------------------------------------------------
def test_db_toggle_changes_the_displayed_values(window):
    assert window.db_on.isChecked()
    assert window._display.y_unit == "dB"
    assert window._display.data.max() == pytest.approx(0.0, abs=1e-9)
    window.db_on.setChecked(False)
    assert window._display.y_unit != "dB"
    assert window._display.data.max() > 0.0


def test_dynamic_range_bounds_the_colour_scale(window):
    window.dynamic_range.setValue(60.0)
    assert window._display.data.min() >= -60.0 - 1e-9
    low, high = window.image.levels
    assert high - low <= 60.0 + 1e-6


def test_raw_spectrogram_is_untouched_by_the_display_toggle(window):
    raw_max = window._spectrogram.data.max()
    window.db_on.setChecked(False)
    window.db_on.setChecked(True)
    assert window._spectrogram.data.max() == raw_max


@pytest.mark.parametrize("table", ["rainbow", "fire", "gray", "viridis"])
def test_every_colour_table_applies(window, table):
    window.color_table.setCurrentText(table)
    assert window.image.getColorMap() is not None


# -- export and cross-window flow --------------------------------------------
def test_sections_copy_as_tsv(window, qapp):
    window.copy_sections()
    text = qapp.clipboard().text()
    assert "Time Section" in text and "Frequency Section" in text
    assert "Frequency (Hz)\tAmplitude" in text
    assert "Time (sec)\tAmplitude" in text


def test_time_processing_sends_signals_to_a_tfa_window(manager):
    tdp = TimeProcessingWindow(manager)
    tdp.store.add(tone("accel"))
    tfa = tdp.open_tfa_window()
    assert isinstance(tfa, TimeFrequencyWindow)
    assert tfa.window_name == "TFA 00"
    assert [s.name for s in tfa.store] == ["accel"]
    assert {s.sid for s in tfa.store}.isdisjoint({s.sid for s in tdp.store})
    assert tfa._spectrogram is not None
    tfa.close()
    tdp.close()


def test_removing_the_signal_clears_the_display(window):
    sig = next(iter(window.store))
    window.store.remove(sig.sid)
    assert window.channel.count() == 0
    assert window._spectrogram is None
    # pyqtgraph reports a cleared curve as None rather than an empty array
    x, _ = window.time_curve.getData()
    assert x is None or len(x) == 0
    assert "Import a signal" in window.statusBar().currentMessage()
