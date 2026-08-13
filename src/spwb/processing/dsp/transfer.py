"""Transfer functions and coherence - port of SPWB's TF chain.

Ported from (LabVIEW block diagrams in SPWB_export):
  * ``TFSA - TF and Coherence V2.vi``          -> :func:`transfer_function`
  * ``TF - Transfer Function and Coherence.vi`` -> :func:`transfer_functions`
  * ``Transfer Function Type.ctl``              -> :data:`TF_DISPLAY_TYPES`

The block diagram carries two warnings from the original author that this
module honours:

    "MUST perform the averages first, before computing the transfer function"
    "The average has to be done on the complex numbers"

Averaging the per-block ``H`` values (or averaging magnitudes) is a
different - and wrong - estimator: it destroys the noise rejection that
makes H1 useful and makes coherence come out as 1 everywhere. So Sxy, Sxx
and Syy are accumulated over the blocks and only then combined.

Conventions (verified against LabVIEW 2022 in ``tests/test_transfer.py``):

* ``Sxy = 2·conj(X)·Y / N²`` with the DC and Nyquist bins left unscaled,
  matching ``NI_AALPro Cross Power Spectrum.vi``;
* ``x`` is the **reference** (input) and ``y`` the **response** (output),
  as SPWB's ``Reference Indexes`` / ``Response Indexes`` inputs imply;
* spectra are truncated to ``N/2`` bins so the cross spectrum lines up with
  ``Auto Power Spectrum.vi`` (NI's own two VIs disagree by one bin), then
  the last bin is duplicated for display exactly as the FFT path does.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ...processing.model.signal import Signal
from . import windows as _win
from .spectral import spectral_params

__all__ = [
    "TF_DISPLAY_TYPES",
    "TF_ESTIMATORS",
    "CrossSpectra",
    "cross_power_spectrum",
    "cross_spectra",
    "format_transfer_function",
    "transfer_function",
    "transfer_functions",
]

#: ``Transfer Function Type.ctl`` - how the FFT/TF window displays a TF
TF_DISPLAY_TYPES: tuple[str, ...] = (
    "Magnitude",
    "Phase (Rad)",
    "Phase Unwrap (Rad)",
    "Phase (Degree)",
    "Phase Unwrap (Degree)",
    "Coherence",
)

#: Estimators. SPWB computed H1 only; H2/H3 are added here because they fall
#: out of the same averaged spectra and answer different noise questions.
TF_ESTIMATORS: tuple[str, ...] = ("H1", "H2", "H3")


def cross_power_spectrum(x: np.ndarray, y: np.ndarray,
                         dt: float) -> tuple[np.ndarray, float]:
    """Single-sided cross power spectrum ``Sxy`` (NI convention).

    Returns ``(Sxy, df)`` as a complex array of ``len(x)//2 + 1`` bins:
    ``conj(X)·Y/N²`` with bins 1..N/2-1 doubled, exactly as
    ``NI_AALPro Cross Power Spectrum.vi`` returns magnitude and phase.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if len(x) != len(y):
        raise ValueError(f"signals must be the same length, got {len(x)} and {len(y)}")
    n = len(x)
    s = np.conj(np.fft.rfft(x)) * np.fft.rfft(y) / (n * n)
    s[1:-1] *= 2.0                     # DC and Nyquist have no mirror bin
    return s, 1.0 / (n * dt)


@dataclass(frozen=True)
class CrossSpectra:
    """Block-averaged spectra - the raw material for every estimator."""
    sxy: np.ndarray      # complex cross spectrum (reference -> response)
    sxx: np.ndarray      # auto spectrum of the reference
    syy: np.ndarray      # auto spectrum of the response
    df: float
    n_averages: int
    eq_noise_bw: float
    coherent_gain: float

    @property
    def coherence(self) -> np.ndarray:
        """Ordinary coherence ``|Sxy|² / (Sxx·Syy)``, clipped to [0, 1]."""
        denominator = self.sxx * self.syy
        with np.errstate(divide="ignore", invalid="ignore"):
            gamma2 = np.where(denominator > 0,
                              np.abs(self.sxy) ** 2 / denominator, 0.0)
        return np.clip(gamma2, 0.0, 1.0)

    def estimator(self, name: str = "H1") -> np.ndarray:
        """Complex frequency response by the named estimator.

        ``H1 = Sxy/Sxx``   - unbiased when the noise is on the response;
        ``H2 = Syy/Syx``   - unbiased when the noise is on the reference;
        ``H3``             - the geometric mean of the two.
        """
        with np.errstate(divide="ignore", invalid="ignore"):
            if name == "H1":
                h = np.where(self.sxx > 0, self.sxy / self.sxx, 0.0)
            elif name == "H2":
                syx = np.conj(self.sxy)
                h = np.where(np.abs(syx) > 0, self.syy / syx, 0.0)
            elif name == "H3":
                h1 = self.estimator("H1")
                h2 = self.estimator("H2")
                # geometric mean keeping H1's phase (H1 and H2 share it)
                h = np.sqrt(np.abs(h1) * np.abs(h2)) * np.exp(1j * np.angle(h1))
            else:
                raise ValueError(f"unknown estimator {name!r}; "
                                 f"expected one of {TF_ESTIMATORS}")
        return np.nan_to_num(h, nan=0.0, posinf=0.0, neginf=0.0)


def cross_spectra(reference: Signal, response: Signal, *,
                  freq_resolution: float, overlap: float = 0.0,
                  window: str = "bh_7term",
                  window_parameter: float = math.nan) -> CrossSpectra:
    """Block-average Sxy, Sxx and Syy over a pair of signals.

    The default window is SPWB's: ``7 Term B-Harris``.
    """
    if reference.n_samples != response.n_samples:
        raise ValueError(
            f"reference and response must be the same length, got "
            f"{reference.n_samples} and {response.n_samples} samples")
    if not math.isclose(reference.dt, response.dt, rel_tol=1e-12):
        raise ValueError(
            f"reference and response must share a sample rate, got "
            f"{reference.fs:g} Hz and {response.fs:g} Hz")

    p = spectral_params(reference.fs, reference.n_samples, freq_resolution,
                        overlap)
    bins = p.fft_length // 2          # match Auto Power Spectrum.vi
    sxy = np.zeros(bins, dtype=complex)
    sxx = np.zeros(bins)
    syy = np.zeros(bins)
    props = None

    for i in range(p.n_averages):
        sl = slice(i * p.step, i * p.step + p.fft_length)
        wx, props = _win.scaled_window(reference.y[sl], window, window_parameter)
        wy, _ = _win.scaled_window(response.y[sl], window, window_parameter)
        cross, _ = cross_power_spectrum(wx, wy, reference.dt)
        # accumulate the COMPLEX cross spectrum, not its magnitude
        sxy += cross[:bins]
        X = np.fft.rfft(wx)
        Y = np.fft.rfft(wy)
        n = p.fft_length
        auto_x = (np.abs(X) / n) ** 2
        auto_y = (np.abs(Y) / n) ** 2
        auto_x[1:] *= 2.0
        auto_y[1:] *= 2.0
        sxx += auto_x[:bins]
        syy += auto_y[:bins]

    return CrossSpectra(
        sxy=sxy / p.n_averages,
        sxx=sxx / p.n_averages,
        syy=syy / p.n_averages,
        df=p.freq_resolution,
        n_averages=p.n_averages,
        eq_noise_bw=props.eq_noise_bw,
        coherent_gain=props.coherent_gain,
    )


def transfer_function(reference: Signal, response: Signal, *,
                      freq_resolution: float, overlap: float = 0.0,
                      window: str = "bh_7term",
                      window_parameter: float = math.nan,
                      estimator: str = "H1") -> tuple[Signal, Signal]:
    """Frequency response and coherence between one reference and response.

    Returns ``(tf, coherence)``. The ``tf`` Signal carries the **complex**
    frequency response in ``attributes["TF_Complex"]``; its ``y`` holds the
    magnitude, so it plots sensibly untouched. Use
    :func:`format_transfer_function` to switch display type.
    """
    spectra = cross_spectra(reference, response,
                            freq_resolution=freq_resolution, overlap=overlap,
                            window=window, window_parameter=window_parameter)
    h = spectra.estimator(estimator)
    gamma2 = spectra.coherence

    # duplicate the last bin so the display spans 0 Hz .. Fs/2, as SPWB does
    h = np.append(h, h[-1])
    gamma2 = np.append(gamma2, gamma2[-1])

    unit_out = response.y_unit or "EU"
    unit_in = reference.y_unit or "EU"
    tf_unit = unit_out if unit_in == unit_out else f"{unit_out}/{unit_in}"
    name = f"{response.name} / {reference.name}"
    common = {
        "FFT_Window_Type": window,
        "FFT_Coherent_Gain": spectra.coherent_gain,
        "FFT_EQ_Noise_BW": spectra.eq_noise_bw,
        "FFT_Nb_Averages": spectra.n_averages,
        "TF_Estimator": estimator,
        "TF_Reference": reference.name,
        "TF_Response": response.name,
        "X_UnitDescription": "Hz",
    }

    tf = Signal(name=name, y=np.abs(h), dt=spectra.df, t0=0.0,
                y_unit=tf_unit, x_unit="Hz",
                attributes={**common, "TF_Complex": h,
                            "FFT_Function_Type": "Transfer Function",
                            "Channel Unit": tf_unit})
    coherence = Signal(name=f"Coherence ({name})", y=gamma2, dt=spectra.df,
                       t0=0.0, y_unit="", x_unit="Hz",
                       attributes={**common,
                                   "FFT_Function_Type": "Coherence",
                                   "Channel Unit": ""})
    return tf, coherence


def transfer_functions(references: list[Signal], responses: list[Signal],
                       **kwargs) -> list[tuple[Signal, Signal]]:
    """Every response/reference combination (SPWB's nested loops).

    Returns ``[(tf, coherence), ...]`` ordered reference-major, matching
    ``TFSA - TF and Coherence V2.vi``'s "Loop for each references" outside
    "Loop for each responses".
    """
    out = []
    for reference in references:
        for response in responses:
            out.append(transfer_function(reference, response, **kwargs))
    return out


def format_transfer_function(tf: Signal, display_type: str,
                             coherence: Signal | None = None) -> Signal:
    """Present a transfer function as ``Transfer Function Type.ctl`` does."""
    if display_type not in TF_DISPLAY_TYPES:
        raise ValueError(f"unknown transfer function type {display_type!r}; "
                         f"expected one of {TF_DISPLAY_TYPES}")
    if display_type == "Coherence":
        if coherence is None:
            raise ValueError("coherence display needs the coherence Signal")
        return coherence

    h = tf.attributes.get("TF_Complex")
    if h is None:
        raise ValueError("signal carries no TF_Complex attribute; "
                         "it is not a transfer function")
    h = np.asarray(h)

    if display_type == "Magnitude":
        return tf.with_(y=np.abs(h))

    phase = np.angle(h)
    if "Unwrap" in display_type:
        phase = np.unwrap(phase)
    if "Degree" in display_type:
        phase = np.degrees(phase)
        unit = "deg"
    else:
        unit = "rad"
    return tf.with_(y=phase, y_unit=unit,
                    attributes={"TF_Display_Type": display_type})
