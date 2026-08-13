"""WAV file IO - port of SPWB's WaveFile_class.

Ported from (LabVIEW block diagrams in SPWB_export/vis/File IO/WaveFile_class):
  * ``READ - Wave File.vi``               -> :func:`read_wave`
  * ``READ - Multiple Wave Files.vi``     -> :func:`read_waves`
  * ``WRITE - Wave File.vi`` +
    ``Scale wForms for wave file.vi``     -> :func:`write_wave`
  * ``Find scale factor from file name.vi`` -> :func:`parse_scale_from_filename`
  * ``Multi Signals Save Option.ctl``     -> :data:`SAVE_OPTIONS`

**The scale-factor-in-the-filename convention.** A WAV file carries no
units and no calibration, and its samples are bounded to +-1 full scale.
SPWB works around this by normalising on write and recording the factor it
applied in the *file name*::

    Accel X_scale_9.81_m-per-s2.wav
            ^^^^^ ^^^^  ^^^^^^^^^^
            keyword     unit (optional, after the number)
                  factor

Reading multiplies the +-1 samples back by that factor, so a round trip
through WAV preserves engineering units. Files without the keyword read
back as raw +-1 data, which is what a WAV from any other tool means.

The filename is split on underscores and matched case-insensitively, as
``Find scale factor from file name.vi`` does.
"""
from __future__ import annotations

import os
from collections.abc import Iterable, Sequence
from pathlib import Path

import numpy as np

from ..model.signal import Signal

__all__ = [
    "SAVE_OPTIONS",
    "SCALE_KEYWORD",
    "SUBTYPES",
    "WaveInfo",
    "parse_scale_from_filename",
    "read_wave",
    "read_waves",
    "scale_filename",
    "wave_contents",
    "write_wave",
]

#: the keyword the scale factor follows in a file name
SCALE_KEYWORD = "scale"

#: ``Multi Signals Save Option.ctl``
SAVE_OPTIONS: tuple[str, ...] = (
    "One wave file per signal",
    "Concatenate ALL signals to a single file",
    "Stereo (Ch1 is Left, Ch2 is Right)",
    "Stereo (Ch1 is Right, Ch2 is Left)",
)

#: sample formats we can write, with their full-scale divisor
SUBTYPES: dict[str, type] = {
    "uint8": np.uint8,
    "int16": np.int16,
    "int32": np.int32,
    "float32": np.float32,
}

# full-scale magnitude per integer dtype, for normalising to +-1
_FULL_SCALE = {
    np.dtype("uint8"): 128.0,
    np.dtype("int16"): 32768.0,
    np.dtype("int32"): 2147483648.0,
}

# characters that cannot appear in a file name but do appear in units
_UNIT_TO_FILENAME = str.maketrans({"/": "-per-", "\\": "-", "^": "", "*": "-"})


class WaveInfo:
    """What a WAV file contains, without committing to import it."""

    __slots__ = (
        "dtype",
        "fs",
        "n_channels",
        "n_samples",
        "path",
        "scale",
        "unit",
    )

    def __init__(self, path: Path, fs: float, n_samples: int, n_channels: int,
                 dtype: str, scale: float | None, unit: str) -> None:
        self.path = path
        self.fs = fs
        self.n_samples = n_samples
        self.n_channels = n_channels
        self.dtype = dtype
        self.scale = scale
        self.unit = unit

    @property
    def duration(self) -> float:
        return self.n_samples / self.fs

    def __repr__(self) -> str:
        return (f"WaveInfo({self.path.name!r}, {self.n_channels}ch, "
                f"{self.fs:g} Hz, {self.duration:.4g} s, scale={self.scale!r})")


# --------------------------------------------------------------------------
# the filename scale convention
# --------------------------------------------------------------------------
def parse_scale_from_filename(filename: str | os.PathLike
                              ) -> tuple[float | None, str]:
    """Recover ``(scale, unit)`` from a name like ``x_scale_9.81_m-per-s2.wav``.

    Returns ``(None, "")`` when the file name carries no ``scale`` keyword,
    or when the token after it is not a number.
    """
    stem = Path(filename).stem
    tokens = stem.split("_")
    lowered = [t.lower() for t in tokens]
    if SCALE_KEYWORD not in lowered:
        return None, ""
    index = lowered.index(SCALE_KEYWORD)
    if index + 1 >= len(tokens):
        return None, ""
    try:
        scale = float(tokens[index + 1])
    except ValueError:
        return None, ""             # keyword present but no number after it
    unit = tokens[index + 2] if index + 2 < len(tokens) else ""
    return scale, _unit_from_filename(unit)


def scale_filename(stem: str, scale: float, unit: str = "") -> str:
    """Build the ``<stem>_scale_<factor>[_<unit>]`` stem used on write.

    The factor is written with 2 decimals, as
    ``Scale wForms for wave file.vi`` formats it.
    """
    parts = [stem, SCALE_KEYWORD, f"{scale:.2f}"]
    if unit:
        parts.append(unit.translate(_UNIT_TO_FILENAME))
    return "_".join(parts)


def _unit_from_filename(token: str) -> str:
    return token.replace("-per-", "/")


# --------------------------------------------------------------------------
# reading
# --------------------------------------------------------------------------
def _read_raw(path: str | os.PathLike) -> tuple[int, np.ndarray]:
    from scipy.io import wavfile
    fs, data = wavfile.read(str(path))
    if data.ndim == 1:
        data = data[:, None]
    return int(fs), data


def _to_unit_range(data: np.ndarray) -> np.ndarray:
    """Normalise integer samples to +-1, as LabVIEW's Sound File Read does."""
    if data.dtype in _FULL_SCALE:
        scale = _FULL_SCALE[data.dtype]
        out = data.astype(float)
        if data.dtype == np.dtype("uint8"):
            out -= 128.0            # unsigned 8-bit is centred on 128
        return out / scale
    return data.astype(float)       # float32/64 files are already +-1


def wave_contents(path: str | os.PathLike) -> WaveInfo:
    """Inspect a WAV file (channel count, rate, and any encoded scale)."""
    path = Path(path)
    fs, data = _read_raw(path)
    scale, unit = parse_scale_from_filename(path)
    return WaveInfo(path=path, fs=float(fs), n_samples=data.shape[0],
                    n_channels=data.shape[1], dtype=str(data.dtype),
                    scale=scale, unit=unit)


def read_wave(path: str | os.PathLike, *,
              scale: float | None = None,
              unit: str | None = None,
              channel_offset: int = 0,
              decorate_names: bool = False) -> list[Signal]:
    """Read a WAV file into one :class:`Signal` per channel.

    Parameters
    ----------
    scale:
        Override the factor encoded in the file name. ``None`` uses the
        encoded one, or 1.0 when there is none.
    unit:
        Override the unit from the file name.
    channel_offset:
        Added to the channel numbers used in signal names, so several files
        can be imported into one window without name collisions
        (SPWB's ``Channel Offset (0 => ignore)`` input).
    decorate_names:
        Append the source file name to each signal name.

    A mono file is named after the file itself; a multichannel file names
    its channels ``<stem> Ch1``, ``<stem> Ch2``, ...
    """
    path = Path(path).resolve()
    fs, raw = _read_raw(path)
    data = _to_unit_range(raw)

    file_scale, file_unit = parse_scale_from_filename(path)
    factor = float(scale) if scale is not None else (
        file_scale if file_scale is not None else 1.0)
    y_unit = unit if unit is not None else file_unit

    # the stem without the scale decoration is the signal's base name
    stem = path.stem
    if file_scale is not None:
        tokens = stem.split("_")
        lowered = [t.lower() for t in tokens]
        stem = "_".join(tokens[:lowered.index(SCALE_KEYWORD)]) or path.stem

    n_channels = data.shape[1]
    signals: list[Signal] = []
    for channel in range(n_channels):
        if n_channels == 1 and channel_offset == 0:
            name = stem
        else:
            name = f"{stem} Ch{channel + 1 + channel_offset}"
        sig = Signal(
            name=name,
            y=data[:, channel] * factor,
            dt=1.0 / fs,
            t0=0.0,
            y_unit=y_unit,
            x_unit="sec",                # SPWB writes "sec" on the wave path
            attributes={
                "Channel Name": name,
                "Channel Unit": y_unit,
                "X Axis Unit": "sec",
                "Data Source": str(path),
                "WAV Scale Factor": factor,
                "WAV Sample Format": str(raw.dtype),
                "WAV Channel": channel + 1,
            },
        )
        if decorate_names:
            from .tdms import append_source_to_name
            sig = append_source_to_name(sig)
        signals.append(sig)
    return signals


def read_waves(paths: Sequence[str | os.PathLike], **kwargs) -> list[Signal]:
    """``READ - Multiple Wave Files.vi``: import several files at once.

    Channel numbering continues across files, so names stay unique.
    """
    out: list[Signal] = []
    offset = kwargs.pop("channel_offset", 0)
    for path in paths:
        signals = read_wave(path, channel_offset=offset, **kwargs)
        out.extend(signals)
        offset += len(signals)
    return out


# --------------------------------------------------------------------------
# writing
# --------------------------------------------------------------------------
def write_wave(path: str | os.PathLike, signals: Iterable[Signal], *,
               desired_level: float = 1.0,
               save_option: str = SAVE_OPTIONS[0],
               subtype: str = "int16",
               encode_scale: bool = True) -> list[Path]:
    """Write signals to WAV, normalising to +-1 and recording the factor.

    ``desired_level`` is the peak the loudest signal is scaled to (<= 1.0),
    matching ``Scale wForms for wave file.vi``'s "Desired Level (EU)" and
    its check that the result cannot exceed full scale.

    Returns the list of files written (more than one for
    "One wave file per signal").
    """
    from scipy.io import wavfile

    signals = list(signals)
    if not signals:
        raise ValueError("no signals to write")
    if save_option not in SAVE_OPTIONS:
        raise ValueError(f"unknown save option {save_option!r}; "
                         f"expected one of {SAVE_OPTIONS}")
    if subtype not in SUBTYPES:
        raise ValueError(f"unknown sample format {subtype!r}; "
                         f"expected one of {tuple(SUBTYPES)}")
    if not 0 < desired_level <= 1.0:
        raise ValueError("desired_level must be in (0, 1]")

    rates = {round(s.fs, 6) for s in signals}
    if len(rates) > 1:
        raise ValueError(
            f"a WAV file holds one sample rate; got {sorted(rates)} Hz. "
            f"Resample first, or save the signals separately.")
    fs = int(round(signals[0].fs))
    path = Path(path)

    stereo = save_option.startswith("Stereo")
    if stereo and len(signals) != 2:
        raise ValueError(f"{save_option!r} needs exactly 2 signals, "
                         f"got {len(signals)}")

    written: list[Path] = []
    if save_option == SAVE_OPTIONS[0]:                    # one file per signal
        for sig in signals:
            factor = _factor_for([sig], desired_level)
            written.append(_write_one(
                wavfile, _decorated(path, sig.name, factor, sig.y_unit,
                                    encode_scale, len(signals) > 1),
                fs, (sig.y * factor)[:, None], subtype))
        return written

    if save_option == SAVE_OPTIONS[1]:                    # concatenate in time
        factor = _factor_for(signals, desired_level)
        data = np.concatenate([s.y for s in signals]) * factor
        unit = signals[0].y_unit
        written.append(_write_one(
            wavfile, _decorated(path, None, factor, unit, encode_scale, False),
            fs, data[:, None], subtype))
        return written

    # stereo: both channels share one factor so their relative level is kept
    left, right = signals if save_option == SAVE_OPTIONS[2] else signals[::-1]
    if left.n_samples != right.n_samples:
        raise ValueError(
            f"stereo needs equal-length signals, got {left.n_samples} "
            f"and {right.n_samples} samples")
    factor = _factor_for(signals, desired_level)
    data = np.column_stack([left.y, right.y]) * factor
    written.append(_write_one(
        wavfile, _decorated(path, None, factor, left.y_unit, encode_scale,
                            False),
        fs, data, subtype))
    return written


def _factor_for(signals: Sequence[Signal], desired_level: float) -> float:
    """Scale so the loudest sample lands on ``desired_level``."""
    peak = max((float(np.max(np.abs(s.y))) for s in signals), default=0.0)
    if peak == 0.0:
        return 1.0
    return desired_level / peak


def _decorated(path: Path, signal_name: str | None, factor: float, unit: str,
               encode_scale: bool, per_signal: bool) -> Path:
    """Build the output path, encoding the inverse factor for the reader.

    The file holds ``y * factor``; a reader must multiply by ``1/factor`` to
    get back to engineering units, so that is what goes in the name.
    """
    stem = path.stem
    if per_signal and signal_name:
        stem = f"{stem}_{signal_name}" if stem else signal_name
    if encode_scale and factor != 0.0:
        stem = scale_filename(stem, 1.0 / factor, unit)
    return path.with_name(f"{stem}{path.suffix or '.wav'}")


def _write_one(wavfile, path: Path, fs: int, data: np.ndarray,
               subtype: str) -> Path:
    dtype = SUBTYPES[subtype]
    clipped = np.clip(data, -1.0, 1.0)
    if subtype == "float32":
        out = clipped.astype(np.float32)
    elif subtype == "uint8":
        out = np.round(clipped * 127.0 + 128.0).astype(np.uint8)
    else:
        full = _FULL_SCALE[np.dtype(dtype)]
        out = np.round(clipped * (full - 1)).astype(dtype)
    if out.shape[1] == 1:
        out = out[:, 0]
    path.parent.mkdir(parents=True, exist_ok=True)
    wavfile.write(str(path), fs, out)
    return path
