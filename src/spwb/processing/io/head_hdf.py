"""HEAD acoustics HDF reading - port of SPWB's HeadAcousticHDF_class.

Ported from (LabVIEW block diagrams in
SPWB_export/vis/File IO/HeadAcousticHDF_class):
  * ``Functions/READ - File.vi``                 -> :func:`read_head_hdf`
  * ``Functions/READ - File & Channels INFO.vi`` -> :func:`head_hdf_contents`

.. warning::

   A HEAD acoustics ``.hdf`` file has **nothing to do with HDF5**. Despite
   the extension it is HEAD acoustics' own recording format; SPWB's native
   format is the unrelated HDF5 in :mod:`spwb.processing.io.hdf5`.

**This module parses the format directly.** The LabVIEW application did not
- it opened the file through NI's Universal Storage Interface with HEAD
acoustics' ``HEAD_Data_Format`` DataPlugin, which is a Windows-only install
most people do not have. That turned out to be unnecessary: the container is
self-describing and its header is plain ASCII, so reading it needs nothing
but the standard library and numpy, on any platform.

**The layout**

A fixed-size ASCII header, then the raw samples::

    ;
    ; Copyright 1999 HEAD acoustics GmbH, Germany
    ;
    version:                           4
    byte order:                        Intel
    kind:                              Time data
    start of data:                     65536      <- payload offset
    nbr of channel:                    1
    abscissa definition:               1          <- starts a block
    delta value:                       0.000122070313
    nbr of scans:                      245760
    channel definition:                1          <- starts a block
    physical unit:                     Pa
    implementation type:               FLOAT32

``key: value``, one per line, padded to ``start of data`` with tabs. Lines
beginning ``;`` are comments; ``;#key: value`` is a *disabled* field, which
is how optional metadata such as the recording date is carried - those are
parsed too, into :attr:`HeadFile.optional`.

Keys repeat, so the header is **block structured**: ``abscissa definition``
and ``channel definition`` open a block and every key after one belongs to
it. That is why ``name str`` can appear three times in a file and mean
three different things.

**Two things that look like traps and are not**

* ``calibration`` is *not* a scale factor. The sample files carry
  ``calibration: 94`` on a pressure channel whose samples are already in
  Pa and peak at exactly 1.0 - 94 dB is simply the level of the calibrator
  that was used (1 Pa RMS re 20 uPa). Another carries ``calibration: -10``
  on an acceleration channel, which as a multiplier would invert the
  measurement. It is metadata, and is kept as an attribute.
* ``delta value`` is written rounded to nine significant figures, so
  ``1/8192`` appears as ``0.000122070313``. Over a 30-second recording that
  rounding accumulates to about 0.1 us of drift. The header value is used
  as-is, because it is what the file says and what other readers will use.

Writing HDF is deliberately not implemented; this module reads only.
"""
from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

from ..model.signal import Signal
from .tdms import append_source_to_name, clean_string

__all__ = [
    "BYTE_ORDERS",
    "DATA_TYPES",
    "HeadChannelInfo",
    "HeadFile",
    "HeadFormatError",
    "head_hdf_contents",
    "read_head_hdf",
    "read_head_hdf_header",
]

#: ``implementation type`` -> numpy base dtype. Only ``FLOAT32`` has been
#: seen in the wild; the rest follow the same naming and are decoded on the
#: same path, but no sample file exercised them.
DATA_TYPES: dict[str, str] = {
    "FLOAT32": "f4",
    "FLOAT64": "f8",
    "DOUBLE": "f8",
    "INT8": "i1",
    "INT16": "i2",
    "INT32": "i4",
    "INT64": "i8",
    "UINT8": "u1",
    "UINT16": "u2",
    "UINT32": "u4",
}

#: ``byte order`` -> numpy byte-order prefix
BYTE_ORDERS: dict[str, str] = {"INTEL": "<", "MOTOROLA": ">"}

#: keys that open a definition block; every later key belongs to it
_BLOCK_KEYS = ("abscissa definition", "channel definition",
               "subchannel definition", "extra field definition")

#: the only channel interleaving seen, and the only one we decode:
#: one sample of every channel in turn
_INTERLEAVED = "a1b1 a2b2"

_START_OF_DATA = "start of data"
#: enough to be sure of catching ``start of data`` before we know the length
_PROBE_BYTES = 8192
_TIME_DATA = "TIME DATA"


class HeadFormatError(ValueError):
    """Raised when a file is not a HEAD acoustics HDF we can read.

    The message says which part of the header was wrong, because the usual
    cause is a file of a different *kind* (a spectrum rather than a
    recording) rather than a corrupt one.
    """


class HeadChannelInfo:
    """One channel as listed by :func:`head_hdf_contents`."""

    __slots__ = ("channel", "description", "dt", "group", "index",
                 "n_samples", "quantity", "y_unit")

    def __init__(self, group: str, channel: str, n_samples: int,
                 dt: float | None, y_unit: str, description: str = "",
                 quantity: str = "", index: int = 1) -> None:
        self.group = group
        self.channel = channel
        self.n_samples = n_samples
        self.dt = dt
        self.y_unit = y_unit
        self.description = description
        #: what the header calls ``physical quantity`` (pressure, ...)
        self.quantity = quantity
        #: 1-based, as ``channel definition: n`` numbers them
        self.index = index

    @property
    def path(self) -> str:
        return f"{self.group}/{self.channel}"

    @property
    def duration(self) -> float | None:
        return None if self.dt is None else self.n_samples * self.dt

    @property
    def is_waveform(self) -> bool:
        """Whether the file gave the channel a sampling interval."""
        return self.dt is not None

    def __repr__(self) -> str:
        return (f"HeadChannelInfo({self.path!r}, n={self.n_samples}, "
                f"dt={self.dt!r}, unit={self.y_unit!r})")


class HeadFile:
    """The parsed header of a HEAD acoustics HDF file."""

    __slots__ = ("blocks", "optional", "top")

    def __init__(self, top: dict[str, str], blocks: list[dict[str, str]],
                 optional: dict[str, str]) -> None:
        #: keys before the first definition block
        self.top = top
        #: one dict per definition block, in file order
        self.blocks = blocks
        #: ``;#key: value`` fields - disabled in this file, but informative
        self.optional = optional

    def _of_kind(self, kind: str) -> list[dict[str, str]]:
        return [b for b in self.blocks if b["definition"] == kind]

    @property
    def abscissas(self) -> list[dict[str, str]]:
        return self._of_kind("abscissa definition")

    @property
    def channels(self) -> list[dict[str, str]]:
        return self._of_kind("channel definition")

    @property
    def data_offset(self) -> int:
        return int(self.top[_START_OF_DATA])

    @property
    def byte_order(self) -> str:
        raw = self.top.get("byte order", "Intel").strip().upper()
        try:
            return BYTE_ORDERS[raw]
        except KeyError:
            raise HeadFormatError(
                f"unknown byte order {raw!r}; expected one of "
                f"{sorted(BYTE_ORDERS)}"
            ) from None

    @property
    def kind(self) -> str:
        return self.top.get("kind", "")

    @property
    def n_channels(self) -> int:
        return int(self.top.get("nbr of channel", len(self.channels)))

    @property
    def n_samples(self) -> int:
        """``nbr of scans`` - samples per channel."""
        return int(self.abscissas[0]["nbr of scans"])

    @property
    def dt(self) -> float | None:
        value = self.abscissas[0].get("delta value")
        return float(value) if value else None

    @property
    def t0(self) -> float:
        return float(self.abscissas[0].get("first value", 0.0) or 0.0)

    @property
    def x_unit(self) -> str:
        return clean_string(self.abscissas[0].get("physical unit", "s")) or "s"

    @property
    def recorded(self) -> str:
        """Recording date, if the file carries one (often a disabled key).

        The readable form is preferred over the machine timestamp beside it.
        """
        return (self.optional.get("date of recording text")
                or self.optional.get("date of recording", ""))

    def dtype(self, channel: dict[str, str]) -> np.dtype:
        raw = channel.get("implementation type", "FLOAT32").strip().upper()
        try:
            return np.dtype(self.byte_order + DATA_TYPES[raw])
        except KeyError:
            raise HeadFormatError(
                f"channel {channel.get('name str')!r} stores "
                f"{raw!r} samples, which this reader does not decode; "
                f"known types are {sorted(DATA_TYPES)}"
            ) from None

    def __repr__(self) -> str:
        return (f"HeadFile({self.kind!r}, {self.n_channels} channels, "
                f"{self.n_samples} samples)")


def _continuation(lines: list[str], n: int) -> str | None:
    """Text carried on the plain comment line after a ``;#key:`` line.

    ``;#date of recording:`` stores a machine timestamp, and the ``;`` line
    under it repeats the date in a form a human can read::

        ;#date of recording:   30063977-4197303808
        ;                      3/6/2010 15:17:00.000
    """
    if n + 1 >= len(lines):
        return None
    following = lines[n + 1].lstrip()
    if not following.startswith(";") or following.startswith(";#"):
        return None
    text = following[1:].strip("\t ")
    return text or None


def _data_offset(probe: bytes, path: str, size: int) -> int:
    """``start of data`` - where the header stops and the samples begin."""
    offset = None
    for line in probe.decode("latin-1").splitlines():
        key, _, value = line.partition(":")
        if key.strip().lower() == _START_OF_DATA:
            try:
                offset = int(value.strip())
            except ValueError:
                offset = None
            break
    if offset is None or offset <= 0:
        raise HeadFormatError(
            f"{path} has no usable '{_START_OF_DATA}' line in its first "
            f"{len(probe)} bytes, so it is not a HEAD acoustics HDF file"
        )
    if offset > size:
        raise HeadFormatError(
            f"{path}: header says data starts at {offset} but the file is "
            f"only {size} bytes"
        )
    return offset


def _parse_header(raw: bytes, path: str) -> HeadFile:
    top: dict[str, str] = {}
    optional: dict[str, str] = {}
    blocks: list[dict[str, str]] = []
    current: dict[str, str] | None = None

    lines = raw.decode("latin-1").splitlines()
    for n, line in enumerate(lines):
        line = line.rstrip("\t ")
        stripped = line.lstrip()
        target = top
        if stripped.startswith(";"):
            # ";#key: value" is a disabled field; a bare ";" is a comment
            if not stripped.startswith(";#"):
                continue
            line, target = stripped[2:], optional
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip().lower(), value.strip()
        if not key:
            continue
        if target is optional:
            optional.setdefault(key, value)
            # a disabled field may be continued on the plain comment line
            # below it, which is where the readable recording date lives
            if (follow := _continuation(lines, n)) is not None:
                optional.setdefault(f"{key} text", follow)
        elif key in _BLOCK_KEYS:
            current = {"definition": key, "index": value}
            blocks.append(current)
        elif current is not None:
            current.setdefault(key, value)
        else:
            top.setdefault(key, value)

    header = HeadFile(top, blocks, optional)
    if _START_OF_DATA not in top:
        raise HeadFormatError(f"{path}: header has no {_START_OF_DATA!r}")
    if not header.abscissas:
        raise HeadFormatError(
            f"{path}: header has no 'abscissa definition' block, so there is "
            f"no sampling interval to read the data with"
        )
    if not header.channels:
        raise HeadFormatError(f"{path}: header defines no channels")
    return header


def read_head_hdf_header(path: str | os.PathLike) -> HeadFile:
    """Read and parse the ASCII header, without touching the samples."""
    size = os.path.getsize(path)
    with open(path, "rb") as fh:
        offset = _data_offset(fh.read(_PROBE_BYTES), str(path), size)
        fh.seek(0)
        return _parse_header(fh.read(offset), str(path))


def _require_time_data(header: HeadFile, path: str) -> None:
    if header.kind.strip().upper() != _TIME_DATA:
        raise HeadFormatError(
            f"{path} is {header.kind!r}, not {_TIME_DATA!r}. This reader "
            f"handles recordings; open spectra and other analysis results in "
            f"ArtemiS and export them as time data or WAV."
        )


def _channel_name(channel: dict[str, str], index: int) -> str:
    name = clean_string(channel.get("name str", ""))
    return name or f"Channel {index}"


def head_hdf_contents(path: str | os.PathLike) -> list[HeadChannelInfo]:
    """List every channel in an HDF file without reading the samples."""
    header = read_head_hdf_header(path)
    group = Path(path).stem
    dt, n = header.dt, header.n_samples
    return [
        HeadChannelInfo(
            group=group,
            channel=_channel_name(channel, i),
            n_samples=n,
            dt=dt,
            y_unit=clean_string(channel.get("physical unit", "")),
            description=clean_string(channel.get("title str", "")),
            quantity=clean_string(channel.get("physical quantity", "")),
            index=i,
        )
        for i, channel in enumerate(header.channels, start=1)
    ]


def read_head_hdf(path: str | os.PathLike, *,
                  select: Sequence[str | int] | None = None,
                  dt: float | None = None,
                  decorate_names: bool = False,
                  keep_header: bool = True) -> list[Signal]:
    """Read a HEAD acoustics HDF recording into :class:`Signal` objects.

    Parameters
    ----------
    select:
        Channels to import, by name, by ``"file/channel"`` path, or by
        1-based index. ``None`` reads every channel, which is what
        ``READ - File.vi`` does with its ``Channel Selected (0=ALL)``
        default.
    dt:
        Sampling interval to use when the file's abscissa block carries no
        ``delta value``. Without it such a file raises.
    decorate_names:
        Append the source file name to each signal name, as SPWB does when
        importing into a session that already holds signals.
    keep_header:
        Keep the file's own header fields under the ``HDF`` attribute, so
        nothing is silently dropped.

    Raises
    ------
    HeadFormatError
        if the file is not a readable HEAD acoustics recording.
    KeyError
        if ``select`` names a channel the file does not contain.
    ValueError
        if the file has no timing information and no ``dt`` was given.
    """
    src = str(Path(path).resolve())
    header = read_head_hdf_header(path)
    _require_time_data(header, src)

    step = header.dt or dt
    if not step or step <= 0:
        raise ValueError(
            f"{src} carries no 'delta value' in its abscissa block; "
            f"pass dt= to read it as sampled data"
        )

    channels = header.channels
    if len(channels) != header.n_channels:
        raise HeadFormatError(
            f"{src} says 'nbr of channel: {header.n_channels}' but defines "
            f"{len(channels)} channel block(s)"
        )
    org = header.top.get("data org", _INTERLEAVED).strip()
    if len(channels) > 1 and org != _INTERLEAVED:
        raise HeadFormatError(
            f"{src} stores its channels as {org!r}; this reader decodes "
            f"{_INTERLEAVED!r} (one sample of each channel in turn)"
        )

    group = Path(path).stem
    wanted = _resolve_selection(select, channels, group)
    if wanted is not None and not wanted:
        return []

    y = _read_samples(path, header, channels)

    raw_header = {**header.top, **header.optional} if keep_header else None
    signals: list[Signal] = []
    for i, channel in enumerate(channels, start=1):
        if wanted is not None and i not in wanted:
            continue
        name = _channel_name(channel, i)
        unit = clean_string(channel.get("physical unit", ""))
        attributes: dict[str, Any] = {
            "Channel Name": name,
            "Channel Unit": unit,
            "X Axis Unit": header.x_unit,
            "Data Source": src,
            "HDF Group": group,
            "HDF Channel": i,
            "Physical Quantity": clean_string(
                channel.get("physical quantity", "")),
        }
        # metadata, not a gain - see the module docstring
        if channel.get("calibration"):
            attributes["Calibration"] = channel["calibration"]
        if header.recorded:
            attributes["Start Time"] = header.recorded
        if channel.get("title str"):
            attributes["Description"] = clean_string(channel["title str"])
        if raw_header is not None:
            attributes["HDF"] = {**raw_header, **channel}

        sig = Signal(name=name, y=y[i - 1], dt=step, t0=header.t0,
                     y_unit=unit, x_unit=header.x_unit,
                     attributes=attributes)
        signals.append(append_source_to_name(sig) if decorate_names else sig)
    return signals


def _resolve_selection(select: Sequence[str | int] | None,
                       channels: list[dict[str, str]],
                       group: str) -> set[int] | None:
    """Turn names, ``group/name`` paths and 1-based indices into indices."""
    if select is None:
        return None
    by_name: dict[str, int] = {}
    for i, channel in enumerate(channels, start=1):
        name = _channel_name(channel, i)
        by_name[name] = i
        by_name[f"{group}/{name}"] = i

    wanted: set[int] = set()
    missing: list[str | int] = []
    for item in select:
        if isinstance(item, int):
            if 1 <= item <= len(channels):
                wanted.add(item)
            else:
                missing.append(item)
        else:
            key = clean_string(item)
            if key in by_name:
                wanted.add(by_name[key])
            else:
                missing.append(item)
    if missing:
        raise KeyError(
            f"channel(s) not found in the HDF file: {missing}; it has "
            f"{sorted({_channel_name(c, i) for i, c in enumerate(channels, 1)})}"
        )
    return wanted


def _read_samples(path: str | os.PathLike, header: HeadFile,
                  channels: list[dict[str, str]]) -> np.ndarray:
    """All channels as a ``(n_channels, n_samples)`` float array."""
    dtypes = {header.dtype(c) for c in channels}
    if len(dtypes) > 1:
        raise HeadFormatError(
            f"{path} mixes sample formats across channels "
            f"({sorted(str(d) for d in dtypes)}); this reader needs one "
            f"format for the whole file"
        )
    dtype = dtypes.pop()
    n_channels, n_samples = len(channels), header.n_samples
    needed = n_channels * n_samples * dtype.itemsize
    available = os.path.getsize(path) - header.data_offset
    if available < needed:
        raise HeadFormatError(
            f"{path} is truncated: its header describes {n_channels} "
            f"channel(s) x {n_samples} samples of {dtype} "
            f"({needed} bytes), but only {available} follow the header"
        )

    flat = np.fromfile(path, dtype=dtype, count=n_channels * n_samples,
                       offset=header.data_offset)
    # "a1b1 a2b2": one sample of each channel in turn
    return flat.reshape(n_samples, n_channels).T.astype(float)
