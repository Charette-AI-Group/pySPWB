"""TDMS file IO - port of SPWB's TDMS_class.

Ported from (LabVIEW block diagrams in SPWB_export/vis/File IO/TDMS_class):
  * ``READ - File.vi``            -> :func:`read_tdms` (all channels)
  * ``IMPORT Signals - File.vi``  -> :func:`read_tdms` with ``select=``
  * ``WRITE - File.vi``           -> :func:`write_tdms`
  * ``GUI - Multi TDMS Files Preview.vi`` -> :func:`tdms_contents`
  * ``Set - wForm from Raw Data.vi`` / ``WF - Append Src Name to Sig Name.vi``
    -> the attribute and naming conventions below.

SPWB attribute conventions carried on every imported Signal:

==================  ====================================================
``Channel Name``    signal name (may be decorated with the source file)
``Channel Unit``    Y unit
``X Axis Unit``     X unit ("s" for time data)
``Data Source``     absolute path of the file the signal came from
==================  ====================================================

Byte-level TDMS parsing is delegated to :mod:`nptdms`; this module is the
mapping layer (channel + NI waveform properties -> :class:`Signal`), which
is what the tests exercise.
"""
from __future__ import annotations

import os
import re
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from ..model.signal import Signal

__all__ = [
    "ChannelInfo",
    "append_source_to_name",
    "clean_string",
    "read_tdms",
    "tdms_contents",
    "write_tdms",
]

# NI waveform property names written by LabVIEW's TDMS Write for waveforms
_P_INCREMENT = "wf_increment"
_P_START_OFFSET = "wf_start_offset"
_P_START_TIME = "wf_start_time"
_P_SAMPLES = "wf_samples"
_P_XUNIT = "wf_xunit_string"
_P_XNAME = "wf_xname"
_P_YUNIT = ("NI_UnitDescription", "unit_string")

_MULTISPACE = re.compile(r"\s{2,}")


def clean_string(s: str) -> str:
    """SPWB's ``Remove Double Spaces`` applied to names and units on import."""
    return _MULTISPACE.sub(" ", str(s)).strip()


def append_source_to_name(signal: Signal) -> Signal:
    """``WF - Append Src Name to Sig Name.vi``: ``name (source file name)``.

    The source is the ``Data Source`` attribute stripped to its file name;
    it falls back to ``unknown`` exactly as the LabVIEW VI does.
    """
    source = signal.attributes.get("Data Source", "")
    src_name = Path(source).name if source else "unknown"
    name = f"{signal.name} ({src_name})"
    return signal.with_(name=name, attributes={"Channel Name": name})


class ChannelInfo:
    """One channel as listed by :func:`tdms_contents` (preview GUIs)."""

    __slots__ = ("channel", "dt", "group", "is_waveform", "n_samples", "y_unit")

    def __init__(self, group: str, channel: str, n_samples: int,
                 dt: float | None, y_unit: str, is_waveform: bool) -> None:
        self.group = group
        self.channel = channel
        self.n_samples = n_samples
        self.dt = dt
        self.y_unit = y_unit
        self.is_waveform = is_waveform

    @property
    def path(self) -> str:
        return f"{self.group}/{self.channel}"

    @property
    def duration(self) -> float | None:
        return None if self.dt is None else self.n_samples * self.dt

    def __repr__(self) -> str:
        return (f"ChannelInfo({self.path!r}, n={self.n_samples}, "
                f"dt={self.dt!r}, unit={self.y_unit!r})")


def _open(path: str | os.PathLike):
    try:
        from nptdms import TdmsFile
    except ImportError as exc:  # pragma: no cover - depends on env
        raise ImportError(
            "reading TDMS files requires nptdms: pip install spwb[io]"
        ) from exc
    return TdmsFile.read(str(path))


def _y_unit(props: dict[str, Any]) -> str:
    for key in _P_YUNIT:
        if props.get(key):
            return clean_string(props[key])
    return ""


def tdms_contents(path: str | os.PathLike) -> list[ChannelInfo]:
    """List every channel in a TDMS file without committing to import."""
    tdms = _open(path)
    out: list[ChannelInfo] = []
    for group in tdms.groups():
        for ch in group.channels():
            props = dict(ch.properties)
            dt = props.get(_P_INCREMENT)
            out.append(ChannelInfo(
                group=group.name,
                channel=ch.name,
                n_samples=len(ch),
                dt=float(dt) if dt else None,
                y_unit=_y_unit(props),
                is_waveform=_P_INCREMENT in props,
            ))
    return out


def read_tdms(path: str | os.PathLike, *,
              select: Sequence[str] | None = None,
              dt: float | None = None,
              decorate_names: bool = False,
              keep_properties: bool = True) -> list[Signal]:
    """Read a TDMS file into :class:`Signal` objects.

    Parameters
    ----------
    select:
        Channel selection, as ``"group/channel"`` or bare ``"channel"``
        names (SPWB's ``IMPORT Signals - File.vi``). ``None`` reads every
        channel (``READ - File.vi``).
    dt:
        Sampling interval to assume for channels that carry no
        ``wf_increment`` property. Without it such channels raise.
    decorate_names:
        Append the source file name to each signal name, as SPWB does when
        importing into a session that already holds signals.
    keep_properties:
        Keep the raw TDMS properties under the ``TDMS`` attribute key, so
        nothing from the original file is silently dropped.

    Raises
    ------
    KeyError
        if ``select`` names a channel the file does not contain.
    ValueError
        if a selected channel has no timing information and no ``dt``.
    """
    src = str(Path(path).resolve())
    tdms = _open(path)

    wanted: set[str] | None = None
    if select is not None:
        wanted = {s.strip() for s in select}
        if not wanted:
            return []

    signals: list[Signal] = []
    matched: set[str] = set()
    for group in tdms.groups():
        for ch in group.channels():
            full = f"{group.name}/{ch.name}"
            if wanted is not None:
                hit = full if full in wanted else (
                    ch.name if ch.name in wanted else None)
                if hit is None:
                    continue
                matched.add(hit)

            props = dict(ch.properties)
            y = np.asarray(ch[:], dtype=float)
            increment = props.get(_P_INCREMENT)
            step = float(increment) if increment else dt
            if not step or step <= 0:
                raise ValueError(
                    f"channel {full!r} has no {_P_INCREMENT} property; "
                    f"pass dt= to read it as sampled data"
                )

            name = clean_string(ch.name)
            attributes: dict[str, Any] = {
                "Channel Name": name,
                "Channel Unit": _y_unit(props),
                "X Axis Unit": clean_string(props.get(_P_XUNIT, "s")) or "s",
                "Data Source": src,
                "TDMS Group": group.name,
            }
            if _P_START_TIME in props:
                attributes["Start Time"] = props[_P_START_TIME]
            if _P_XNAME in props:
                attributes["X Axis Name"] = clean_string(props[_P_XNAME])
            if keep_properties:
                attributes["TDMS"] = props

            sig = Signal(
                name=name,
                y=y,
                dt=step,
                t0=float(props.get(_P_START_OFFSET, 0.0)),
                y_unit=attributes["Channel Unit"],
                x_unit=attributes["X Axis Unit"],
                attributes=attributes,
            )
            signals.append(append_source_to_name(sig) if decorate_names else sig)

    if wanted is not None and (missing := wanted - matched):
        raise KeyError(f"channel(s) not found in {src}: {sorted(missing)}")
    return signals


def write_tdms(path: str | os.PathLike, signals: Iterable[Signal], *,
               group: str = "SPWB") -> Path:
    """Write signals to a TDMS file (``WRITE - File.vi``).

    Each signal becomes one channel carrying the NI waveform properties, so
    LabVIEW and other TDMS readers see it as a waveform rather than raw
    samples. Signals keep their original ``TDMS Group`` when they have one.
    """
    try:
        from nptdms import ChannelObject, TdmsWriter
    except ImportError as exc:  # pragma: no cover - depends on env
        raise ImportError(
            "writing TDMS files requires nptdms: pip install spwb[io]"
        ) from exc

    out = Path(path)
    objects = []
    for sig in signals:
        props = {
            _P_INCREMENT: float(sig.dt),
            _P_START_OFFSET: float(sig.t0),
            _P_SAMPLES: int(sig.n_samples),
            _P_XUNIT: sig.x_unit,
            _P_XNAME: sig.attributes.get("X Axis Name", "Time"),
        }
        if sig.y_unit:
            props["NI_UnitDescription"] = sig.y_unit
        start_time = sig.attributes.get("Start Time")
        if start_time is not None:
            props[_P_START_TIME] = start_time
        objects.append(ChannelObject(
            sig.attributes.get("TDMS Group", group), sig.name,
            np.asarray(sig.y, dtype=float), properties=props,
        ))

    with TdmsWriter(str(out)) as writer:
        writer.write_segment(objects)
    return out
