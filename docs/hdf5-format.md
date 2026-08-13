# The SPWB HDF5 format

SPWB's native file format is plain [HDF5](https://www.hdfgroup.org/). No
part of it is SPWB-specific machinery: any tool that reads HDF5 — MATLAB,
Julia, R, C++, HDFView, `h5dump`, or five lines of `h5py` — can read an
SPWB file without SPWB, and without this document. The document exists so
the *meaning* of what is in there is unambiguous.

Format version: **1.0**

## Layout

```
/                                     root
    @spwb_format          "SPWB-HDF5"
    @spwb_format_version  "1.0"
    @spwb_version         e.g. "0.1.0"     (the writer's version)
    @created              ISO-8601 UTC     e.g. "2026-08-13T04:15:00Z"

/<group>/                             one per signal group
/<group>/<channel>                    1-D float64 dataset, one per signal
    @name        str    the signal's name (authoritative - see Naming)
    @dt          f8     sample interval, seconds
    @t0          f8     time of the first sample, seconds
    @unit        str    engineering unit of the samples ("Pa", "m/s^2", ...)
    @x_unit      str    unit of the abscissa ("s", "Hz", ...)
    ...                 every other SPWB attribute, see Attributes
```

A file with no grouping information puts everything in a group named
`SPWB`. Signals that carry a `TDMS Group` attribute keep that group name,
so a TDMS file converted to HDF5 keeps its structure.

## Reading one without SPWB

```python
import h5py
with h5py.File("run.h5") as f:
    for group in f.values():
        for ds in group.values():
            y  = ds[:]                       # the samples
            fs = 1.0 / ds.attrs["dt"]        # sample rate, Hz
            unit = ds.attrs["unit"].decode() # strings are UTF-8 bytes
```

```matlab
% MATLAB
y  = h5read('run.h5', '/SPWB/Accel X');
dt = h5readatt('run.h5', '/SPWB/Accel X', 'dt');
```

## Strings

All string attributes are **fixed-length UTF-8 bytes** (HDF5 `|S*`), not
variable-length strings. Variable-length strings are the h5py default and
are what most Python code writes, but older MATLAB releases and some C
readers handle them poorly. Fixed-length bytes are read correctly
everywhere; the cost is that consumers must `.decode()` them, which the
snippets above show.

## Naming

HDF5 uses `/` as a path separator, so a signal called `Left/Right` cannot
be a dataset name. SPWB therefore:

* replaces `/` with `∕` (U+2215 DIVISION SLASH) in the **dataset key**;
* appends ` #2`, ` #3`, … to the key when two signals share a name;
* always stores the true, original name in the `name` attribute.

The `name` attribute is authoritative. The dataset key is a convenience
for browsing and may have been altered to be a legal, unique HDF5 name.

## Attributes

Every entry of a signal's SPWB attribute dictionary is written as an HDF5
attribute, so provenance survives a round trip: which window produced a
spectrum, which file the data came from, the calibration applied, and so
on.

Values that HDF5 stores natively (numbers, booleans, strings, arrays,
complex arrays) are written as themselves. Anything else — nested
dictionaries such as the raw TDMS property block, lists of mixed type — is
JSON-encoded, and the names of those attributes are listed in the
dataset's `_spwb_json_attrs` attribute so a reader knows to decode them.
Attributes that cannot be represented at all are skipped rather than
failing the save; their names are listed in `_spwb_skipped_attrs`.

## Compression

Datasets are chunked and gzip-compressed by default (level 4). This is
transparent: any HDF5 reader decompresses automatically. Compression can
be turned off when write speed matters more than size.

## Writing safely

SPWB writes to a temporary file in the destination directory, flushes it,
and then atomically renames it over the target. A crash mid-write
therefore leaves the previous file intact rather than a half-written,
unreadable one — HDF5's one notable fragility.
