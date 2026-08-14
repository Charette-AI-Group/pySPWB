"""Text / CSV IO - port of SPWB's TEXT_class.

Ported from (LabVIEW block diagrams in SPWB_export/vis/File IO/TEXT_class):
  * ``Functions/READ - File.vi``      -> :func:`read_text`
  * ``Functions/WRITE - File.vi`` +
    ``Private/fWform to CSV File.vi`` -> :func:`write_text`
  * ``Functions/READ - FRF File.vi``  -> :func:`read_text_frf`
  * ``Private/CSV File to fWform.vi`` -> the reader heuristics below
  * ``Private/Find Name and Unit from String.vi`` -> :func:`split_name_unit`
  * ``Private/Find T0 and dTt.vi``    -> :func:`infer_timing`
  * ``Private/Signal Start and Length.vi`` -> :func:`find_data_start`

**There is no standard schema for signals in CSV.** RFC 4180 standardises
the syntax - quoting, line endings - and says nothing about units, sampling
interval or metadata. The signals domain does have a real interchange
standard, UFF-58, but it is fixed-width ASCII with a coded header that
Excel opens as gibberish. So "rich metadata" and "double-click into Excel"
have to be traded off, and this module makes that trade explicitly.

**The layout written here**::

    # pySPWB text export 1.0
    # signal: {"name": "Accel X", "unit": "m/s^2", "dt": 0.0001220703125, ...}
    # signal: {"name": "Mic", "unit": "Pa", "dt": 0.0001220703125, ...}
    Time [s],Accel X [m/s^2],Mic [Pa]
    0,0.02618408203125,-0.10924488306045532
    0.0001220703125,-0.006903648376464844,-0.29662212729454041

A ``#`` comment block carrying one JSON object per signal, then a plain
table. Excel and LibreOffice open it directly - the ``#`` rows land in
column A and you chart the block underneath - while SPWB reads its own
files back losslessly, because the units, ``dt`` and ``t0`` come from the
block rather than being re-derived from a rounded time column.

JSON rather than ``key=value`` because units and names contain ``;``,
``=`` and quotes, and because :mod:`spwb.processing.io.hdf5` already
encodes attributes that way.

**CSV is for interchange, not archival.** HDF5 is the lossless format
(:mod:`spwb.processing.io.hdf5`); nothing here is contorted to compete
with it.

**What the LabVIEW original did**, and where this differs. ``TEXT_class``
wrote one header row of ``Name (Unit)`` cells, an optional time column, and
9 significant digits, storing ``dt`` and ``t0`` nowhere - ``Find T0 and
dTt.vi`` re-derived them from the time column, accepting a 1% mismatch.
Both of those lose data, so this module stores the timing and defaults to
shortest round-trip formatting. Files *written* by the LabVIEW app still
read correctly: with no ``#`` block, :func:`read_text` falls back to
exactly its heuristics.
"""
from __future__ import annotations

import csv
import json
import os
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from ..model.signal import Signal
from .tdms import append_source_to_name, clean_string

__all__ = [
    "COMMENT",
    "DELIMITERS",
    "EXCEL_MAX_ROWS",
    "FORMAT_TAG",
    "LOCALES",
    "TextColumnInfo",
    "TextFRF",
    "find_data_start",
    "infer_timing",
    "read_text",
    "read_text_frf",
    "split_name_unit",
    "text_contents",
    "write_text",
]

#: marks the metadata block; also what Excel shows harmlessly in column A
COMMENT = "#"
FORMAT_TAG = "pySPWB text export 1.0"

#: Excel's hard sheet limit, minus nothing - a file longer than this simply
#: cannot be opened whole. LibreOffice Calc has the same limit.
EXCEL_MAX_ROWS = 1_048_576

#: delimiters we write, and sniff for on read
DELIMITERS: dict[str, str] = {
    "comma": ",",
    "semicolon": ";",
    "tab": "\t",
    "space": " ",
    "pipe": "|",
}

#: ready-made (delimiter, decimal) pairs. A French- or German-locale Excel
#: reads "1,5" as a number and treats "," as a decimal point, so a
#: dot-decimal file lands in a single text column - the most common reason
#: a CSV "does not open properly".
LOCALES: dict[str, tuple[str, str]] = {
    "en": (",", "."),
    "international": (",", "."),
    "fr": (";", ","),
    "de": (";", ","),
    "european": (";", ","),
}

_UNIT_OPENERS = ("(", "[", "{", "<")
#: how many rows SPWB inspects before deciding a NaN is trailing junk
_HEADER_SCAN_ROWS = 100


class TextColumnInfo:
    """One data column as listed by :func:`text_contents`."""

    __slots__ = ("channel", "dt", "group", "n_samples", "y_unit")

    def __init__(self, group: str, channel: str, n_samples: int,
                 dt: float | None, y_unit: str) -> None:
        self.group = group
        self.channel = channel
        self.n_samples = n_samples
        self.dt = dt
        self.y_unit = y_unit

    @property
    def path(self) -> str:
        """What to pass to ``read_text(select=...)`` for this column."""
        return self.channel

    @property
    def duration(self) -> float | None:
        return None if self.dt is None else self.n_samples * self.dt

    @property
    def is_waveform(self) -> bool:
        """Whether the file gave this column a sampling interval."""
        return self.dt is not None

    def __repr__(self) -> str:
        return (f"TextColumnInfo({self.channel!r}, n={self.n_samples}, "
                f"dt={self.dt!r}, unit={self.y_unit!r})")


@dataclass
class TextFRF:
    """One complex curve from a text FRF file (``READ - FRF File.vi``).

    Distinct from :class:`spwb.processing.io.pch.FRF`, which is the
    six-component Nastran shape. A text FRF is one column: complex values
    against one abscissa.
    """

    name: str = ""
    abscissa: np.ndarray = field(default_factory=lambda: np.empty(0))
    values: np.ndarray = field(default_factory=lambda: np.empty(0, complex))
    unit: str = ""
    x_unit: str = "Hz"
    source: str = ""

    @property
    def n_samples(self) -> int:
        return len(self.abscissa)

    @property
    def magnitude(self) -> np.ndarray:
        return np.abs(self.values)

    @property
    def phase(self) -> np.ndarray:
        """Phase in radians."""
        return np.angle(self.values)

    def __repr__(self) -> str:
        return (f"TextFRF({self.name!r}, n={self.n_samples}, "
                f"unit={self.unit!r})")


# -- header-cell conventions ------------------------------------------------
def split_name_unit(cell: str) -> tuple[str, str]:
    """``"Accel X (m/s^2)"`` -> ``("Accel X", "m/s^2")``.

    ``Find Name and Unit from String.vi`` offers several split styles
    because the choice is genuinely ambiguous: SPWB's own example signal is
    ``Ref Mic - Exp2010 - Gen I (N1)``, where splitting on ``-`` gives the
    wrong answer. So brackets win over dashes, and the *last* bracket group
    wins, which is what the VI's "Last Item" mode does.
    """
    text = clean_string(cell)
    if not text:
        return "", ""
    for opener in _UNIT_OPENERS:
        closer = {"(": ")", "[": "]", "{": "}", "<": ">"}[opener]
        start = text.rfind(opener)
        if start > 0 and text.endswith(closer):
            return text[:start].strip(), text[start + 1:-1].strip()
    # no brackets: fall back to the last " - " group, as the VI does
    if " - " in text:
        name, _, unit = text.rpartition(" - ")
        return name.strip(), unit.strip()
    return text, ""


def _header_cell(name: str, unit: str) -> str:
    return f"{name} [{unit}]" if unit else name


# -- reader heuristics (used only when there is no metadata block) ----------
def find_data_start(column: np.ndarray) -> tuple[int, int]:
    """``Signal Start and Length.vi``: where the numbers actually begin.

    Non-numeric cells parse to NaN. A NaN inside the first
    ``100`` rows is header text, so the signal starts after it; a NaN later
    is trailing junk and is ignored rather than treated as a new header.
    """
    finite = np.isfinite(column)
    if finite.all():
        return 0, len(column)
    start = 0
    for i, ok in enumerate(finite):
        if not ok and i < _HEADER_SCAN_ROWS:
            start = i + 1
        elif not ok:
            return start, i - start
    return start, len(column) - start


def infer_timing(x: np.ndarray, *, tolerance: float = 0.01
                 ) -> tuple[float, float, bool]:
    """``Find T0 and dTt.vi``: recover ``(t0, dt, uniform)`` from a column.

    SPWB checks ``t0 + dt*i`` against the column and accepts a 1%
    mismatch. The same tolerance is kept, but the verdict is returned
    rather than assumed, so a genuinely non-uniform abscissa can be
    reported instead of silently flattened.
    """
    if len(x) < 2:
        return (float(x[0]) if len(x) else 0.0), 0.0, False
    t0 = float(x[0])
    dt = float(x[1]) - t0
    if dt <= 0:
        return t0, dt, False
    predicted = t0 + dt * np.arange(len(x))
    span = abs(dt * len(x)) or 1.0
    return t0, dt, bool(np.max(np.abs(predicted - x)) <= tolerance * span)


# -- low-level text handling -----------------------------------------------
def _sniff(lines: list[str], delimiter: str | None,
           decimal: str | None) -> tuple[str, str]:
    """Guess the delimiter and decimal separator from the data rows."""
    body = [ln for ln in lines if ln.strip()
            and not ln.lstrip().startswith(COMMENT)]
    if delimiter is None:
        best, best_score = ",", -1.0
        for candidate in (",", ";", "\t", "|", " "):
            counts = [ln.count(candidate) for ln in body[:20]]
            if not counts or not counts[0]:
                continue
            # a real delimiter appears the same number of times on each row
            score = counts[0] if len(set(counts)) == 1 else 0
            if score > best_score:
                best, best_score = candidate, score
        delimiter = best
    if decimal is None:
        # with ";" the decimal point is very often "," - decide by looking
        sample = delimiter.join(body[:20])
        fields = [f for ln in body[:20] for f in ln.split(delimiter)]
        commas = sum(1 for f in fields if re.fullmatch(r"\s*-?\d+,\d+\s*", f))
        decimal = "," if (delimiter != "," and commas) else "."
        del sample
    return delimiter, decimal


def _to_float(text: str, decimal: str) -> float:
    text = text.strip().strip('"')
    if not text:
        return float("nan")
    if decimal != ".":
        text = text.replace(decimal, ".")
    try:
        return float(text)
    except ValueError:
        return float("nan")


def _to_complex(text: str, decimal: str) -> complex:
    """Parse ``1.5+2.3i``, ``1.5+2.3j``, ``4i``, ``-i``, or a plain real.

    Hand-rolled rather than a regex because the split between the real and
    imaginary parts is the last sign that is not an exponent's - ``1e-3i``
    is one imaginary number, ``1e-3-2i`` is two parts.
    """
    raw = text.strip().strip('"').replace(" ", "")
    if decimal != ".":
        raw = raw.replace(decimal, ".")
    if not raw:
        return complex(float("nan"))

    if raw[-1] in "ijIJ":
        body = raw[:-1]
        split = -1
        for i in range(len(body) - 1, 0, -1):
            if body[i] in "+-" and body[i - 1] not in "eE":
                split = i
                break
        real_text, imag_text = (body[:split], body[split:]) if split > 0 \
            else ("", body)
        if imag_text in ("", "+", "-"):
            imag_text += "1"
        try:
            return complex(float(real_text) if real_text else 0.0,
                           float(imag_text))
        except ValueError:
            return complex(float("nan"))
    try:
        return complex(float(raw))
    except ValueError:
        return complex(float("nan"))


def _read_lines(path: str | os.PathLike, encoding: str) -> list[str]:
    with open(path, encoding=encoding, newline="") as fh:
        return fh.read().splitlines()


def _split_rows(lines: list[str], delimiter: str) -> list[list[str]]:
    body = [ln for ln in lines if not ln.lstrip().startswith(COMMENT)]
    reader = csv.reader(body, delimiter=delimiter, skipinitialspace=True)
    return [row for row in reader if any(cell.strip() for cell in row)]


def _parse_metadata(lines: list[str]) -> tuple[dict[str, Any],
                                               list[dict[str, Any]]]:
    """Read the ``#`` block written by :func:`write_text`, if present."""
    top: dict[str, Any] = {}
    signals: list[dict[str, Any]] = []
    for line in lines:
        stripped = line.lstrip()
        if not stripped.startswith(COMMENT):
            if stripped.strip():
                break        # the block only ever sits above the table
            continue
        text = stripped.lstrip(COMMENT).strip()
        key, _, payload = text.partition(":")
        if key.strip() != "signal":
            if text.startswith(FORMAT_TAG.split()[0]):
                top["format"] = text
            continue
        try:
            signals.append(json.loads(payload))
        except json.JSONDecodeError:
            continue
    return top, signals


# -- reading ---------------------------------------------------------------
def text_contents(path: str | os.PathLike, *, delimiter: str | None = None,
                  decimal: str | None = None,
                  encoding: str = "utf-8-sig") -> list[TextColumnInfo]:
    """List the data columns a text file offers, without importing them."""
    lines = _read_lines(path, encoding)
    _top, meta = _parse_metadata(lines)
    delimiter, decimal = _sniff(lines, delimiter, decimal)
    rows = _split_rows(lines, delimiter)
    if not rows:
        return []
    grid, header = _orient(rows, decimal)
    if grid.size == 0:
        return []

    columns = [_column(grid, i) for i in range(grid.shape[1])]
    x, columns, header, _x_unit = _take_time_column(columns, header, meta,
                                                    None)
    names, units = _names_and_units(header, meta, len(columns))

    dt: float | None = None
    if meta and meta[0].get("dt"):
        dt = float(meta[0]["dt"])
    elif x is not None:
        _t0, step, uniform = infer_timing(x)
        dt = step if uniform and step > 0 else None

    return [
        TextColumnInfo(group=Path(path).stem, channel=name,
                       n_samples=len(column), dt=dt, y_unit=unit)
        for name, unit, column in zip(names, units, columns, strict=False)
    ]


def _orient(rows: list[list[str]], decimal: str
            ) -> tuple[np.ndarray, list[str]]:
    """Numeric grid (samples x signals) plus the header row above it.

    ``CSV File to fWform.vi`` notes that "for time signals, it is assumed
    that there will always be many more samples than the number of
    signals", and transposes when that does not hold - which is how a
    row-wise file is detected.
    """
    width = max(len(r) for r in rows)
    padded = [r + [""] * (width - len(r)) for r in rows]
    grid = np.array([[_to_float(c, decimal) for c in r] for r in padded])

    if grid.shape[1] > grid.shape[0]:
        grid = grid.T
        padded = [list(col) for col in zip(*padded, strict=False)]

    # the header is the last all-NaN row before the numbers start, which is
    # what "backup 1 column before the signal start" means in the VI
    first_data = 0
    for i in range(min(len(grid), _HEADER_SCAN_ROWS)):
        if np.isfinite(grid[i]).any():
            first_data = i
            break
    header = padded[first_data - 1] if first_data else [""] * grid.shape[1]
    return grid[first_data:], list(header)


def read_text(path: str | os.PathLike, *,
              select: Sequence[str | int] | None = None,
              delimiter: str | None = None,
              decimal: str | None = None,
              encoding: str = "utf-8-sig",
              dt: float | None = None,
              time_column: bool | None = None,
              decorate_names: bool = False) -> list[Signal]:
    """Read a text/CSV file into :class:`Signal` objects.

    When the file carries the ``#`` metadata block this module writes, the
    names, units, ``dt`` and ``t0`` come from it exactly. Otherwise the
    LabVIEW heuristics apply: header cells are split into name and unit,
    and the first column is treated as a time vector if it looks like one.

    Parameters
    ----------
    select:
        Columns to import, by name or 1-based index. ``None`` reads all.
    delimiter, decimal:
        Overrides for the sniffer. Pass these when a file uses the
        European convention (``;`` with a decimal comma) and detection
        guesses wrong.
    dt:
        Sampling interval to use when the file has no time column and no
        metadata block.
    time_column:
        Force the first column to be treated as the abscissa (``True``) or
        as data (``False``). ``None`` decides by checking whether it is
        monotonically increasing and evenly spaced.
    decorate_names:
        Append the source file name to each signal name.

    Raises
    ------
    ValueError
        if the file has no numeric data, or timing cannot be established.
    KeyError
        if ``select`` names a column the file does not have.
    """
    src = str(Path(path).resolve())
    lines = _read_lines(path, encoding)
    _top, meta = _parse_metadata(lines)
    delimiter, decimal = _sniff(lines, delimiter, decimal)
    rows = _split_rows(lines, delimiter)
    if not rows:
        raise ValueError(f"{src} contains no data rows")

    grid, header = _orient(rows, decimal)
    if grid.size == 0:
        raise ValueError(f"{src} contains no numeric data")

    columns = [_column(grid, i) for i in range(grid.shape[1])]
    # the abscissa has to be split off *before* the metadata block is mapped
    # onto columns: the block describes data columns only, so mapping first
    # would shift every name by one
    x, columns, header, x_unit = _take_time_column(
        columns, header, meta, time_column)
    names, units = _names_and_units(header, meta, len(columns))

    if x is not None:
        t0, step, uniform = infer_timing(x)
        if not uniform and dt is None:
            step = step or 0.0
    else:
        t0, step, uniform = 0.0, dt or 0.0, True
    if meta:
        step = float(meta[0].get("dt", step) or step)
        t0 = float(meta[0].get("t0", t0) or t0)
    if dt is not None:
        step = dt
    if not step or step <= 0:
        raise ValueError(
            f"{src} has no usable sampling interval: it carries no metadata "
            f"block and no time column to derive one from. Pass dt= to read "
            f"it as sampled data."
        )

    wanted = _resolve_selection(select, names)
    signals: list[Signal] = []
    for i, (y, name, unit) in enumerate(zip(columns, names, units,
                                            strict=False), start=1):
        if wanted is not None and i not in wanted:
            continue
        info = meta[i - 1] if len(meta) >= i else {}
        attributes: dict[str, Any] = {
            "Channel Name": name,
            "Channel Unit": unit,
            "X Axis Unit": x_unit,
            "Data Source": src,
        }
        if not uniform and x is not None:
            attributes["Non-Uniform Abscissa"] = True
        attributes.update(info.get("attributes", {}))
        sig = Signal(name=name, y=y, dt=float(info.get("dt", step) or step),
                     t0=float(info.get("t0", t0) or t0),
                     y_unit=unit, x_unit=x_unit, attributes=attributes)
        signals.append(append_source_to_name(sig) if decorate_names else sig)
    return signals


def _column(grid: np.ndarray, index: int) -> np.ndarray:
    col = grid[:, index]
    start, length = find_data_start(col)
    return col[start:start + length]


def _names_and_units(header: list[str], meta: list[dict[str, Any]],
                     count: int) -> tuple[list[str], list[str]]:
    names, units = [], []
    for i in range(count):
        if len(meta) > i:
            names.append(str(meta[i].get("name", f"Signal {i + 1}")))
            units.append(str(meta[i].get("unit", "")))
            continue
        cell = header[i] if i < len(header) else ""
        name, unit = split_name_unit(cell)
        names.append(name or f"Signal {i + 1}")
        units.append(unit)
    return names, units


def _take_time_column(columns: list[np.ndarray], header: list[str],
                      meta: list[dict[str, Any]], forced: bool | None
                      ) -> tuple[np.ndarray | None, list[np.ndarray],
                                 list[str], str]:
    """Split off the abscissa column, if the file has one.

    Returns ``(x, data_columns, data_header, x_unit)``.
    """
    if not columns or forced is False:
        return None, columns, header, "s"

    first = columns[0]
    looks_like_time = (
        len(first) > 1
        and bool(np.all(np.diff(first) > 0))
        and infer_timing(first)[2]
    )
    # a metadata block describes every *data* column, so one extra column
    # on the left can only be the abscissa - and an exact match means
    # there is none, whatever the first column looks like
    if meta:
        looks_like_time = len(columns) == len(meta) + 1

    if forced is True or looks_like_time:
        _name, unit = split_name_unit(header[0] if header else "")
        return first, columns[1:], header[1:], unit or "s"
    return None, columns, header, "s"


def _resolve_selection(select: Sequence[str | int] | None,
                       names: list[str]) -> set[int] | None:
    if select is None:
        return None
    by_name = {name: i for i, name in enumerate(names, start=1)}
    wanted: set[int] = set()
    missing: list[str | int] = []
    for item in select:
        if isinstance(item, int):
            if 1 <= item <= len(names):
                wanted.add(item)
            else:
                missing.append(item)
        elif item in by_name:
            wanted.add(by_name[item])
        else:
            missing.append(item)
    if missing:
        raise KeyError(f"column(s) not found: {missing}; the file has "
                       f"{names}")
    return wanted


def read_text_frf(path: str | os.PathLike, *,
                  delimiter: str | None = None,
                  decimal: str | None = None,
                  encoding: str = "utf-8-sig",
                  pairs: str | None = None) -> list[TextFRF]:
    """Read a text FRF file (``READ - FRF File.vi``).

    The LabVIEW VI reuses the same CSV reader but carries a **complex**
    (CDB) value per sample, so the default here is one column per curve
    with complex tokens such as ``1.5+2.3i`` or ``1.5+2.3j``. The first
    column is the abscissa.

    Parameters
    ----------
    pairs:
        For the other common export shape, where each curve occupies *two*
        real columns: ``"real-imag"`` or ``"mag-phase"`` (phase in
        degrees). ``None`` expects single complex-valued columns.

    Raises
    ------
    ValueError
        if the file has no data, or ``pairs`` is set and the column count
        is not odd (abscissa plus pairs).
    """
    src = str(Path(path).resolve())
    lines = _read_lines(path, encoding)
    delimiter, decimal = _sniff(lines, delimiter, decimal)
    rows = _split_rows(lines, delimiter)
    if not rows:
        raise ValueError(f"{src} contains no data rows")

    width = max(len(r) for r in rows)
    padded = [r + [""] * (width - len(r)) for r in rows]
    numeric = np.array([[_to_float(c, decimal) for c in r] for r in padded])
    first_data = 0
    for i in range(min(len(numeric), _HEADER_SCAN_ROWS)):
        if np.isfinite(numeric[i]).any():
            first_data = i
            break
    header = padded[first_data - 1] if first_data else [""] * width
    data = padded[first_data:]

    abscissa = np.array([_to_float(r[0], decimal) for r in data])
    x_name, x_unit = split_name_unit(header[0] if header else "")
    del x_name

    curves: list[TextFRF] = []
    if pairs:
        if (width - 1) % 2:
            raise ValueError(
                f"{src} has {width} columns; with pairs={pairs!r} it needs "
                f"an abscissa plus two columns per curve"
            )
        for col in range(1, width, 2):
            a = np.array([_to_float(r[col], decimal) for r in data])
            b = np.array([_to_float(r[col + 1], decimal) for r in data])
            values = (a + 1j * b if pairs == "real-imag"
                      else a * np.exp(1j * np.deg2rad(b)))
            name, unit = split_name_unit(header[col])
            curves.append(TextFRF(name=name or f"FRF {col // 2 + 1}",
                                  abscissa=abscissa, values=values,
                                  unit=unit, x_unit=x_unit or "Hz",
                                  source=src))
        return curves

    for col in range(1, width):
        values = np.array([_to_complex(r[col], decimal) for r in data])
        name, unit = split_name_unit(header[col])
        curves.append(TextFRF(name=name or f"FRF {col}", abscissa=abscissa,
                              values=values, unit=unit,
                              x_unit=x_unit or "Hz", source=src))
    return curves


# -- writing ---------------------------------------------------------------
def write_text(path: str | os.PathLike, signals: Iterable[Signal], *,
               delimiter: str = ",",
               decimal: str = ".",
               locale: str | None = None,
               time_column: bool = True,
               metadata: str = "block",
               precision: int | None = None,
               encoding: str = "utf-8-sig",
               line_ending: str = "\r\n",
               check_excel_limit: bool = True) -> Path:
    """Write signals to a text/CSV file (``WRITE - File.vi``).

    Parameters
    ----------
    delimiter, decimal:
        Field and decimal separators. Must differ.
    locale:
        Shorthand that sets both: ``"en"`` gives ``,`` and ``.``;
        ``"fr"``/``"de"``/``"european"`` give ``;`` and ``,``, which is
        what a French- or German-locale Excel expects. Overrides
        ``delimiter``/``decimal``.
    time_column:
        Write the abscissa as the first column (SPWB's "Inlude Time
        Vector"). Needed to chart in Excel, and harmless to read back
        because the timing is also in the metadata block.
    metadata:
        ``"block"`` writes the ``#`` header; ``"none"`` writes a bare
        table, for when the file feeds a tool that cannot skip comments.
    precision:
        Significant digits. ``None`` (default) uses Python's shortest
        round-trip representation, so a value survives write -> read
        unchanged. Note SPWB wrote 9 digits, which does **not** round-trip
        a float64 - pass ``precision=9`` to match it exactly.
    encoding:
        ``utf-8-sig`` by default: Excel on Windows needs the BOM, or units
        containing ``µ`` and ``²`` arrive as mojibake.
    check_excel_limit:
        Raise when the table would exceed Excel's and LibreOffice's
        1 048 576-row sheet limit, rather than silently writing a file
        they will truncate.

    Raises
    ------
    ValueError
        if the signals cannot share one table (different length or ``dt``),
        if the separators collide, or if the row limit would be exceeded.
    """
    if locale is not None:
        try:
            delimiter, decimal = LOCALES[locale]
        except KeyError:
            raise ValueError(
                f"unknown locale {locale!r}; known: {sorted(LOCALES)}"
            ) from None
    if delimiter == decimal:
        raise ValueError(
            f"the delimiter and the decimal separator are both {delimiter!r}; "
            f"a file like that cannot be parsed back"
        )
    if metadata not in ("block", "none"):
        raise ValueError(f"metadata must be 'block' or 'none', not "
                         f"{metadata!r}")

    signals = list(signals)
    if not signals:
        raise ValueError("no signals to write")

    lengths = {sig.n_samples for sig in signals}
    steps = {round(float(sig.dt), 15) for sig in signals}
    if len(lengths) > 1 or len(steps) > 1:
        raise ValueError(
            "a single table needs one column length and one sampling "
            f"interval, but got lengths {sorted(lengths)} and dt "
            f"{sorted(steps)}. Write these signals to separate files, or "
            f"resample them first."
        )

    n_rows = signals[0].n_samples
    total = n_rows + 1 + (len(signals) + 1 if metadata == "block" else 0)
    if check_excel_limit and total > EXCEL_MAX_ROWS:
        raise ValueError(
            f"{total} rows exceeds the {EXCEL_MAX_ROWS}-row limit of Excel "
            f"and LibreOffice, which would open this file truncated. "
            f"Decimate the signals first, or pass check_excel_limit=False "
            f"if the file is for a tool without that limit."
        )

    out = Path(path)
    fmt = None if precision is None else f"%.{precision}g"

    def number(value: float) -> str:
        text = repr(float(value)) if fmt is None else fmt % value
        return text if decimal == "." else text.replace(".", decimal)

    def row(cells: Sequence[str]) -> str:
        return delimiter.join(_quote(c, delimiter) for c in cells)

    lines: list[str] = []
    if metadata == "block":
        lines.append(f"{COMMENT} {FORMAT_TAG}")
        for sig in signals:
            lines.append(f"{COMMENT} signal: " + json.dumps(
                _describe(sig), ensure_ascii=False, sort_keys=True))

    header = [_header_cell(sig.name, sig.y_unit) for sig in signals]
    if time_column:
        header.insert(0, _header_cell(
            signals[0].attributes.get("X Axis Name", "Time"),
            signals[0].x_unit))
    lines.append(row(header))

    stack = [sig.y for sig in signals]
    if time_column:
        stack.insert(0, signals[0].t)
    table = np.column_stack(stack) if len(stack) > 1 else np.asarray(
        stack[0]).reshape(-1, 1)
    lines.extend(row([number(v) for v in record]) for record in table)

    out.write_text(line_ending.join(lines) + line_ending, encoding=encoding,
                   newline="")
    return out


def _describe(sig: Signal) -> dict[str, Any]:
    """The JSON object one ``# signal:`` line carries."""
    described: dict[str, Any] = {
        "name": sig.name,
        "unit": sig.y_unit,
        "x_unit": sig.x_unit,
        "dt": float(sig.dt),
        "t0": float(sig.t0),
        "n": int(sig.n_samples),
    }
    extra = {k: v for k, v in sig.attributes.items()
             if k not in ("Channel Name", "Channel Unit", "X Axis Unit")
             and _jsonable(v)}
    if extra:
        described["attributes"] = extra
    return described


def _jsonable(value: Any) -> bool:
    try:
        json.dumps(value)
    except (TypeError, ValueError):
        return False
    return True


def _quote(cell: str, delimiter: str) -> str:
    text = str(cell)
    if delimiter in text or '"' in text or "\n" in text:
        return '"' + text.replace('"', '""') + '"'
    return text
