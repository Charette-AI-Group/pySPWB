"""HDF5 - SPWB's native file format.

The format is plain HDF5 with a documented layout (``docs/hdf5-format.md``),
chosen over TDMS for the Python port because it is an open standard that
MATLAB, Julia, R, C++ and HDFView all read without SPWB installed. The data
model maps onto TDMS almost exactly - file, groups, channels, attributes at
every level - so converting between them loses nothing.

Three decisions here are deliberate and easy to undo by accident:

* **strings are fixed-length UTF-8 bytes**, not h5py's default
  variable-length strings, because older MATLAB and some C readers handle
  variable-length poorly. Consumers decode; everyone can read;
* **writes are atomic** - a temporary file in the destination directory,
  then a rename - because a process killed mid-write is the one way to
  produce an unreadable HDF5 file;
* **the ``name`` attribute is authoritative**, not the dataset key, since
  HDF5 keys cannot contain ``/`` and must be unique.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from ..model.signal import Signal

__all__ = [
    "FORMAT_NAME",
    "FORMAT_VERSION",
    "HDF5ChannelInfo",
    "hdf5_contents",
    "read_hdf5",
    "write_hdf5",
]

FORMAT_NAME = "SPWB-HDF5"
FORMAT_VERSION = "1.0"

DEFAULT_GROUP = "SPWB"
#: U+2215 DIVISION SLASH - stands in for "/" which HDF5 reserves for paths.
#: The look-alike is the point: a browsing user sees "Left/Right" while
#: HDF5 sees a single legal key.
_SLASH = "∕"  # noqa: RUF001
_JSON_ATTRS = "_spwb_json_attrs"
_SKIPPED_ATTRS = "_spwb_skipped_attrs"
# written per dataset, so never treated as user attributes on read
_RESERVED = {"name", "dt", "t0", "unit", "x_unit", _JSON_ATTRS,
             _SKIPPED_ATTRS}


def _require_h5py():
    try:
        import h5py
    except ImportError as exc:  # pragma: no cover - depends on env
        raise ImportError(
            "reading and writing HDF5 files requires h5py: "
            "pip install spwb[io]"
        ) from exc
    return h5py


def _encode(text: str) -> np.bytes_:
    """Fixed-length UTF-8 bytes - readable by MATLAB and every C reader."""
    return np.bytes_(str(text).encode("utf-8"))


def _decode(value: Any) -> Any:
    """Undo :func:`_encode`, leaving anything else alone."""
    if isinstance(value, bytes | np.bytes_):
        return value.decode("utf-8")
    return value


def _json_default(value: Any) -> str:
    """Stringify only the types where a string genuinely carries the value.

    Deliberately narrow: a blanket ``default=str`` would happily store
    ``"<function <lambda> at 0x7f...>"`` - a memory address masquerading as
    data. Anything not listed here raises, and the caller skips it.
    """
    if isinstance(value, _dt.datetime | _dt.date | _dt.time):
        return value.isoformat()
    if isinstance(value, np.datetime64 | np.timedelta64):
        return str(value)
    if isinstance(value, os.PathLike):
        return os.fspath(value)
    raise TypeError(f"cannot represent {type(value).__name__} in HDF5")


def _is_native(value: Any) -> bool:
    """Can HDF5 store this as-is, without JSON?"""
    if isinstance(value, str | bytes | np.bytes_ | bool | np.bool_):
        return True
    if isinstance(value, int | float | complex | np.number):
        return True
    if isinstance(value, np.ndarray):
        return value.dtype.kind in "biufc"
    return False


class HDF5ChannelInfo:
    """One channel as listed by :func:`hdf5_contents`."""

    __slots__ = ("dt", "group", "key", "n_samples", "name", "unit")

    def __init__(self, group: str, key: str, name: str, n_samples: int,
                 dt: float, unit: str) -> None:
        self.group = group
        self.key = key
        self.name = name
        self.n_samples = n_samples
        self.dt = dt
        self.unit = unit

    @property
    def path(self) -> str:
        return f"{self.group}/{self.key}"

    @property
    def fs(self) -> float:
        return 1.0 / self.dt if self.dt else float("nan")

    @property
    def duration(self) -> float:
        return self.n_samples * self.dt

    def __repr__(self) -> str:
        return (f"HDF5ChannelInfo({self.path!r}, n={self.n_samples}, "
                f"{self.fs:g} Hz, unit={self.unit!r})")


# --------------------------------------------------------------------------
# reading
# --------------------------------------------------------------------------
def hdf5_contents(path: str | os.PathLike) -> list[HDF5ChannelInfo]:
    """List the channels in an SPWB HDF5 file without importing them."""
    h5py = _require_h5py()
    out: list[HDF5ChannelInfo] = []
    with h5py.File(str(path), "r") as f:
        for group_name, group in f.items():
            if not isinstance(group, h5py.Group):
                continue
            for key, dataset in group.items():
                if not isinstance(dataset, h5py.Dataset):
                    continue
                attrs = dataset.attrs
                out.append(HDF5ChannelInfo(
                    group=group_name,
                    key=key,
                    name=_decode(attrs.get("name", key)),
                    n_samples=int(dataset.shape[0]) if dataset.shape else 0,
                    dt=float(attrs.get("dt", 0.0)),
                    unit=_decode(attrs.get("unit", "")),
                ))
    return out


def read_hdf5(path: str | os.PathLike, *,
              select: Sequence[str] | None = None,
              decorate_names: bool = False) -> list[Signal]:
    """Read an SPWB HDF5 file into :class:`Signal` objects.

    ``select`` picks channels by ``"group/key"``, by bare key, or by the
    signal's ``name``. ``None`` reads everything.
    """
    h5py = _require_h5py()
    source = str(Path(path).resolve())
    wanted = {s.strip() for s in select} if select is not None else None
    if wanted is not None and not wanted:
        return []

    signals: list[Signal] = []
    matched: set[str] = set()
    with h5py.File(source, "r") as f:
        for group_name, group in f.items():
            if not isinstance(group, h5py.Group):
                continue
            for key, dataset in group.items():
                if not isinstance(dataset, h5py.Dataset):
                    continue
                attrs = dataset.attrs
                name = _decode(attrs.get("name", key))
                full = f"{group_name}/{key}"
                if wanted is not None:
                    hit = next((candidate for candidate in (full, key, name)
                                if candidate in wanted), None)
                    if hit is None:
                        continue
                    matched.add(hit)

                dt = float(attrs.get("dt", 0.0))
                if dt <= 0:
                    raise ValueError(
                        f"{full!r} has no usable 'dt' attribute; it is not "
                        f"an SPWB HDF5 signal")

                json_names = {_decode(v) for v in
                              np.atleast_1d(attrs.get(_JSON_ATTRS, []))}
                attributes: dict[str, Any] = {}
                for attr_name, value in attrs.items():
                    if attr_name in _RESERVED:
                        continue
                    if attr_name in json_names:
                        attributes[attr_name] = json.loads(_decode(value))
                    else:
                        attributes[attr_name] = _decode(value)

                attributes.setdefault("Channel Name", name)
                attributes["Data Source"] = source
                attributes["HDF5 Group"] = group_name

                sig = Signal(
                    name=name,
                    y=np.asarray(dataset[...], dtype=float),
                    dt=dt,
                    t0=float(attrs.get("t0", 0.0)),
                    y_unit=_decode(attrs.get("unit", "")),
                    x_unit=_decode(attrs.get("x_unit", "s")),
                    attributes=attributes,
                )
                if decorate_names:
                    from .tdms import append_source_to_name
                    sig = append_source_to_name(sig)
                signals.append(sig)

    if wanted is not None and (missing := wanted - matched):
        raise KeyError(f"channel(s) not found in {source}: {sorted(missing)}")
    return signals


# --------------------------------------------------------------------------
# writing
# --------------------------------------------------------------------------
def _dataset_key(name: str, used: set[str]) -> str:
    """A legal, unique HDF5 key. The true name lives in the attribute."""
    key = name.replace("/", _SLASH).strip() or "signal"
    if key not in used:
        used.add(key)
        return key
    suffix = 2
    while f"{key} #{suffix}" in used:
        suffix += 1
    key = f"{key} #{suffix}"
    used.add(key)
    return key


def write_hdf5(path: str | os.PathLike, signals: Iterable[Signal], *,
               group: str | None = None,
               compression: str | None = "gzip",
               compression_level: int = 4) -> Path:
    """Write signals to an SPWB HDF5 file, atomically.

    Each signal keeps its own group when it has a ``TDMS Group`` or
    ``HDF5 Group`` attribute, so a file converted from TDMS keeps its
    structure; ``group`` overrides that for every signal.

    The file is built beside the target and renamed into place, so an
    interrupted save leaves any previous file untouched rather than
    replacing it with an unreadable one.
    """
    h5py = _require_h5py()
    from ... import __version__

    signals = list(signals)
    if not signals:
        raise ValueError("no signals to write")

    target = Path(path)
    if target.suffix == "":
        target = target.with_suffix(".h5")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")

    options: dict[str, Any] = {}
    if compression:
        options["compression"] = compression
        if compression == "gzip":
            options["compression_opts"] = int(compression_level)

    try:
        with h5py.File(str(temporary), "w") as f:
            f.attrs["spwb_format"] = _encode(FORMAT_NAME)
            f.attrs["spwb_format_version"] = _encode(FORMAT_VERSION)
            f.attrs["spwb_version"] = _encode(__version__)
            f.attrs["created"] = _encode(
                _dt.datetime.now(_dt.timezone.utc)
                .strftime("%Y-%m-%dT%H:%M:%SZ"))

            used_keys: dict[str, set[str]] = {}
            for signal in signals:
                group_name = group or signal.attributes.get(
                    "HDF5 Group", signal.attributes.get("TDMS Group",
                                                        DEFAULT_GROUP))
                group_name = str(group_name).replace("/", _SLASH)
                target_group = f.require_group(group_name)
                key = _dataset_key(signal.name,
                                   used_keys.setdefault(group_name, set()))

                data = np.asarray(signal.y, dtype=float)
                # chunking is required for compression, and a whole tiny
                # signal in one chunk is the sensible default
                dataset_options = dict(options)
                if options and data.size:
                    dataset_options["chunks"] = (min(len(data), 1 << 16),)
                dataset = target_group.create_dataset(key, data=data,
                                                      **dataset_options)

                dataset.attrs["name"] = _encode(signal.name)
                dataset.attrs["dt"] = float(signal.dt)
                dataset.attrs["t0"] = float(signal.t0)
                dataset.attrs["unit"] = _encode(signal.y_unit)
                dataset.attrs["x_unit"] = _encode(signal.x_unit)

                json_names: list[str] = []
                skipped: list[str] = []
                for attr_name, value in signal.attributes.items():
                    if attr_name in _RESERVED or attr_name == "HDF5 Group":
                        continue
                    try:
                        if isinstance(value, str):
                            dataset.attrs[attr_name] = _encode(value)
                        elif _is_native(value):
                            dataset.attrs[attr_name] = value
                        else:
                            dataset.attrs[attr_name] = _encode(
                                json.dumps(value, default=_json_default))
                            json_names.append(attr_name)
                    except (TypeError, ValueError):
                        # a value HDF5 cannot represent must not cost the
                        # user their whole save
                        skipped.append(attr_name)
                if json_names:
                    dataset.attrs[_JSON_ATTRS] = [_encode(n)
                                                  for n in json_names]
                if skipped:
                    dataset.attrs[_SKIPPED_ATTRS] = [_encode(n)
                                                     for n in skipped]
            f.flush()
        os.replace(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return target
