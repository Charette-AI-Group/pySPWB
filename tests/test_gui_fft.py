"""FFT Analysis window - offscreen logic tests."""
import math
import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from spwb import Signal
from spwb.gui.bridge import WindowManager
from spwb.gui.fft_analysis import FFTWindow
from spwb.gui.time_processing import TimeProcessingWindow

AMPLITUDE = 3.0
FREQ = 128.0
FS = 1024.0


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def manager(qapp):
    return WindowManager()


def make_signal(name="sine", amp=AMPLITUDE, f=FREQ, fs=FS, n=4096, unit="Pa"):
    dt = 1.0 / fs
    t = np.arange(n) * dt
    return Signal(name, amp * np.sin(2 * np.pi * f * t), dt, y_unit=unit)


@pytest.fixture
def window(manager):
    w = FFTWindow(manager)
    w.store.add(make_signal())
    yield w
    w.close()


def bin_of(window, freq=FREQ):
    spec = next(iter(window._spectra.values()))
    return int(round(freq / spec.dt))


# -- basics ------------------------------------------------------------------
def test_window_name_uses_the_fft_prefix(manager):
    w = FFTWindow(manager)
    assert w.window_name == "FFT 00"
    w.close()


def test_adding_a_signal_computes_and_plots_a_spectrum(window):
    assert len(window._spectra) == 1
    assert window.tree.topLevelItemCount() == 1
    assert len(window.plot.plotItem.listDataItems()) == 1
    item = window.tree.topLevelItem(0)
    assert item.text(0) == "sine"
    assert item.text(2) == "1"                        # df = 1 Hz default


def test_default_reading_is_the_rms_amplitude(window):
    spec = next(iter(window._spectra.values()))
    assert spec.y[bin_of(window)] == pytest.approx(AMPLITUDE / math.sqrt(2),
                                                   rel=1e-6)


def test_unchecking_hides_the_trace(window):
    window.store.add(make_signal("second", f=256.0))
    assert len(window.plot.plotItem.listDataItems()) == 2
    window.tree.topLevelItem(0).setCheckState(0, Qt.Unchecked)
    assert len(window.plot.plotItem.listDataItems()) == 1
    assert len(window._spectra) == 2                  # still computed


# -- controls drive recomputation --------------------------------------------
def test_changing_resolution_changes_the_spectrum_length(window):
    before = next(iter(window._spectra.values())).n_samples
    window.freq_resolution.setValue(2.0)
    after = next(iter(window._spectra.values()))
    assert after.dt == pytest.approx(2.0)
    assert after.n_samples < before
    assert after.y[bin_of(window)] == pytest.approx(AMPLITUDE / math.sqrt(2),
                                                    rel=1e-3)


def test_overlap_increases_the_average_count(window):
    window.freq_resolution.setValue(1.0)
    assert window._spectra[next(iter(window._spectra))]\
        .attributes["FFT_Nb_Averages"] == 4
    window.overlap.setValue(50.0)
    assert window._spectra[next(iter(window._spectra))]\
        .attributes["FFT_Nb_Averages"] == 7


@pytest.mark.parametrize("label", ["Rectangle", "Flat Top", "Kaiser"])
def test_window_choice_preserves_amplitude(window, label):
    window.window_box.setCurrentText(label)
    spec = next(iter(window._spectra.values()))
    assert spec.y[bin_of(window)] == pytest.approx(AMPLITUDE / math.sqrt(2),
                                                   rel=2e-3)
    assert spec.attributes["FFT_Window_Type"] == window.window_name_selected


def test_window_parameter_enabled_only_for_parametrised_windows(window):
    window.window_box.setCurrentText("Hanning")
    assert not window.window_parameter.isEnabled()
    window.window_box.setCurrentText("Kaiser")
    assert window.window_parameter.isEnabled()
    window.window_box.setCurrentText("Gaussian")
    assert window.window_parameter.value() == pytest.approx(0.2)


def test_function_type_and_display_option_reach_the_plot(window):
    window.function_type.setCurrentText("Power Spectrum - (EU RMS²)")
    spec = next(iter(window._spectra.values()))
    assert spec.y[bin_of(window)] == pytest.approx(AMPLITUDE ** 2 / 2, rel=1e-6)

    window.display_option.setCurrentText("dB - NO reference value")
    spec = next(iter(window._spectra.values()))
    assert spec.y[bin_of(window)] == pytest.approx(
        10 * math.log10(AMPLITUDE ** 2 / 2), rel=1e-6)
    assert window.tree.topLevelItem(0).text(3) == "dB"


def test_a_weighting_reaches_the_plot(window):
    plain = next(iter(window._spectra.values())).y[bin_of(window)]
    window.weighting.setCurrentText("A-weighting")
    weighted = next(iter(window._spectra.values()))
    from spwb.processing.dsp import spectral as S
    expected = plain * 10 ** (S.a_weighting(np.array([FREQ]))[0] / 20)
    assert weighted.y[bin_of(window)] == pytest.approx(expected, rel=1e-9)
    assert "[A-Weighted]" in weighted.y_unit


def test_unreachable_resolution_is_clamped_and_reported(window):
    """Asking for finer df than the record supports uses the whole record."""
    window.freq_resolution.setValue(1e-4)     # would need ~10M samples
    spec = next(iter(window._spectra.values()))
    assert spec.dt == pytest.approx(FS / 4096)          # whole-record df
    assert spec.attributes["FFT_Nb_Averages"] == 1
    message = window.statusBar().currentMessage()
    assert "not possible" in message and "0.25" in message
    window.freq_resolution.setValue(1.0)                # and it recovers
    assert next(iter(window._spectra.values())).dt == pytest.approx(1.0)
    assert "not possible" not in window.statusBar().currentMessage()


def test_graph_options_toggle_log_axes(window):
    window.log_x.setCurrentText("Logarithmic")
    window.log_y.setCurrentText("Logarithmic")
    assert window.plot.plotItem.ctrl.logXCheck.isChecked()
    assert window.plot.plotItem.ctrl.logYCheck.isChecked()


def test_log_frequency_axis_drops_the_dc_bin(window):
    """log10(0 Hz) is -inf, which would blank the whole plot."""
    window.log_x.setCurrentText("Logarithmic")
    item = window.plot.plotItem.listDataItems()[0]
    freqs = item.xData
    assert freqs[0] > 0
    assert np.isfinite(freqs).all()
    assert len(freqs) == next(iter(window._spectra.values())).n_samples - 1
    window.log_x.setCurrentText("Linear")
    assert window.plot.plotItem.listDataItems()[0].xData[0] == 0.0


def test_db_view_stays_in_a_plottable_range(window):
    """Regression: a machine-epsilon floor gave ~-6000 dB and broke autoscale."""
    window.display_option.setCurrentText("dB - NO reference value")
    spec = next(iter(window._spectra.values()))
    assert np.isfinite(spec.y).all()
    assert spec.y.max() - spec.y.min() <= 400.0 + 1e-6


# -- energy band -------------------------------------------------------------
def test_energy_band_totals_the_power_in_range(window):
    window.band_start.setValue(0.0)
    window.band_end.setValue(FS / 2)
    assert window.band_table.rowCount() == 1
    rms_text = window.band_table.item(window.band_table.rowCount() - 1, 1).text()
    assert float(rms_text.split()[0]) == pytest.approx(AMPLITUDE / math.sqrt(2),
                                                       rel=1e-3)


def test_energy_band_excludes_out_of_range_content(window):
    window.band_start.setValue(0.0)
    window.band_end.setValue(FREQ / 2)         # tone sits above the band
    value = float(window.band_table.item(0, 1).text().split()[0])
    assert value < 0.01 * AMPLITUDE


def test_energy_band_copies_as_tsv(window, qapp):
    window.copy_band_table()
    text = qapp.clipboard().text()
    assert text.splitlines()[0] == "Signal\tBand RMS\tBand Power"
    assert "sine" in text


def test_spectra_copy_as_tsv(window, qapp):
    window.copy_spectra()
    lines = qapp.clipboard().text().splitlines()
    assert lines[0] == "Frequency (Hz)\tsine"
    assert len(lines) == next(iter(window._spectra.values())).n_samples + 1


# -- cross-window flow -------------------------------------------------------
def test_time_processing_sends_signals_to_a_new_fft_window(manager):
    tdp = TimeProcessingWindow(manager)
    tdp.store.add(make_signal("accel"))
    tdp.store.add(make_signal("mic", f=256.0))

    fft = tdp.open_fft_window()               # no selection -> all visible
    assert isinstance(fft, FFTWindow)
    assert fft.window_name == "FFT 00"
    assert [s.name for s in fft.store] == ["accel", "mic"]
    assert len(fft._spectra) == 2
    # copies, so the two windows are independent
    assert {s.sid for s in fft.store}.isdisjoint({s.sid for s in tdp.store})
    fft.close()
    tdp.close()


def test_time_processing_sends_only_the_selection_when_there_is_one(manager):
    tdp = TimeProcessingWindow(manager)
    tdp.store.add(make_signal("accel"))
    tdp.store.add(make_signal("mic", f=256.0))
    tdp.tree.topLevelItem(1).setSelected(True)

    fft = tdp.open_fft_window()
    assert [s.name for s in fft.store] == ["mic"]
    fft.close()
    tdp.close()


def test_fft_window_imports_from_a_time_window(manager):
    tdp = TimeProcessingWindow(manager)
    tdp.store.add(make_signal("shared"))
    fft = FFTWindow(manager)

    from spwb.gui.dialogs import ImportFromWindowDialog
    dialog = ImportFromWindowDialog(manager.others(fft), fft)
    assert dialog.window_box.count() == 1
    for sig in dialog.selected_signals():
        fft.store.add(sig)

    assert len(fft._spectra) == 1
    assert next(iter(fft._spectra.values())).y[bin_of(fft)] == pytest.approx(
        AMPLITUDE / math.sqrt(2), rel=1e-6)
    fft.close()
    tdp.close()


def test_duplicate_carries_the_settings_over(window, manager):
    window.freq_resolution.setValue(4.0)
    window.window_box.setCurrentText("Flat Top")
    window.function_type.setCurrentText("Power Spectrum - (EU RMS²)")
    clone = window.duplicate_window()
    assert clone.window_name != window.window_name
    assert clone.freq_resolution.value() == pytest.approx(4.0)
    assert clone.window_box.currentText() == "Flat Top"
    assert clone.function_type.currentText() == "Power Spectrum - (EU RMS²)"
    assert [s.name for s in clone.store] == ["sine"]
    clone.close()


def test_deleting_a_signal_drops_its_spectrum(window):
    window.tree.topLevelItem(0).setSelected(True)
    window.delete_selected()
    assert len(window.store) == 0
    assert window._spectra == {}
    assert len(window.plot.plotItem.listDataItems()) == 0
