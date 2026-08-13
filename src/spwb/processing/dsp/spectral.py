"""Spectral analysis - port of SPWB's FFT chain.

Ported from (LabVIEW block diagrams in SPWB_export):
  * ``FFT - computation parameters.vi``  -> :func:`spectral_params`
  * ``FFT - Auto Power Spectrums.vi``    -> :func:`auto_power_spectrums`
  * ``NI Auto Power Spectrum.vi``        -> :func:`auto_power_spectrum`
  * ``FFT - Spectrum Display Options.vi``-> :func:`scale_spectrum`

Conventions (validated against LabVIEW 2022 fixtures):
  * ``auto_power_spectrum`` returns the single-sided spectrum in EU_rms^2
    with N/2 bins (0 Hz .. Fs/2 - df); SPWB then appends a copy of the last
    bin so the displayed spectrum spans 0 Hz .. Fs/2 inclusive.
  * Averaged spectra use amplitude-preserving windows (see windows.py), so
    a full-scale sine reads its A^2/2 power regardless of window.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..model.signal import Signal
from . import windows as _win

__all__ = [
    "ACOUSTIC_WEIGHTINGS",
    "DB_REFERENCES",
    "SPECTRAL_FUNCTION_TYPES",
    "SPECTRUM_DISPLAY_OPTIONS",
    "SpectralParams",
    "a_weighting",
    "apply_weighting",
    "auto_power_spectrum",
    "auto_power_spectrums",
    "band_power",
    "band_rms",
    "format_spectrum",
    "scale_spectrum",
    "spectral_params",
]


# --------------------------------------------------------------------------
# FFT - computation parameters.vi
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class SpectralParams:
    fft_length: int
    freq_resolution: float   # actual df (Hz) after rounding fft_length
    overlap_samples: int
    n_averages: int
    step: int                # fft_length - overlap_samples


def spectral_params(fs: float, n_samples: int, freq_resolution: float,
                    overlap: float = 0.0) -> SpectralParams:
    """Block/averaging bookkeeping for a requested frequency resolution.

    ``overlap`` is a fraction (0 .. <1) of the FFT length, as in SPWB's
    Spectral Function Parameters cluster.
    """
    if freq_resolution <= 0:
        raise ValueError("freq_resolution must be > 0")
    if not 0 <= overlap < 1:
        raise ValueError("overlap must be in [0, 1)")
    fft_length = int(round(fs / freq_resolution))
    fft_length = min(fft_length, n_samples)
    if fft_length < 2:
        raise ValueError("freq_resolution too coarse for the signal length")
    overlap_samples = int(round(fft_length * overlap))
    step = fft_length - overlap_samples
    n_averages = (n_samples - fft_length) // step + 1
    return SpectralParams(
        fft_length=fft_length,
        freq_resolution=fs / fft_length,
        overlap_samples=overlap_samples,
        n_averages=max(1, n_averages),
        step=step,
    )


# --------------------------------------------------------------------------
# NI Auto Power Spectrum.vi
# --------------------------------------------------------------------------
def auto_power_spectrum(x: np.ndarray, dt: float) -> tuple[np.ndarray, float]:
    """Single-sided auto power spectrum in EU_rms^2 (NI convention).

    Returns ``(Sxx, df)`` with ``len(Sxx) == len(x) // 2``:
    ``Sxx[0] = (X[0]/N)^2`` (DC, mean squared) and
    ``Sxx[k] = 2 |X[k]|^2 / N^2`` for k >= 1.
    """
    x = np.asarray(x, dtype=float)
    n = len(x)
    X = np.fft.rfft(x)
    two_sided = (np.abs(X) / n) ** 2
    s = np.empty(n // 2)
    s[0] = two_sided[0]
    s[1:] = 2.0 * two_sided[1:n // 2]
    return s, 1.0 / (n * dt)


# --------------------------------------------------------------------------
# GSwFormDSP FFT - Auto Power Spectrums.vi
# --------------------------------------------------------------------------
def auto_power_spectrums(signal: Signal, freq_resolution: float,
                         overlap: float = 0.0,
                         window: str = "hanning",
                         window_parameter: float = math.nan) -> Signal:
    """Averaged auto power spectrum of one signal, SPWB style.

    Splits the signal into (possibly overlapping) blocks, applies the
    amplitude-preserving window, averages the block spectra, and appends a
    copy of the last bin so the spectrum covers 0 Hz .. Fs/2 inclusive
    (exactly as the LabVIEW diagram does). Processing provenance is stored
    in the returned Signal's attributes.
    """
    p = spectral_params(signal.fs, signal.n_samples, freq_resolution, overlap)
    acc = np.zeros(p.fft_length // 2)
    props = None
    for i in range(p.n_averages):
        block = signal.y[i * p.step: i * p.step + p.fft_length]
        wx, props = _win.scaled_window(block, window, window_parameter)
        s, _ = auto_power_spectrum(wx, signal.dt)
        acc += s
    acc /= p.n_averages
    df = p.freq_resolution
    # SPWB: copy the last value so the spectrum covers 0 Hz .. FFT_Length/2
    s_full = np.append(acc, acc[-1])
    return Signal(
        name=signal.name,
        y=s_full,
        dt=df,
        t0=0.0,
        y_unit=f"{signal.y_unit or 'EU'}²rms",
        x_unit="Hz",
        attributes={
            **signal.attributes,
            "FFT_Function_Type": "Power Spectrum - (EU RMS²)",
            "FFT_Window_Type": window,
            "FFT_Coherent_Gain": props.coherent_gain,
            "FFT_EQ_Noise_BW": props.eq_noise_bw,
            "FFT_Nb_Averages": p.n_averages,
            # the source's engineering unit, so format_spectrum can label
            # and pick automatic dB references without the caller's help
            "Channel Unit": signal.attributes.get("Channel Unit",
                                                  signal.y_unit),
            "X_UnitDescription": "Hz",
        },
    )


# --------------------------------------------------------------------------
# FFT - Spectrum Display Options.vi
# --------------------------------------------------------------------------
#: dB reference values by display option (from the LabVIEW case frames)
DB_REFERENCES: dict[str, float] = {
    "none": 1.0,
    "spl": 20e-6,          # Sound SPL (ref 20 uPa)
    "acceleration": 1e-6,  # ref 1e-6 m/s^2
    "velocity": 1e-9,      # ref 1e-9 m/s
    "displacement": 1e-12, # ref 1e-12 m
}

#: automatic reference lookup by unit (dB - Automatic reference value frame)
_AUTO_REF_BY_UNIT = {
    "pa": 20e-6,
    "m/s^2": 1e-6, "m/s²": 1e-6,
    "m/s": 1e-9,
    "m": 1e-12,
}


def scale_spectrum(s_rms2: np.ndarray, df: float, *,
                   form: str = "power",
                   density: bool = False,
                   eq_noise_bw: float = 1.0,
                   db: bool = False,
                   db_reference: str | float = "none",
                   y_unit: str = "") -> tuple[np.ndarray, str]:
    """Scale an EU_rms^2 auto spectrum for display, SPWB style.

    form:    "power" (EU rms^2), "rms" (EU rms) or "peak" (EU peak)
    density: divide the power spectrum by (ENBW * df) first (PSD)
    db:      convert to dB re ``db_reference`` (name from DB_REFERENCES,
             "auto" to pick by unit, or a numeric reference)

    Returns ``(scaled, unit_suffix)`` where unit_suffix documents the
    scaling the way SPWB's unit-string frames do.
    """
    s = np.asarray(s_rms2, dtype=float)
    suffix = ""
    if density:
        s = s / (eq_noise_bw * df)
        suffix = "/Hz"

    if isinstance(db_reference, str):
        key = db_reference.lower()
        if key == "auto":
            ref = _AUTO_REF_BY_UNIT.get(y_unit.lower(), 1.0)
        else:
            ref = DB_REFERENCES[key]
    else:
        ref = float(db_reference)

    form = form.lower()
    if form == "power":
        if db:
            with np.errstate(divide="ignore"):
                return 10.0 * np.log10(s / ref ** 2), f"dB re {ref:g}"
        return s, f"RMS²{suffix}"
    if form in ("rms", "peak"):
        amp = np.sqrt(s)
        if form == "peak":
            amp = amp * math.sqrt(2.0)
        if db:
            with np.errstate(divide="ignore"):
                return 20.0 * np.log10(amp / ref), f"dB re {ref:g}"
        label = "RMS" if form == "rms" else "Peak"
        return amp, f"{label}{'/√Hz' if density else ''}"
    raise ValueError("form must be 'power', 'rms' or 'peak'")


# --------------------------------------------------------------------------
# SPWB's user-facing enums (strings recovered verbatim from the .ctl files)
# --------------------------------------------------------------------------
#: ``Spectral Function Type.ctl`` - what the spectrum represents
SPECTRAL_FUNCTION_TYPES: tuple[str, ...] = (
    "Auto Spectrum - (EU RMS)",
    "Auto Spectrum - (EU Peak)",
    "Power Spectrum - (EU RMS²)",
    "Power Spectrum - (EU Peak²)",
    "Auto Spectrum Density - (EU RMS/rtHz)",
    "Auto Spectrum Density - (EU Peak/rtHz)",
    "Power Spectrum Density - (EU RMS²/Hz)",
    "Power Spectrum Density - (EU Peak²/Hz)",
)

#: ``Spectrum Display Options.ctl`` - linear or dB re a reference
SPECTRUM_DISPLAY_OPTIONS: tuple[str, ...] = (
    "None",
    "dB - NO reference value",
    "dB - Automatic reference value",
    "dB - Sound SPL (ref 20E-6 Pa)",
    "dB - Acceleration (ref 1E-6 m/s²)",
    "dB - Velocity (ref 1E-9 m/s)",
    "dB - Displacement (ref 1E-12 m)",
)

#: ``Acoustic Weighting.ctl``
ACOUSTIC_WEIGHTINGS: tuple[str, ...] = ("Linear", "A-weighting")

# function type -> (magnitude, squared, density)
_FUNCTION_SPEC: dict[str, tuple[str, bool, bool]] = {
    SPECTRAL_FUNCTION_TYPES[0]: ("rms", False, False),
    SPECTRAL_FUNCTION_TYPES[1]: ("peak", False, False),
    SPECTRAL_FUNCTION_TYPES[2]: ("rms", True, False),
    SPECTRAL_FUNCTION_TYPES[3]: ("peak", True, False),
    SPECTRAL_FUNCTION_TYPES[4]: ("rms", False, True),
    SPECTRAL_FUNCTION_TYPES[5]: ("peak", False, True),
    SPECTRAL_FUNCTION_TYPES[6]: ("rms", True, True),
    SPECTRAL_FUNCTION_TYPES[7]: ("peak", True, True),
}

# display option -> dB reference ("auto" resolves from the signal's unit)
_DISPLAY_REF: dict[str, str | float | None] = {
    SPECTRUM_DISPLAY_OPTIONS[0]: None,      # linear, no dB
    SPECTRUM_DISPLAY_OPTIONS[1]: 1.0,
    SPECTRUM_DISPLAY_OPTIONS[2]: "auto",
    SPECTRUM_DISPLAY_OPTIONS[3]: 20e-6,
    SPECTRUM_DISPLAY_OPTIONS[4]: 1e-6,
    SPECTRUM_DISPLAY_OPTIONS[5]: 1e-9,
    SPECTRUM_DISPLAY_OPTIONS[6]: 1e-12,
}


def a_weighting(freqs: np.ndarray) -> np.ndarray:
    """A-weighting in dB (``A-Weight (given frequency).vi``).

    The IEC 61672 curve as SPWB implements it::

                       12200^2 f^4
        R_A(f) = ------------------------------------------------------
                 (f^2+20.6^2) sqrt((f^2+107.7^2)(f^2+737.9^2)) (f^2+12200^2)

        A(f) = 2.0 + 20 log10(R_A(f))
    """
    f = np.asarray(freqs, dtype=float)
    f2 = f * f
    num = 12200.0 ** 2 * f2 * f2
    den = ((f2 + 20.6 ** 2)
           * np.sqrt((f2 + 107.7 ** 2) * (f2 + 737.9 ** 2))
           * (f2 + 12200.0 ** 2))
    with np.errstate(divide="ignore", invalid="ignore"):
        ra = np.where(den > 0, num / den, 0.0)
        return 2.0 + 20.0 * np.log10(np.where(ra > 0, ra, np.finfo(float).tiny))


def apply_weighting(y: np.ndarray, freqs: np.ndarray, weighting: str, *,
                    domain: str) -> np.ndarray:
    """``Acoustic Weighting.vi``.

    ``domain`` says how the weighting enters: ``"dB"`` adds it directly,
    ``"EU"`` multiplies by ``10^(A/20)`` and ``"EU2"`` by ``10^(A/10)``.
    """
    if weighting in (None, "", "Linear"):
        return y
    if weighting != "A-weighting":
        raise ValueError(f"unknown weighting {weighting!r}; "
                         f"expected one of {ACOUSTIC_WEIGHTINGS}")
    a_db = a_weighting(freqs)
    if domain == "dB":
        return y + a_db
    if domain == "EU":
        return y * 10.0 ** (a_db / 20.0)
    if domain == "EU2":
        return y * 10.0 ** (a_db / 10.0)
    raise ValueError("domain must be 'dB', 'EU' or 'EU2'")


def format_spectrum(spectrum: Signal, *,
                    function_type: str = SPECTRAL_FUNCTION_TYPES[0],
                    display_option: str = SPECTRUM_DISPLAY_OPTIONS[0],
                    weighting: str = "Linear") -> Signal:
    """Present a raw EU_rms² spectrum the way the FFT window displays it.

    Combines ``Spectral Function Type``, ``Spectrum Display Options`` and
    ``Acoustic Weighting`` - i.e. what ``Get FFT - Scaled Spectrums.vi``
    does. ``spectrum`` is the output of :func:`auto_power_spectrums`, whose
    ``FFT_EQ_Noise_BW`` attribute supplies the density normalisation.
    """
    if function_type not in _FUNCTION_SPEC:
        raise ValueError(f"unknown function type {function_type!r}")
    if display_option not in _DISPLAY_REF:
        raise ValueError(f"unknown display option {display_option!r}")

    magnitude, squared, density = _FUNCTION_SPEC[function_type]
    enbw = float(spectrum.attributes.get("FFT_EQ_Noise_BW", 1.0))
    base_unit = spectrum.attributes.get("Channel Unit", "") or ""
    freqs = spectrum.t

    y = np.asarray(spectrum.y, dtype=float)
    if density:
        y = y / (enbw * spectrum.dt)
    if magnitude == "peak":
        y = y * 2.0                     # peak² = 2 · rms²
    if not squared:
        y = np.sqrt(y)

    ref = _DISPLAY_REF[display_option]
    if ref is None:                     # linear display
        y = apply_weighting(y, freqs, weighting,
                            domain="EU2" if squared else "EU")
        unit = _linear_unit(base_unit, magnitude, squared, density)
    else:
        if ref == "auto":
            ref = _AUTO_REF_BY_UNIT.get(base_unit.lower(), 1.0)
        ref = float(ref)
        factor = 10.0 if squared else 20.0
        denom = ref ** 2 if squared else ref
        y = factor * np.log10(_floor_for_db(y, factor) / denom)
        y = apply_weighting(y, freqs, weighting, domain="dB")
        unit = _db_unit(display_option, ref, base_unit)
    if weighting == "A-weighting":
        unit = f"{unit} [A-Weighted]"

    return spectrum.with_(
        y=y, y_unit=unit,
        attributes={
            "FFT_Function_Type": function_type,
            "FFT_Display_Option": display_option,
            "FFT_Acoustic_Weighting": weighting,
        },
    )


#: dB floor applied before a log: values this far below the spectrum's own
#: peak are clamped. Far beyond any instrument's dynamic range, but finite -
#: flooring at machine epsilon instead yields ~-6000 dB outliers that make
#: an autoscaled plot useless.
DB_DYNAMIC_RANGE = 400.0


def _floor_for_db(y: np.ndarray, factor: float) -> np.ndarray:
    """Clamp non-positive bins to ``DB_DYNAMIC_RANGE`` below the peak."""
    positive = y[y > 0]
    if positive.size == 0:
        return np.full_like(y, np.finfo(float).tiny)
    floor = positive.max() * 10.0 ** (-DB_DYNAMIC_RANGE / factor)
    return np.maximum(y, max(floor, np.finfo(float).tiny))


def band_power(spectrum: Signal, start: float, end: float) -> float:
    """Total power in ``[start, end]`` Hz of a raw EU_rms² spectrum.

    The Energy Band tab of the FFT window. ``spectrum`` must be the output
    of :func:`auto_power_spectrums` (not a formatted one), because the
    normalisation uses its ``FFT_EQ_Noise_BW`` attribute.

    An amplitude-preserving window spreads each tone over roughly ENBW
    bins, so a bare sum overstates the power by that factor - NI's own note
    on *eq noise BW* is to divide a sum of power spectra by it. Dividing
    here makes ``sqrt(band_power)`` the true RMS of the band's content.
    """
    if end < start:
        start, end = end, start
    freqs = spectrum.t
    mask = (freqs >= start) & (freqs <= end)
    enbw = float(spectrum.attributes.get("FFT_EQ_Noise_BW", 1.0))
    return float(np.asarray(spectrum.y)[mask].sum()) / enbw


def band_rms(spectrum: Signal, start: float, end: float) -> float:
    """RMS of the content in ``[start, end]`` Hz - ``sqrt(band_power)``."""
    return math.sqrt(max(band_power(spectrum, start, end), 0.0))


def _db_unit(display_option: str, ref: float, base_unit: str) -> str:
    """``dB re 20E-6 Pa`` - reuse the reference text from the option name."""
    if ref == 1.0:
        return "dB"
    start = display_option.find("(ref ")
    if start >= 0:
        end = display_option.find(")", start)
        return f"dB {display_option[start + 1:end]}"
    return f"dB re {ref:g} {base_unit}".strip()


def _linear_unit(base: str, magnitude: str, squared: bool,
                 density: bool) -> str:
    eu = base or "EU"
    label = "RMS" if magnitude == "rms" else "Peak"
    if squared:
        return f"{eu}² {label}²/Hz" if density else f"{eu}² {label}²"
    return f"{eu} {label}/√Hz" if density else f"{eu} {label}"
