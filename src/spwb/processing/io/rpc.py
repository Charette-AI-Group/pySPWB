"""RPC-III file reading - port of SPWB's RPC_class (read path only).

Ported from (LabVIEW block diagrams in SPWB_export/vis/File IO/RPC_class):
  * ``Functions/READ File.vi``          -> :func:`read_rpc`
  * ``private/Read File Header.vi``     -> :func:`read_rpc_header`
  * ``private/Read Data.vi``            -> the group/channel seek arithmetic
  * ``private/Extract value using keyword.vi`` -> :func:`RPCHeader.get`
  * ``GUI - RPC File (V1.00).vi``       -> :func:`rpc_contents`

RPC-III (MTS / MegaDAC, ``.rsp``) is a fixed-layout binary format:

**Header.** A sequence of 128-byte records, each ``32-byte keyword`` +
``96-byte value``, both NUL-padded ASCII. Records are grouped into 512-byte
blocks of 4. The very first block always carries ``NUM_HEADER_BLOCKS``, so a
reader takes 512 bytes, learns how many blocks there are, and reads the
rest. Data begins at ``NUM_HEADER_BLOCKS * 512``.

**Data.** ``int16`` little-endian, *demultiplexed by group*: the file is a
run of groups, and within one group every channel's ``PTS_PER_GROUP``
samples sit contiguously::

    group 0: [chan 1 x PTS_PER_GROUP][chan 2 x PTS_PER_GROUP]...
    group 1: [chan 1 x PTS_PER_GROUP][chan 2 x PTS_PER_GROUP]...

Engineering units come from ``SCALE.CHAN_n``: ``y = raw * scale``.

**Keyword lookup is by prefix**, exactly as the LabVIEW VI does it - it
compares the first ``len(keyword)`` characters of each record. That is why
SPWB asks for ``DELTA`` and gets ``DELTA_T``, and it is preserved here
because real files disagree about the trailing part of several keywords.

Writing RPC-III is deliberately not implemented; this module reads only.
"""
from __future__ import annotations

import math
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

from ..model.signal import Signal
from .tdms import append_source_to_name, clean_string

__all__ = [
    "BLOCK_SIZE",
    "RECORD_SIZE",
    "RPCChannelInfo",
    "RPCHeader",
    "read_rpc",
    "read_rpc_header",
    "rpc_contents",
]

#: one keyword/value record
RECORD_SIZE = 128
#: header records are read in blocks of four
BLOCK_SIZE = 512
_RECORDS_PER_BLOCK = BLOCK_SIZE // RECORD_SIZE
_KEYWORD_SIZE = 32
#: samples are 16-bit signed, little-endian (``Read Data.vi`` reverses the
#: bytes before unflattening, which is a big-endian read of swapped bytes)
_DTYPE = np.dtype("<i2")
_BYTES_PER_SAMPLE = _DTYPE.itemsize


def _text(raw: bytes) -> str:
    """Decode one NUL-padded ASCII field the way LabVIEW displays it."""
    return clean_string(raw.split(b"\x00", 1)[0].decode("latin-1"))


class RPCHeader:
    """The parsed keyword/value header of an RPC-III file.

    Lookup is by *prefix* (``Extract value using keyword.vi``), so
    ``header["DELTA"]`` finds a ``DELTA_T`` record.
    """

    __slots__ = ("n_blocks", "records")

    def __init__(self, records: list[tuple[str, str]], n_blocks: int) -> None:
        self.records = records
        self.n_blocks = n_blocks

    @property
    def data_offset(self) -> int:
        """Byte offset of the first sample."""
        return self.n_blocks * BLOCK_SIZE

    def get(self, keyword: str, default: str | None = None) -> str:
        """First value whose keyword starts with ``keyword``.

        Raises :class:`KeyError` when there is no match and no ``default``,
        with a message that names the file's keywords - SPWB pops up
        "Sorry but the following Keyword could not be found" here.
        """
        for key, value in self.records:
            if key.startswith(keyword):
                return value
        if default is not None:
            return default
        raise KeyError(
            f"keyword {keyword!r} is not in the RPC-III header; the file has "
            f"{[k for k, _ in self.records[:12]]}..."
        )

    def get_int(self, keyword: str, default: int | None = None) -> int:
        raw = self.get(keyword, "" if default is not None else None)
        try:
            return int(float(raw))
        except ValueError:
            if default is None:
                raise ValueError(
                    f"RPC-III header keyword {keyword!r} is {raw!r}, "
                    f"which is not a number"
                ) from None
            return default

    def get_float(self, keyword: str, default: float | None = None) -> float:
        raw = self.get(keyword, "" if default is not None else None)
        try:
            return float(raw)
        except ValueError:
            if default is None:
                raise ValueError(
                    f"RPC-III header keyword {keyword!r} is {raw!r}, "
                    f"which is not a number"
                ) from None
            return default

    def __contains__(self, keyword: str) -> bool:
        return any(key.startswith(keyword) for key, _ in self.records)

    def as_dict(self) -> dict[str, str]:
        """Every record, first occurrence wins."""
        out: dict[str, str] = {}
        for key, value in self.records:
            out.setdefault(key, value)
        return out

    # -- the derived quantities Read File Header.vi computes ----------------
    @property
    def n_channels(self) -> int:
        return self.get_int("CHANNELS")

    @property
    def dt(self) -> float:
        return self.get_float("DELTA")

    @property
    def group_size(self) -> int:
        """``PTS_PER_GROUP`` - samples per channel in one group."""
        return self.get_int("PTS_PER_GROUP")

    @property
    def frame_size(self) -> int:
        return self.get_int("PTS_PER_FRAME")

    @property
    def n_frames(self) -> int:
        """``FRAMES + HALF_FRAMES``, SPWB's ``NumFrame``."""
        return self.get_int("FRAMES") + self.get_int("HALF_FRAMES", 0)

    @property
    def n_groups(self) -> int:
        """``ceil(NumFrame / frames-per-group)``, SPWB's ``NumberOfGroups``."""
        per_group = self.group_size / self.frame_size
        return int(math.ceil(self.n_frames / per_group))

    @property
    def n_samples(self) -> int:
        """Samples stored per channel, padding included."""
        return self.n_groups * self.group_size

    def channel_name(self, index: int) -> str:
        """``DESC.CHAN_n`` (1-based), falling back to ``Channel n``."""
        return self.get(f"DESC.CHAN_{index}", "") or f"Channel {index}"

    def channel_unit(self, index: int) -> str:
        return self.get(f"UNITS.CHAN_{index}", "")

    def channel_scale(self, index: int) -> float:
        return self.get_float(f"SCALE.CHAN_{index}", 1.0)

    def __repr__(self) -> str:
        return (f"RPCHeader({self.n_channels} channels, "
                f"{self.n_samples} samples, dt={self.dt:g})")


class RPCChannelInfo:
    """One channel as listed by :func:`rpc_contents` (the preview GUI)."""

    __slots__ = ("dt", "index", "n_samples", "name", "scale", "y_unit")

    def __init__(self, index: int, name: str, n_samples: int, dt: float,
                 y_unit: str, scale: float) -> None:
        #: 1-based, as the ``*.CHAN_n`` keywords number them
        self.index = index
        self.name = name
        self.n_samples = n_samples
        self.dt = dt
        self.y_unit = y_unit
        self.scale = scale

    @property
    def duration(self) -> float:
        return self.n_samples * self.dt

    @property
    def path(self) -> str:
        """What to pass to ``read_rpc(select=...)`` for this channel."""
        return self.name

    @property
    def is_waveform(self) -> bool:
        """Always true: an RPC-III header always carries ``DELTA_T``."""
        return True

    def __repr__(self) -> str:
        return (f"RPCChannelInfo({self.index}: {self.name!r}, "
                f"n={self.n_samples}, dt={self.dt!r}, unit={self.y_unit!r})")


def read_rpc_header(path: str | os.PathLike) -> RPCHeader:
    """Read just the header of an RPC-III file (``Read File Header.vi``)."""
    with open(path, "rb") as fh:
        first = fh.read(BLOCK_SIZE)
        if len(first) < BLOCK_SIZE:
            raise ValueError(
                f"{path} is only {len(first)} bytes; an RPC-III file starts "
                f"with a {BLOCK_SIZE}-byte header block"
            )
        records = _split_records(first)
        n_blocks = _num_header_blocks(records, path)
        rest = fh.read((n_blocks - 1) * BLOCK_SIZE) if n_blocks > 1 else b""
        records += _split_records(rest)

    # trailing records in the last block are blank padding
    populated = [(k, v) for k, v in records if k]
    return RPCHeader(populated, n_blocks)


def _split_records(block: bytes) -> list[tuple[str, str]]:
    out = []
    for start in range(0, len(block) - RECORD_SIZE + 1, RECORD_SIZE):
        rec = block[start:start + RECORD_SIZE]
        out.append((_text(rec[:_KEYWORD_SIZE]), _text(rec[_KEYWORD_SIZE:])))
    return out


def _num_header_blocks(records: list[tuple[str, str]],
                       path: str | os.PathLike) -> int:
    for key, value in records:
        if key.startswith("NUM_HEADER"):
            try:
                n = int(float(value))
            except ValueError:
                break
            if n >= 1:
                return n
            break
    raise ValueError(
        f"{path} does not look like an RPC-III file: its first "
        f"{_RECORDS_PER_BLOCK} header records are "
        f"{[k for k, _ in records]!r}, with no usable NUM_HEADER_BLOCKS"
    )


def rpc_contents(path: str | os.PathLike) -> list[RPCChannelInfo]:
    """List every channel in an RPC-III file without importing the data."""
    header = read_rpc_header(path)
    dt, n_samples = header.dt, header.n_samples
    return [
        RPCChannelInfo(
            index=i,
            name=header.channel_name(i),
            n_samples=n_samples,
            dt=dt,
            y_unit=header.channel_unit(i),
            scale=header.channel_scale(i),
        )
        for i in range(1, header.n_channels + 1)
    ]


def read_rpc(path: str | os.PathLike, *,
             select: Sequence[str | int] | None = None,
             decorate_names: bool = False,
             trim_padding: bool = False,
             keep_header: bool = True) -> list[Signal]:
    """Read an RPC-III file into :class:`Signal` objects (``READ File.vi``).

    Parameters
    ----------
    select:
        Channels to import, by ``DESC.CHAN_n`` name or by 1-based index.
        ``None`` reads every channel.
    decorate_names:
        Append the source file name to each signal name, as SPWB does when
        importing into a session that already holds signals.
    trim_padding:
        The last group of an RPC-III file is padded out to a whole group,
        so a recording of 3.5 groups still stores 4. LabVIEW keeps the
        padding; pass ``True`` to cut each signal back to
        ``NumFrame * PTS_PER_FRAME`` samples. Off by default so results
        match the LabVIEW application sample for sample.
    keep_header:
        Keep the whole keyword/value header under the ``RPC`` attribute, so
        nothing from the original file is silently dropped.

    Raises
    ------
    KeyError
        if ``select`` names a channel the file does not contain.
    ValueError
        if the file is truncated, or its header is not RPC-III.
    """
    src = str(Path(path).resolve())
    header = read_rpc_header(path)

    n_channels = header.n_channels
    group_size = header.group_size
    n_groups = header.n_groups
    n_samples = n_groups * group_size
    dt = header.dt
    if dt <= 0:
        raise ValueError(f"{src} declares DELTA_T={dt!r}; expected a positive "
                         f"sampling interval")

    wanted = _resolve_selection(select, header)
    if wanted is not None and not wanted:
        return []

    group_bytes = n_channels * group_size * _BYTES_PER_SAMPLE
    channel_bytes = group_size * _BYTES_PER_SAMPLE
    needed = header.data_offset + n_groups * group_bytes
    actual = os.path.getsize(path)
    if actual < needed:
        raise ValueError(
            f"{src} is truncated: its header describes {n_channels} channels "
            f"x {n_groups} groups x {group_size} samples "
            f"({needed} bytes needed, file is {actual})"
        )

    keep = n_samples
    if trim_padding:
        keep = min(n_samples, header.n_frames * header.frame_size)

    raw_header = header.as_dict() if keep_header else None
    signals: list[Signal] = []
    with open(path, "rb") as fh:
        for index in range(1, n_channels + 1):
            if wanted is not None and index not in wanted:
                continue
            y = np.empty(n_samples, dtype=float)
            for group in range(n_groups):
                fh.seek(header.data_offset + group * group_bytes
                        + (index - 1) * channel_bytes)
                chunk = np.frombuffer(fh.read(channel_bytes), dtype=_DTYPE)
                y[group * group_size:(group + 1) * group_size] = chunk
            y *= header.channel_scale(index)

            signals.append(_to_signal(header, index, y[:keep], src, raw_header,
                                      decorate_names))
    return signals


def _resolve_selection(select: Sequence[str | int] | None,
                       header: RPCHeader) -> set[int] | None:
    """Turn names and/or 1-based indices into a set of channel indices."""
    if select is None:
        return None
    by_name = {header.channel_name(i): i
               for i in range(1, header.n_channels + 1)}
    wanted: set[int] = set()
    missing: list[str | int] = []
    for item in select:
        if isinstance(item, int):
            if 1 <= item <= header.n_channels:
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
            f"channel(s) not found in the RPC-III file: {missing}; "
            f"it has {sorted(by_name)}"
        )
    return wanted


def _to_signal(header: RPCHeader, index: int, y: np.ndarray, src: str,
               raw_header: dict[str, str] | None,
               decorate_names: bool) -> Signal:
    name = header.channel_name(index)
    unit = header.channel_unit(index)
    attributes: dict[str, Any] = {
        "Channel Name": name,
        "Channel Unit": unit,
        "X Axis Unit": "s",
        "Data Source": src,
        "RPC Channel": index,
        "RPC Scale": header.channel_scale(index),
        "RPC Group Size": header.group_size,
        "RPC Frames": header.n_frames,
    }
    if raw_header is not None:
        attributes["RPC"] = raw_header

    sig = Signal(name=name, y=y, dt=header.dt, t0=0.0, y_unit=unit,
                 x_unit="s", attributes=attributes)
    return append_source_to_name(sig) if decorate_names else sig
