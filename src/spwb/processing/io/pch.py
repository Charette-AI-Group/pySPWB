"""Nastran punch (.pch) file reading - port of SPWB's Nastran PCH_class.

Ported from (LabVIEW block diagrams in
SPWB_export/vis/File IO/Nastran PCH_class):
  * ``Functions/READ File.vi``                  -> :func:`read_pch`
  * ``Functions/Find FRF Info from File Lines.vi`` -> :func:`pch_contents`
  * ``Functions/Convert Line to Obj Data.vi``   -> :func:`_parse_block`
  * ``GUI - Nastran PCH File (V1.00).vi``       -> the :class:`FRF` fields

A punch file is the text output of a Nastran frequency-response run. It is a
run of *blocks*, each one response point, each made of a ``$``-prefixed
header followed by numeric lines::

    $TITLE   = MY MODEL
    $SUBTITLE=
    $LABEL   = RUN 3
    $SUBCASE ID =           1
    $POINT ID =           101
    $DISPLACEMENTS
    $REAL-IMAGINARY OUTPUT
     1.000000E+01       G  -1.234E-03   5.678E-04   ...
    -CONT-                  9.876E-05   ...

SPWB finds each block by scanning for ``$TITLE``, takes the ``$`` lines that
follow as the header (up to 20), and takes the numeric lines up to the next
``$`` as the data.

**Three output flavours, and how many lines each costs per frequency**

============================  =====  =============================
``$REAL OUTPUT``                2    real only, imaginary part 0
``$REAL-IMAGINARY OUTPUT``      4    re/im interleaved by line pair
``$MAGNITUDE-PHASE OUTPUT``     4    magnitudes then phases, degrees
============================  =====  =============================

Anything else is treated as magnitude-phase, which is what the LabVIEW case
structure does with its default frame.

Each frequency yields six complex values - three translations
(:attr:`FRF.x`, :attr:`FRF.y`, :attr:`FRF.z`) and three rotations
(:attr:`FRF.u`, :attr:`FRF.v`, :attr:`FRF.w`) - so an :class:`FRF` is
returned rather than a :class:`~spwb.processing.model.signal.Signal`:
the data is complex, indexed by frequency, and six-component. That is
exactly what ``READ File.vi`` hands back.

Writing punch files is deliberately not implemented; this module reads only.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

__all__ = [
    "FRF",
    "LINES_PER_SAMPLE",
    "UNIT_TYPES",
    "PCHBlockInfo",
    "pch_contents",
    "read_pch",
]

#: ``$<keyword>`` prefix -> (unit type, default unit), from the LabVIEW
#: case structure. ``$DISPLACE`` is its default frame.
UNIT_TYPES: dict[str, tuple[str, str]] = {
    "$DISPLACE": ("displacement", "mm"),
    "$VELOCITY": ("velocity", "mm/s"),
    "$ACCELERA": ("acceleration", "m/s^2"),
}
_UNIT_KEY_LEN = 9  # every key above is 9 characters, as the VI assumes

#: output flavour -> lines of text per frequency point
LINES_PER_SAMPLE: dict[str, int] = {
    "$REAL OUTPUT": 2,
    "$REAL-IMAGINARY OUTPUT": 4,
    "$MAGNITUDE-PHASE OUTPUT": 4,
}
_DEFAULT_OUTPUT = "$MAGNITUDE-PHASE OUTPUT"

#: how many header lines the LabVIEW loop will look at
MAX_HEADER_LINES = 20

_TITLE = "$TITLE"
_NUMBER = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[EeDd][-+]?\d+)?")
_TRAILING_ID = re.compile(r"=\s*(-?\d+)")


@dataclass
class PCHBlockInfo:
    """Where one response block sits in the file (``Find FRF Info...``)."""

    header_start: int
    data_start: int
    header_length: int
    data_length: int

    @property
    def data_end(self) -> int:
        return self.data_start + self.data_length


@dataclass
class FRF:
    """One frequency response: six complex components over one abscissa."""

    title: str = ""
    sub_title: str = ""
    name: str = ""
    point_id: int = 0
    subcase_id: int = 0
    unit_type: str = "displacement"
    unit: str = "mm"
    storage_type: str = "Sort1"
    output_type: str = _DEFAULT_OUTPUT
    abscissa: np.ndarray = field(default_factory=lambda: np.empty(0))
    x: np.ndarray = field(default_factory=lambda: np.empty(0, complex))
    y: np.ndarray = field(default_factory=lambda: np.empty(0, complex))
    z: np.ndarray = field(default_factory=lambda: np.empty(0, complex))
    u: np.ndarray = field(default_factory=lambda: np.empty(0, complex))
    v: np.ndarray = field(default_factory=lambda: np.empty(0, complex))
    w: np.ndarray = field(default_factory=lambda: np.empty(0, complex))
    source: str = ""

    @property
    def n_samples(self) -> int:
        return len(self.abscissa)

    @property
    def components(self) -> dict[str, np.ndarray]:
        """The six components by name, translations first."""
        return {"x": self.x, "y": self.y, "z": self.z,
                "u": self.u, "v": self.v, "w": self.w}

    def __repr__(self) -> str:
        return (f"FRF({self.name!r}, point={self.point_id}, "
                f"subcase={self.subcase_id}, n={self.n_samples}, "
                f"{self.unit_type} [{self.unit}])")


def _read_lines(path: str | os.PathLike) -> list[str]:
    with open(path, encoding="latin-1", newline="") as fh:
        return fh.read().splitlines()


def pch_contents(path: str | os.PathLike) -> list[PCHBlockInfo]:
    """Locate every response block in a punch file.

    Blocks are found the way ``Find FRF Info from File Lines.vi`` finds
    them: scan for a line containing ``$TITLE``, take the ``$`` lines that
    follow as the header, then the non-``$`` lines as the data.
    """
    return _find_blocks(_read_lines(path))


def _find_blocks(lines: list[str]) -> list[PCHBlockInfo]:
    blocks: list[PCHBlockInfo] = []
    i, n = 0, len(lines)
    while i < n:
        if _TITLE not in lines[i]:
            i += 1
            continue
        header_start = i
        j = i
        while (j < n and j - header_start < MAX_HEADER_LINES
               and "$" in lines[j]):
            j += 1
        header_length = j - header_start
        data_start = j
        while j < n and "$" not in lines[j]:
            j += 1
        end = j
        while end > data_start and not lines[end - 1].strip():
            end -= 1  # a blank tail is not data, and would break the pairing
        blocks.append(PCHBlockInfo(header_start, data_start, header_length,
                                   end - data_start))
        i = max(j, header_start + 1)
    return blocks


def read_pch(path: str | os.PathLike) -> list[FRF]:
    """Read every frequency response in a Nastran punch file.

    Raises
    ------
    ValueError
        if the file holds no ``$TITLE`` block, or a block's data lines do
        not divide evenly into frequency points.
    """
    src = str(Path(path).resolve())
    lines = _read_lines(path)
    blocks = _find_blocks(lines)
    if not blocks:
        raise ValueError(
            f"{src} contains no '{_TITLE}' line, so it is not a Nastran "
            f"punch file SPWB can read"
        )
    return [_parse_block(lines, block, src) for block in blocks]


def _find_header(header: list[str], keyword: str) -> str | None:
    """The first header line starting with ``keyword``, if any.

    The LabVIEW VI indexes fixed offsets from ``$TITLE`` instead - line 4 is
    ``$POINT ID``, line 5 the unit type, and so on. Real punch files put
    ``$SUBCASE ID`` / ``$POINT ID`` before *or* after the type lines
    depending on the Nastran version, so this searches the header block
    rather than counting lines. Files the LabVIEW app read give the same
    answer; files it mis-parsed now read correctly.
    """
    for line in header:
        if line.strip().upper().startswith(keyword):
            return line
    return None


def _strip_keyword(line: str | None, keyword: str) -> str:
    """``$TITLE   = MY MODEL`` -> ``MY MODEL`` (``Get Title - SubTitle``)."""
    if line is None:
        return ""
    return line.strip().replace(keyword, "").replace("=", "").strip()


def _trailing_id(line: str | None) -> int:
    if line is None:
        return 0
    match = _TRAILING_ID.search(line)
    return int(match.group(1)) if match else 0


def _parse_block(lines: list[str], block: PCHBlockInfo, src: str) -> FRF:
    """``Convert Line to Obj Data.vi`` for one block."""
    header = lines[block.header_start:block.data_start]

    title = _strip_keyword(_find_header(header, "$TITLE"), "$TITLE")
    sub_title = _strip_keyword(_find_header(header, "$SUBTITLE"), "$SUBTITLE")
    label = _strip_keyword(_find_header(header, "$LABEL"), "$LABEL")
    subcase_id = _trailing_id(_find_header(header, "$SUBCASE ID"))

    point_line = _find_header(header, "$POINT ID")
    if point_line is not None:
        # SORT2: one point, every frequency. The point number goes into the
        # name because it is the only thing distinguishing two blocks.
        storage_type = "Sort2"
        point_id = _trailing_id(point_line)
        name = f"{label} (PID {point_id})" if label else f"PID {point_id}"
    else:
        storage_type = "Sort1"
        point_id = 0
        name = label

    unit_type, unit = UNIT_TYPES["$DISPLACE"]
    for line in header:
        key = line.strip().upper()[:_UNIT_KEY_LEN]
        if key in UNIT_TYPES:
            unit_type, unit = UNIT_TYPES[key]
            break

    output_type = _DEFAULT_OUTPUT
    for line in header:
        if line.strip().upper() in LINES_PER_SAMPLE:
            output_type = line.strip().upper()
            break
    per_sample = LINES_PER_SAMPLE[output_type]

    data = lines[block.data_start:block.data_end]
    n_samples = len(data) // per_sample
    if n_samples * per_sample != len(data):
        raise ValueError(
            f"{src}: the block starting at line {block.header_start + 1} "
            f"declares {output_type} ({per_sample} lines per frequency) but "
            f"has {len(data)} data lines, which is not a whole number of "
            f"frequency points"
        )

    frf = FRF(title=title, sub_title=sub_title, name=name, point_id=point_id,
              subcase_id=subcase_id, unit_type=unit_type, unit=unit,
              storage_type=storage_type, output_type=output_type, source=src)
    _fill(frf, data, n_samples, per_sample, src, block)
    return frf


def _numbers(line: str) -> list[float]:
    """Every number on a line, tolerating Fortran ``1.0D+00`` exponents."""
    return [float(m.group(0).replace("D", "E").replace("d", "e"))
            for m in _NUMBER.finditer(line)]


def _row(line: str, count: int, src: str, line_no: int) -> list[float]:
    """The first ``count`` numbers on a line, in the order LabVIEW scans."""
    values = _numbers(line)
    if len(values) < count:
        raise ValueError(
            f"{src}: line {line_no} has {len(values)} numbers, expected "
            f"at least {count}: {line.strip()!r}"
        )
    return values[:count]


def _fill(frf: FRF, data: list[str], n_samples: int, per_sample: int,
          src: str, block: PCHBlockInfo) -> None:
    abscissa = np.empty(n_samples)
    parts = np.empty((6, n_samples), dtype=complex)

    for i in range(n_samples):
        base = i * per_sample
        line_no = block.data_start + base + 1
        # the first line of a point carries the abscissa, then 3 values
        first = _row(data[base], 4, src, line_no)
        abscissa[i] = first[0]
        head, tail = first[1:], _row(data[base + 1], 3, src, line_no + 1)

        if per_sample == 2:  # $REAL OUTPUT - no imaginary part at all
            parts[:, i] = np.array(head + tail, dtype=complex)
            continue

        third = _row(data[base + 2], 3, src, line_no + 2)
        fourth = _row(data[base + 3], 3, src, line_no + 3)
        if frf.output_type == "$REAL-IMAGINARY OUTPUT":
            # lines 1,2 are the real parts; lines 3,4 the imaginary parts
            real = head + tail
            imag = third + fourth
            parts[:, i] = np.array(real) + 1j * np.array(imag)
        else:  # magnitude/phase, phase in degrees
            magnitude = np.array(head + tail)
            phase = np.deg2rad(np.array(third + fourth))
            parts[:, i] = magnitude * np.exp(1j * phase)

    frf.abscissa = abscissa
    frf.x, frf.y, frf.z, frf.u, frf.v, frf.w = parts
