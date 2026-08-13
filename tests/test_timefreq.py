"""STFT spectrogram vs LabVIEW 2022 + analytical checks."""
import pathlib

import numpy as np
import pytest

from spwb import Signal
from spwb.processing.dsp import timefreq as TF

FS = 1024.0
N = 4096
BLOCK = 256
HOP = 128


@pytest.fixture(scope="session")
def lvstft():
    path = (pathlib.Path(__file__).parent / "fixtures"
            / "labview_stft_reference.npz")
    return np.load(path)


def sig_from(y, name="s", unit=""):
    return Signal(name, y, 1.0 / FS, y_unit=unit)


# -- against LabVIEW ---------------------------------------------------------
@pytest.mark.parametrize("case", ["tone", "chirp", "mixed"])
def test_spectrogram_matches_labview(lvstft, case):
    out = TF.stft_spectrogram(sig_from(lvstft[f"sig_{case}"]),
                              block_size=BLOCK, hop=HOP, window="hanning")
    reference = lvstft[f"spec_{case}"]
    assert out.shape == reference.shape
    np.testing.assert_allclose(out.data, reference, rtol=1e-9, atol=1e-15)


@pytest.mark.parametrize("window", list(TF.TFA_WINDOW_RING.values()))
def test_every_ring_window_matches_labview(lvstft, window):
    """The NI TFA window ring maps onto spwb's window names."""
    out = TF.stft_spectrogram(sig_from(lvstft["sig_tone"]),
                              block_size=BLOCK, hop=HOP, window=window)
    np.testing.assert_allclose(out.data, lvstft[f"win_{window}"],
                               rtol=1e-9, atol=1e-15)


def test_shape_rule_matches_ni(lvstft):
    """rows = len(x)//hop + 1 (hop, not a frame count); cols = nfft//2."""
    out = TF.stft_spectrogram(sig_from(lvstft["sig_tone"]),
                              block_size=BLOCK, hop=HOP)
    assert out.n_frames == N // HOP + 1
    assert out.n_bins == BLOCK // 2


# -- analytical --------------------------------------------------------------
def test_rectangular_window_puts_a_sine_at_amplitude_squared_over_four():
    t = np.arange(N) / FS
    out = TF.stft_spectrogram(sig_from(3.0 * np.sin(2 * np.pi * 128 * t)),
                              block_size=BLOCK, hop=HOP, window="rectangular")
    assert out.data.max() == pytest.approx(3.0 ** 2 / 4, rel=1e-9)


def test_dc_through_a_rectangular_window_reads_its_square():
    out = TF.stft_spectrogram(sig_from(np.full(N, 2.0)),
                              block_size=BLOCK, hop=HOP, window="rectangular")
    interior = out.data[2:-2]                 # skip the padded edges
    assert interior[:, 0].max() == pytest.approx(4.0, rel=1e-9)


def test_stationary_tone_is_stationary():
    t = np.arange(N) / FS
    out = TF.stft_spectrogram(sig_from(np.sin(2 * np.pi * 128 * t)),
                              block_size=BLOCK, hop=HOP)
    peak_bins = out.data[2:-2].argmax(axis=1)
    assert len(set(peak_bins.tolist())) == 1          # same bin every frame
    assert out.freqs[peak_bins[0]] == pytest.approx(128.0, abs=out.df)


def test_chirp_ridge_climbs_monotonically():
    t = np.arange(N) / FS
    duration = t[-1]
    y = np.sin(2 * np.pi * (50.0 * t + (350.0 / (2 * duration)) * t ** 2))
    out = TF.stft_spectrogram(sig_from(y), block_size=BLOCK, hop=HOP)
    ridge = out.freqs[out.data[3:-3].argmax(axis=1)]
    assert np.all(np.diff(ridge) >= -out.df)          # never goes backwards
    assert ridge[0] < 120 and ridge[-1] > 300


def test_frame_centres_line_up_with_a_burst():
    """A burst in the middle must light up the middle frames, not the edges."""
    y = np.zeros(N)
    y[N // 2 - 200: N // 2 + 200] = np.sin(
        2 * np.pi * 200 * np.arange(400) / FS)
    out = TF.stft_spectrogram(sig_from(y), block_size=BLOCK, hop=HOP)
    energy = out.data.sum(axis=1)
    assert out.times[int(np.argmax(energy))] == pytest.approx(
        (N // 2) / FS, abs=BLOCK / FS)


def test_time_and_frequency_axes():
    t = np.arange(N) / FS
    out = TF.stft_spectrogram(sig_from(np.sin(2 * np.pi * 128 * t)),
                              block_size=BLOCK, hop=HOP)
    assert out.freqs[0] == 0.0
    assert out.df == pytest.approx(FS / BLOCK)
    assert out.freqs[-1] == pytest.approx(FS / 2 - out.df)
    assert out.times[0] == 0.0
    assert out.dt == pytest.approx(HOP / FS)


def test_t0_offsets_the_time_axis():
    s = Signal("s", np.zeros(N), 1 / FS, t0=5.0)
    out = TF.stft_spectrogram(s, block_size=BLOCK, hop=HOP)
    assert out.times[0] == pytest.approx(5.0)


def test_normalize_scales_to_unit_peak():
    t = np.arange(N) / FS
    y = 7.0 * np.sin(2 * np.pi * 128 * t)
    plain = TF.stft_spectrogram(sig_from(y), block_size=BLOCK, hop=HOP)
    normed = TF.stft_spectrogram(sig_from(y), block_size=BLOCK, hop=HOP,
                                 normalize=True)
    assert normed.data.max() == pytest.approx(plain.data.max() / 49.0, rel=1e-9)
    assert normed.attributes["TFA_Normalized"] is True


# -- cross sections ----------------------------------------------------------
@pytest.fixture
def spec():
    t = np.arange(N) / FS
    y = np.sin(2 * np.pi * 100 * t) + 0.5 * np.sin(2 * np.pi * 300 * t)
    return TF.stft_spectrogram(sig_from(y, "mix", "Pa"),
                               block_size=BLOCK, hop=HOP)


def test_time_section_is_a_spectrum(spec):
    section = spec.time_section(2.0)
    assert section.n_samples == spec.n_bins
    assert section.x_unit == "Hz"
    assert section.dt == pytest.approx(spec.df)
    peak = section.t[int(np.argmax(section.y))]
    assert peak == pytest.approx(100.0, abs=spec.df)


def test_frequency_section_is_a_time_history(spec):
    section = spec.frequency_section(300.0)
    assert section.n_samples == spec.n_frames
    assert section.x_unit == "sec"
    assert section.dt == pytest.approx(spec.dt)
    assert section.attributes["TFA_Frequency"] == pytest.approx(300.0,
                                                                abs=spec.df)


def test_sections_snap_to_the_nearest_available_point(spec):
    assert spec.frequency_section(1e9).attributes["TFA_Frequency"] == \
        pytest.approx(spec.freqs[-1])
    assert spec.time_section(-5.0).attributes["TFA_Time"] == \
        pytest.approx(spec.times[0])


def test_sections_are_copies_not_views(spec):
    section = spec.time_section(1.0)
    section.y[:] = 0.0
    assert spec.data.max() > 0.0


# -- dB conversion -----------------------------------------------------------
def test_to_db_is_relative_to_the_peak_by_default(spec):
    db = spec.to_db()
    assert db.y_unit == "dB"
    assert db.data.max() == pytest.approx(0.0, abs=1e-12)
    assert np.isfinite(db.data).all()


def test_to_db_floors_at_the_dynamic_range(spec):
    db = spec.to_db(dynamic_range=60.0)
    assert db.data.min() >= -60.0 - 1e-9


def test_to_db_of_zeros_stays_finite():
    zeros = TF.Spectrogram(data=np.zeros((4, 8)), times=np.arange(4),
                           freqs=np.arange(8))
    assert np.isfinite(zeros.to_db().data).all()


def test_to_db_with_an_explicit_reference(spec):
    db = spec.to_db(reference=1.0)
    assert db.data.max() == pytest.approx(10 * np.log10(spec.data.max()))


def test_db_preserves_axes(spec):
    db = spec.to_db()
    np.testing.assert_array_equal(db.times, spec.times)
    np.testing.assert_array_equal(db.freqs, spec.freqs)


# -- validation --------------------------------------------------------------
@pytest.mark.parametrize("block, message", [
    (0, "even"), (3, "even"), (1, "even"), (N * 2, "exceeds"),
])
def test_invalid_block_size_rejected(block, message):
    with pytest.raises(ValueError, match=message):
        TF.stft_spectrogram(sig_from(np.zeros(N)), block_size=block)


def test_invalid_hop_rejected():
    with pytest.raises(ValueError, match="hop"):
        TF.stft_spectrogram(sig_from(np.zeros(N)), block_size=BLOCK, hop=0)


def test_default_hop_is_quarter_block():
    out = TF.stft_spectrogram(sig_from(np.zeros(N)), block_size=BLOCK)
    assert out.attributes["TFA_Hop"] == BLOCK // 4


def test_attributes_carry_provenance():
    s = sig_from(np.zeros(N), "x", "Pa")
    s.attributes["Data Source"] = "run.tdms"
    out = TF.stft_spectrogram(s, block_size=BLOCK, window="flat_top")
    assert out.attributes["Data Source"] == "run.tdms"
    assert out.attributes["TFA_Window_Type"] == "flat_top"
    assert out.attributes["TFA_Block_Size"] == BLOCK
    assert out.y_unit == "Pa²"
