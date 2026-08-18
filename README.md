# pySPWB

[![tests](https://github.com/Charette-AI-Group/pySPWB/actions/workflows/tests.yml/badge.svg)](https://github.com/Charette-AI-Group/pySPWB/actions/workflows/tests.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/Charette-AI-Group/pySPWB/blob/main/LICENSE)
[![python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org)

A **DSP library and desktop application** for measurement work: spectra,
transfer functions, coherence, spectrograms and adaptive filtering.

It is two things, and you can use either without the other:

* a **signal-processing library** — spectra, transfer functions, coherence,
  spectrograms, adaptive filtering, HDF5/TDMS/WAV/CSV IO plus read-only
  RPC-III, Nastran punch and HEAD acoustics — that runs happily in a
  notebook;
* a **desktop application** built on it, with multi-window signal sharing:
  send the same signals to an FFT, a transfer function and a spectrogram at
  once, and they stay in step.

```bash
pip install spwb          # the library: numpy + scipy, no GUI stack
pip install spwb[gui]     # the full application, then run:  spwb
```

### No Python on the machine? Download the application

The desktop application is also published as a **standalone build** that
carries its own Python, so nothing has to be installed to run it — the
successor to the compiled builds the
[original LabVIEW SPWB](https://github.com/Charette-AI-Group/SPWB) shipped
for people without LabVIEW.

| | |
|---|---|
| **Windows** | `SPWB-windows-x64.zip` — unzip, run `SPWB.exe` |
| **macOS** (Apple Silicon) | `SPWB-macos-apple-silicon.zip` |
| **macOS** (Intel) | `SPWB-macos-intel.zip` |

Get them from the [**latest release**](https://github.com/Charette-AI-Group/pySPWB/releases/latest).
Unzip the whole folder and keep it together — the executable needs the files
beside it. Each release also carries `SPWB-checksums.txt`.

The builds are **not code-signed**, so the first launch needs one extra step:
Windows SmartScreen shows *More info → Run anyway*, and macOS refuses until
you right-click the app and choose **Open** once (or run
`xattr -cr /path/to/SPWB.app`). Signing certificates cost money yearly; the
checksums are there so a download can be verified without them.

There is no Linux build: a bundle is tied to the glibc of the machine that
made it, and `pip install spwb[gui]` works well on Linux.

Its native file format is plain **HDF5**, so a measurement saved here opens
in MATLAB, Julia, R or HDFView without SPWB installed —
see [`docs/hdf5-format.md`](https://github.com/Charette-AI-Group/pySPWB/blob/main/docs/hdf5-format.md).

There is a [**user manual**](https://github.com/Charette-AI-Group/pySPWB/tree/main/docs/manuals) for every analysis window, each
working through demonstration datasets you can create from the File menu,
with a companion notebook that computes the same numbers in a few lines.

**The numbers are not approximations.** They are pinned to reference data
committed in `tests/fixtures/`, so a spectrum here is the spectrum an
instrument-grade implementation produces — see
[Numerical fidelity](#numerical-fidelity).

## Layout: processing and GUI are strictly separated

```
src/spwb/
├── processing/        the complete Qt-free side — use it in notebooks
│   ├── model/         Signal (wForm + attributes), SignalStore
│   ├── dsp/           windows, spectra, transfer functions, metrics
│   └── io/            file formats (HDF5, TDMS, WAV, CSV; read-only:
│                      RPC-III, Nastran punch, HEAD acoustics)
├── app_config.py      names, credits, links, brand colours, paths — Qt-free
├── resources/         bundled files (icon); ships in the wheel
└── gui/               the PySide6 application — the ONLY package that
                       may import Qt; a pure client of processing/
```

The boundary is a tested contract, not a convention:
`tests/test_separation.py` imports every `spwb.processing` module in a
clean subprocess and fails if Qt gets loaded, greps the processing sources
for Qt references, and runs a full notebook-style analysis with the Qt
stack made unimportable. A notebook user does `pip install spwb` and never
sees, needs, or pays for the GUI; `pip install spwb[gui]` adds it.

```python
# notebook usage — no GUI, no Qt
from spwb.processing import Signal
from spwb.processing.io import read_tdms
from spwb.processing.dsp import auto_power_spectrums

signals = read_tdms("run.tdms")     # or read_hdf5("run.h5") / read_wave(...)
spectrum = auto_power_spectrums(signals[0], freq_resolution=1.0, window="hanning")

# ... and everything the FFT window's controls do is available here too
from spwb.processing.dsp import band_rms, format_spectrum

dba = format_spectrum(spectrum,
                      function_type="Auto Spectrum - (EU RMS)",
                      display_option="dB - Sound SPL (ref 20E-6 Pa)",
                      weighting="A-weighting")
level = band_rms(spectrum, 100.0, 400.0)     # RMS in the 100-400 Hz band

# frequency response + coherence between an input and an output channel
from spwb.processing.dsp import transfer_function

tf, coherence = transfer_function(signals[0], signals[1],
                                  freq_resolution=1.0, overlap=0.5,
                                  estimator="H1")
H = tf.attributes["TF_Complex"]              # complex FRF, for curve fitting

# spectrogram, with axes ready for your own plotting
from spwb.processing.dsp import stft_spectrogram

spec = stft_spectrogram(signals[0], block_size=1024).to_db(dynamic_range=70)
plt.pcolormesh(spec.times, spec.freqs, spec.data.T)
ridge = spec.freqs[spec.data.argmax(axis=1)]  # dominant frequency vs time
```

## What is done

| Layer | State |
|---|---|
| `processing.model` — `Signal` (wForm + attributes), `SignalStore` (multi-window sharing) | ✅ done |
| `processing.dsp.windows` — all 19 SPWB windows, NI-exact (periodic, amplitude-preserving scaling, ENBW/CG) | ✅ validated vs LabVIEW 2022 |
| `processing.dsp.spectral` — auto power spectrum, block averaging w/ overlap, all 8 spectral function types, 7 dB display options, A-weighting, band power | ✅ validated vs LabVIEW 2022 |
| `processing.io.tdms` — read/write TDMS, NI waveform properties, SPWB attribute + naming conventions | ✅ round-trip tested; LabVIEW reads our files |
| `gui` — Time Processing hub window: signal list, plot, TDMS open/save, generators, **multi-instance signal sharing** | ✅ runs |
| `processing.dsp.transfer` — cross spectra, H1/H2/H3, coherence, all 6 TF display types | ✅ validated vs LabVIEW 2022 |
| `gui` — FFT Analysis window: spectra, all display options, Energy Band, log axes, clipboard export | ✅ runs |
| `gui` — Transfer Function window: reference/response roles, every combination, magnitude/phase/coherence | ✅ runs |
| `processing.dsp.timefreq` — STFT spectrogram, cross sections, dB scaling | ✅ validated vs LabVIEW 2022 |
| `gui` — Time-Frequency window: spectrogram, cursor-driven Time/Frequency sections, colour tables | ✅ runs |
| `processing.io.wave` — WAV read/write, filename scale convention, all 4 save options | ✅ round-trip tested; LabVIEW reads our files bit-exactly |
| `processing.dsp.metrics` — statistics and the 7 sliding-window trend types | ✅ validated vs LabVIEW 2022 |
| `processing.dsp.conditioning` — calibrate, offset, normalise, truncate, resample | ✅ done |
| `gui` — Time Processing analysis tabs: Scale Signals, Stats, TV Metrics | ✅ runs |
| `processing.io.hdf5` — **the native format**: open HDF5, documented schema, atomic writes | ✅ round-trip tested |
| `processing.dsp.adaptive` — LMS / NLMS adaptive noise cancellation, convergence metric | ✅ done |
| `gui` — Adaptive Filtering window: reference/noisy roles, convergence trace, learned filter | ✅ runs |
| `processing.io.rpc` — **read** MTS RPC-III (`.rsp`): header keywords, group de-interleaving, per-channel scaling | ✅ read-only, tested against a byte-level fixture |
| `processing.io.pch` — **read** Nastran punch (`.pch`): block detection, all 3 output flavours, 6 complex components | ✅ read-only, tested |
| `processing.io.head_hdf` — **read** HEAD acoustics (`.hdf`): native parser, no DataPlugin, any platform | ✅ read-only; verified against 4 real ArtemiS recordings |
| `gui` — RPC-III and HEAD acoustics import in the Time Processing window | ✅ runs |
| `processing.io.text` — text/CSV read **and** write, Excel-facing schema, locale separators, text FRF reader | ✅ round-trips exactly |
| `gui` — Text/CSV open and save in the Time Processing window | ✅ runs |
| `gui.plotting` — LabVIEW-style graph palette on every plot: pan, rect / X / Y zoom, fit, undo | ✅ runs |
| `gui.settings` — remembers browse folders per file type and operation, plus window geometry, splitters and column layout | ✅ runs |
| `gui.flow_layout` — wrapping control rows, so the window fits a laptop screen | ✅ runs |
| `gui.about` — About dialog matching the sibling Charette AI Group apps, with Donate | ✅ runs |
| `app_config` — one home for names, credits, links, colours and resource paths | ✅ runs |

## Numerical fidelity

SPWB began as a LabVIEW application, and the numerics were never
re-derived from textbooks - they are pinned to it. That original is
archived, MIT-licensed, and kept for reference at
[Charette-AI-Group/SPWB](https://github.com/Charette-AI-Group/SPWB); if you
have measurements from it, they still come out the same here.

`tests/fixtures/*.npz` hold ground-truth data generated by driving
**LabVIEW 2022 itself** over COM (see `tools/`): NI's
`Auto Power Spectrum.vi` and `Scaled Time Domain Window (DBL).vi` were called
with known inputs and their outputs frozen. The pytest suite reproduces them
to ~1e-7 relative or better (limited only by NI's tabulated window-constant
rounding, documented in `tests/test_windows.py`).

Port notes discovered on the way:

* NI window codes are non-sequential: `0-9`, `11` (Blackman-Nuttall!),
  `30-34` (triangle…welch), `60-62` (Kaiser, Dolph-Chebyshev, Gaussian).
* NI "scaled" windows are amplitude-preserving: `x·w/CG`, `CG = mean(w)`.
* NI's Gaussian is symmetric over `n+1` points truncated to `n`, with
  `σ = std·(n+1)`; its Parzen is the piecewise cubic on `|i−n/2|/(n/2)`.
* NI's flat-top coefficients differ from scipy's in the 8th decimal
  (exact values recovered by least-squares fit and used here).
* SPWB's spectra append a copy of the last bin so plots span 0 Hz…Fs/2
  inclusive.
* The `Spectral Function Type` / `Spectrum Display Options` /
  `Acoustic Weighting` strings are recovered verbatim from the `.ctl` files,
  so the Python enums read identically to the LabVIEW rings.
* A-weighting enters in the domain of the quantity it weights, as
  `Acoustic Weighting.vi` does: added directly in dB, `10^(A/20)` on
  amplitudes, `10^(A/10)` on power.
* Band power divides the summed spectrum by the window's ENBW — without it
  a band RMS reads high by `sqrt(ENBW)` (√1.5 ≈ 1.22 for Hanning) and
  depends on which window you picked.
* NI's cross spectrum is `2·conj(X)·Y/N²` with the DC **and Nyquist** bins
  left undoubled; `Cross Power Spectrum.vi` returns `N/2+1` bins while
  `Auto Power Spectrum.vi` returns `N/2`, so the TF path truncates to the
  shorter to keep Sxy/Sxx/Syy aligned (LabVIEW's array arithmetic did the
  same thing implicitly).
* Transfer functions average the **complex** Sxy, Sxx and Syy across blocks
  and only then divide — the original diagram carries this as two
  hand-written warnings. Averaging per-block `H`, or averaging `|Sxy|`,
  silently pins coherence at 1 and destroys H1's noise rejection.
* The trend metrics inherit **two disagreeing normalisations** from NI:
  `Moment about Mean.vi` divides by `N`, while `Std Deviation and
  Variance.vi` divides by `N-1`. So Variance and Standard Deviation are the
  sample forms, but Skewness (`m3/σ³`) and Kurtosis (`m4/σ⁴`) mix a
  population moment with a sample sigma. Kurtosis is not *excess* kurtosis
  — a Gaussian reads ≈ 3, not 0.
* NI's STFT spectrogram is **not** `scipy.signal.spectrogram`'s default:
  frames are centre-aligned (the signal is pre-padded by `nfft//2`), its
  "time steps" input is the **hop in samples** rather than a frame count,
  it returns `nfft//2` bins without the factor-2 single-sided doubling, and
  each bin is `|FFT(w·x)|² / (Σw² · nfft)` — a power quantity where a sine
  of amplitude A through a rectangular window peaks at `A²/4`.

### HDF5 — the native format

The Python port stores data as plain **HDF5** rather than TDMS. TDMS was
the right default for a LabVIEW application; for an open-source Python one,
HDF5 is an open standard with the same data model (file → groups →
channels, attributes at every level) that MATLAB, Julia, R, C++ and
HDFView read natively. The layout is written down in
[`docs/hdf5-format.md`](https://github.com/Charette-AI-Group/pySPWB/blob/main/docs/hdf5-format.md) so the files stay meaningful
without this project.

Three choices are load-bearing and easy to undo by accident:

* **strings are fixed-length UTF-8 bytes**, not h5py's default
  variable-length strings, which older MATLAB and some C readers handle
  poorly. A test asserts the on-disk dtype, since the difference is
  invisible from Python;
* **writes are atomic** — a temporary file, then a rename — because a
  process killed mid-write is the one way to make an HDF5 file unreadable.
  A test kills the rename and checks the previous file survives intact;
* **the `name` attribute is authoritative**, not the dataset key: HDF5
  keys cannot contain `/` and must be unique, so `Left/Right` and repeated
  names are stored under adjusted keys with the real name alongside.

Attributes that HDF5 cannot hold natively (the raw TDMS property block,
say) are JSON-encoded and listed in `_spwb_json_attrs`. Values it cannot
represent at all are **skipped and listed**, not stringified — a blanket
`str()` would happily store `"<function <lambda> at 0x7f…>"`, a memory
address masquerading as data.

Note that SPWB's `.hdf` reader for **HEAD acoustics** files
(`spwb.processing.io.head_hdf`) handles a different, proprietary format
that merely shares three letters of the extension; the native format is
`.h5`. See [Read-only formats](#read-only-formats-rpc-iii-nastran-punch-head-acoustics).

### TDMS

Byte-level TDMS parsing is delegated to [`nptdms`](https://nptdms.readthedocs.io);
`spwb.processing.io.tdms` is the mapping layer (NI waveform properties ↔
`Signal`) and is what the tests cover. Two independent checks:

* **round trip** — write → read reproduces samples, `dt`, `t0`, units and group;
* **NI cross-check** — `tools/verify_labview_reads_spwb_tdms.py` writes a TDMS
  with `spwb`, has **LabVIEW 2022 itself** convert it to TDM, and confirms the
  channels, groups, units, `wf_increment` and `wf_start_offset` all survive.
  Last run: PASS.

### WAV

A WAV file has no units field and its samples are bounded to ±1, so SPWB
normalises on write and records the factor it applied **in the file name**:

```
Accel X_scale_9.81_m-per-s2.wav
        ^^^^^ ^^^^  ^^^^^^^^^^
        keyword     unit (optional)
              factor
```

Reading multiplies the ±1 samples back by that factor, so engineering units
survive a round trip. Files without the keyword read as raw ±1 data, which
is what a WAV from any other tool means. The name is split on underscores
and matched case-insensitively, as `Find scale factor from file name.vi`
does; `Multi Signals Save Option.ctl`'s four modes (per-signal,
concatenate, stereo, stereo-swapped) are all supported.

`tools/verify_labview_reads_spwb_wav.py` writes a WAV with `spwb` and has
LabVIEW's own `Snd Read Wave File.vi` read it back: **sample data matches
bit-exactly** (max difference 0.000e+00), and the channel count, bit depth
and rate all decode correctly. Last run: PASS.

That check also turned up a limitation *of the original LabVIEW path*:
`Snd Read Wave File.vi` reports the sample rate as an index into
`{11025, 22050, 44100, 8000}` Hz. A file at 48 kHz or 51.2 kHz reads its
samples correctly but is reported as 11025 Hz. This port reads the true
rate from the file header, so it does not share the bug — but be aware
that WAVs written here at non-classic rates will be mislabelled if opened
in the old LabVIEW application.

SPWB's own file-IO VIs could *not* be driven over COM for fixtures — they
require a LabVIEW queue refnum (`State Queue`), which does not marshal. The
conventions were therefore read off the exported block diagrams:
`Channel Name` / `Channel Unit` / `X Axis Unit` / `Data Source` attributes,
double-space collapsing on names and units, and the
`"name (source file.tdms)"` decoration from
`WF - Append Src Name to Sig Name.vi`.

### Read-only formats: RPC-III, Nastran punch, HEAD acoustics

SPWB imports three foreign formats it never wrote back, and so does this
port — there are no writers for them, deliberately. All three need nothing
beyond numpy: no plugins, no vendor runtimes, no Windows.

**MTS RPC-III (`.rsp`)** is fully implemented from the format itself. Its
header is 128-byte keyword/value records grouped into 512-byte blocks, and
its data is `int16` little-endian *demultiplexed by group*: all of channel
1's `PTS_PER_GROUP` samples, then all of channel 2's, then the next group.
Getting that interleaving wrong produces plausible-looking garbage, so
`tests/test_rpc.py` builds the bytes by hand and asserts the values come
back in the right order and scaled by `SCALE.CHAN_n`.

Two behaviours are inherited from LabVIEW on purpose:

* **keyword lookup is by prefix.** `Extract value using keyword.vi`
  compares only the first `len(keyword)` characters, which is why SPWB
  asks for `DELTA` and finds `DELTA_T`. Real files disagree about keyword
  suffixes, so this is kept.
* **the padded last group is kept.** A recording of 2.5 groups is stored as
  3, and LabVIEW returns all of it. `read_rpc(..., trim_padding=True)` cuts
  it back to `FRAMES × PTS_PER_FRAME` if you would rather not see the
  trailing zeros.

**Nastran punch (`.pch`)** returns `FRF` objects rather than `Signal`s,
because the data is complex, indexed by frequency, and has six components
(three translations, three rotations) — which is exactly what
`READ File.vi` hands back. The three output flavours differ in how many
lines a frequency point costs and how the numbers combine, and each is
pinned by a hand-computed test:

| header line | lines/point | combination |
|---|---|---|
| `$REAL OUTPUT` | 2 | real only, imaginary part 0 |
| `$REAL-IMAGINARY OUTPUT` | 4 | lines 1–2 real, lines 3–4 imaginary |
| `$MAGNITUDE-PHASE OUTPUT` | 4 | lines 1–2 magnitude, 3–4 phase in degrees |

One **deliberate difference from LabVIEW**: `Convert Line to Obj Data.vi`
indexes fixed offsets from `$TITLE` (line 4 is `$POINT ID`, line 5 the unit
type, …). Real punch files put `$SUBCASE ID` / `$POINT ID` before *or*
after the type lines depending on the Nastran version, so this port
searches the header block by keyword instead. Files the LabVIEW app read
give the same answer; files it mis-parsed now read correctly.

**HEAD acoustics (`.hdf`)** is parsed directly, and needs no plugin. The
LabVIEW class did not parse it: `READ - File.vi` opens the file through
NI's *Universal Storage Interface* with HEAD acoustics' `HEAD_Data_Format`
DataPlugin — a Windows-only install most people do not have. That turns out
to be unnecessary. The container is self-describing and its header is plain
ASCII, so reading it takes nothing but numpy, on any platform:

```
;
; Copyright 1999 HEAD acoustics GmbH, Germany
;
byte order:                        Intel
kind:                              Time data
start of data:                     65536          <- payload offset
nbr of channel:                    1
abscissa definition:               1              <- opens a block
delta value:                       0.000122070313
nbr of scans:                      245760
channel definition:                1              <- opens a block
physical unit:                     Pa
implementation type:               FLOAT32
```

`key: value` lines padded to `start of data` with tabs, then raw samples.
Keys repeat, so the header is **block structured** — `name str` appears
once per block and means something different each time. Lines starting `;`
are comments, and `;#key: value` is a *disabled* field, which is how
optional metadata such as the recording date is carried.

Two things that look like traps and are not:

* **`calibration` is not a gain.** A sample file carries `calibration: 94`
  on a pressure channel whose samples are already in Pa and peak at exactly
  1.0 — 94 dB is just the calibrator level (1 Pa RMS re 20 µPa). Another
  carries `calibration: -10` on an accelerometer, which as a multiplier
  would invert the measurement. It is kept as an attribute, not applied.
* **`delta value` is rounded to nine significant figures**, so `1/8192` is
  stored as `0.000122070313`. The header value is used as-is, because it is
  what the file says and what every other reader will use.

Verified against four ArtemiS recordings (`Sine 1kHz`, `SineSweep 20 to
320Hz`, `Random`, and a measured accelerometer channel). The 1 kHz sine is
the decisive one: least-squares fitting a 1 kHz sine to all 245 760 samples
returns **amplitude 1.00000023** and every decoded value is exactly
representable as `float32`, which is only possible if byte order, sample
format and payload offset are all right. The leftover residual is the `delta
value` rounding and nothing else — refitting with an exact `1/8192` shrinks
it 26× (4.0e-4 → 1.5e-5), and `test_head_hdf.py` asserts that relationship
so a real bug cannot hide behind it.

Those recordings are not in the repo (not ours to publish), so the suite
builds equivalent files byte-for-byte and the real-file tests skip when the
data is absent — point `SPWB_ARTEMIS_DIR` at a copy to run them.

Multi-channel files interleave sample-by-sample (`data org: a1b1 a2b2`).
Only single-channel recordings were available, so any other `data org`
value is **refused with a clear error** rather than de-interleaved on a
guess. `FLOAT32` is the only `implementation type` seen in the wild; the
others decode on the same path but are untested against real files.

### Text / CSV, and what "opens in Excel" actually requires

**There is no standard schema for signals in CSV.** RFC 4180 standardises
the *syntax* — quoting, line endings — and says nothing about units,
sampling interval or metadata. The domain does have a real interchange
standard, **UFF-58**, but it is fixed-width ASCII with a coded header that
Excel opens as gibberish; ASAM ODS/ATFX is XML with the same problem. Both
are standards for analysis software, not for office software. So "rich
metadata" and "double-click into Excel" have to be traded off.

Since HDF5 is already the lossless format, **CSV's job here is interchange**,
and the layout is chosen for that:

```
# pySPWB text export 1.0
# signal: {"dt": 0.0001220703125, "n": 245760, "name": "Test", "t0": 0.0, "unit": "Pa", ...}
Time [s],Test [Pa]
0.0,0.0
0.0001220703125,0.6939728856086731
```

A `#` block carrying one JSON object per signal, then a plain table. Excel
and LibreOffice open it on a double-click — the `#` rows sit in column A and
you chart the block underneath — while SPWB reads its own files back
**exactly**, because units, `dt` and `t0` come from the block instead of
being re-derived from a rounded time column. `metadata="none"` writes a bare
table when a downstream tool cannot skip comment lines.

Verified end to end on a real 245 760-sample ArtemiS recording: HDF →
CSV → back is bit-identical, ~0.8 s each way for a 9 MB file.

**Four things that matter more than the schema**, all handled and all tested:

| | |
|---|---|
| **Locale** | A French- or German-locale Excel expects `;` between fields and `,` as the decimal point; a dot-decimal file lands in a single text column there. `locale="fr"` sets both, and the GUI *asks* on export rather than guessing, since the right answer depends on the machine that opens the file |
| **Row limit** | Excel and LibreOffice both stop at 1 048 576 rows. Writing more raises rather than producing a file they silently truncate — not hypothetical, since the GUI's default rate is 51 200 Hz, so ~20 s overflows |
| **Precision** | The default is Python's shortest round-trip representation, so a value survives write → read unchanged. SPWB wrote 9 significant digits, which does **not** round-trip a float64; `precision=9` reproduces it |
| **Encoding** | UTF-8 **with BOM**, because Excel on Windows needs it or `µm/s²` arrives as mojibake |

**Reading files the LabVIEW app wrote** still works: with no `#` block,
`read_text` falls back to exactly its heuristics — `Signal Start and
Length.vi`'s NaN scan for header rows, `Find Name and Unit from String.vi`'s
bracket-first split, `Find T0 and dTt.vi`'s time-column inference, and the
row-wise transpose rule ("there will always be many more samples than
signals"). Unit-in-the-header-cell is genuinely ambiguous — SPWB's own
example signal is `Ref Mic - Exp2010 - Gen I (N1)`, where splitting on `-`
gives the wrong answer — which is exactly why the metadata block carries the
unit separately.

Text **FRF** files (`READ - FRF File.vi`) read through `read_text_frf` into
`TextFRF` objects: complex tokens (`1.5+2.5i`, `4j`) by default, or
`pairs="real-imag"` / `pairs="mag-phase"` for the two-column-per-curve
exports other tools produce.

## Running

```
pip install -e .[gui,io]
spwb                     # or: python -m spwb
spwb run.tdms take1.wav  # loads files into the first window
```

On Windows you can instead **double-click `runApp.cmd`**. It prefers a
`.venv` beside it over whatever Python is on PATH, offers to install SPWB
the first time, and explains what to do rather than flashing a console
window and vanishing if something is missing. Dropping data files onto it
opens them.

### User manuals

[`docs/manuals/`](https://github.com/Charette-AI-Group/pySPWB/tree/main/docs/manuals) holds **a manual for every analysis
window** — [Time Processing](https://github.com/Charette-AI-Group/pySPWB/blob/main/docs/manuals/time-processing.md),
[FFT Analysis](https://github.com/Charette-AI-Group/pySPWB/blob/main/docs/manuals/fft-analysis.md),
[Transfer Function](https://github.com/Charette-AI-Group/pySPWB/blob/main/docs/manuals/transfer-function.md),
[Time-Frequency](https://github.com/Charette-AI-Group/pySPWB/blob/main/docs/manuals/time-frequency.md) and
[Adaptive Filtering](https://github.com/Charette-AI-Group/pySPWB/blob/main/docs/manuals/adaptive-filtering.md) — each working
through demonstration datasets whose expected values
`tools/verify_demo_data.py` checks, so every number a manual quotes is one
the application demonstrably produces. They are also reachable from inside
the application, under **Help > User Manuals ...**.

**The demo datasets come with the package, not just the repository.** They
are synthesised from a fixed seed rather than shipped as files, so every
copy is identical, and there are three ways to make them: **File > Create
Demo Data ...** in the application, `from spwb.demo import write_demo_data`
in a script, or `python tools/make_demo_data.py` from a checkout. A reader
who installed the wheel can follow every manual example. (Screenshots are
regenerated with `python tools/make_manual_images.py`.)

Every manual has a **companion notebook** working the same examples in
code — [FFT Analysis — worked
examples](https://github.com/Charette-AI-Group/pySPWB/blob/main/docs/manuals/notebooks/fft-analysis.ipynb), rendered by GitHub
with its graphs — so the same material serves both the person clicking
through the application and the person scripting it. Their sources live in
[`examples/manuals/`](https://github.com/Charette-AI-Group/pySPWB/tree/main/examples/manuals) and each section asserts the
numbers its manual quotes, which `tests/test_examples.py` runs.

### The graph palette

Every plot carries the tool palette SPWB's LabVIEW front panels had: pick a
tool, then use the mouse directly on the graph.

| | |
|---|---|
| **Pan** | drag to move the view |
| **Zoom** | drag a rectangle to zoom into it |
| **Zoom X** | drag horizontally — rescales the X axis only, full height |
| **Zoom Y** | drag vertically — rescales the Y axis only, full width |
| **± / Fit / Undo** | zoom about the centre, autoscale to the data, step back through zooms |

The X and Y band zooms are implemented in `gui/plotting.py`, because
pyqtgraph has no such mode — its `RectMode` always rescales both axes
(`showAxRect` ignores the `mouseEnabled` mask). Selecting a tool also
constrains the **scroll wheel** to the same axis, since `wheelEvent` reads
that mask.

Undo is slightly better than pyqtgraph's: it records the view *before* the
first zoom, which pyqtgraph does not, so the first Undo returns you to where
you started instead of doing nothing.

The right-click menu is deliberately kept — typing an exact numeric range is
the one thing a mouse does badly, and that is what the menu is good at.

**Antialiasing is off, and that is a performance decision, not a taste one.**
Qt's raster engine has a fast path for 1px cosmetic pens only; a 2px
*antialiased* polyline of 245 760 points (30 s at 8192 Hz) took **6.4 s to
paint, per redraw**. Aliased it takes 0.21 s, and with peak downsampling
0.04 s — faster than the 1px antialiased curve it replaced. At 2px the
stair-stepping is barely visible, and on dense waveform data it is invisible.

Plots also draw at most a couple of points per screen pixel, in `peak` mode
so the envelope and any transient survive (a plain stride would drop them);
zooming in re-renders from the full data. `setClipToView` is deliberately
*not* set — it makes a curve report only the data inside the view, which
stops autoscale seeing the rest, and measuring showed it buys nothing.

The legend gets a backing panel at `LEGEND_OPACITY` with a faint border.
pyqtgraph's default is transparent, so on a dense plot the labels sit
directly on the traces and disappear. It is not *fully* opaque — a curve
passing behind stays faintly visible, so it still reads as an overlay
rather than a hole punched in the plot.

Data traces are drawn at `CURVE_WIDTH` (2px) against the 1px grid and axes.
At equal width a trace reads as part of the background rather than as the
measurement. Whole pixels on purpose — a fractional width antialiases into a
soft grey edge on a non-HiDPI screen. Every window builds its pens with
`curve_pen()`, so the width and the colour cycle are set in one place. The
grid sits at `GRID_ALPHA` (0.2) — light enough to read as a background
reference rather than competing with the traces.

All five analysis windows share `SpwbPlot`, which also absorbed the plot
theming that used to be copy-pasted into each of them. It forwards unknown
attributes to the `PlotWidget` it wraps, so `plot.plot(...)`,
`plot.setLabel(...)` and the rest are unchanged.

### Fitting on a real screen

A `QHBoxLayout`'s minimum width is the **sum** of its children, and a
child's minimum propagates all the way up. Two habits had compounded into a
Time Processing window that refused to be narrower than **2052 px** — wider
than a 1920 display, so it could not be sized to fit one:

* `QLabel` does not word-wrap by default, so a one-sentence help line's
  minimum width is the whole sentence. Two of them accounted for ~250 px.
* rows of controls laid out end to end set the floor at their total width.

Help text now wraps, and control rows use `gui/flow_layout.py` — the
`QLayout` subclass Qt's own examples describe, whose `minimumSize` returns
the **widest single child** rather than the sum. Below that width the row
wraps onto another line instead of pushing the window wider.

Minimum width: **2052 → 838 px**.

### Remembered folders

The file dialogs start where you last were, tracked **per file type and per
operation** — opening a TDMS and saving a WAV remember different places,
which is how the work actually goes: read from a measurement folder, write
to a report folder.

Settings go wherever Qt puts them for the platform (the registry on Windows,
`~/.config` on Linux), under the names `main()` already sets — no config
file of SPWB's own.

A remembered folder is only ever a *hint*: drives get unmounted and folders
get renamed, so `last_dir` checks the directory still exists and falls back
to the user's home folder when it does not. A stale setting can never leave
a dialog pointing at nothing.

All eleven dialogs go through `settings.open_file` / `open_files` /
`save_file` rather than `QFileDialog` directly, so a call site cannot read
the remembered folder without also recording the new one. `forget_dirs()`
clears the lot.

The **whole layout** is remembered the same way: window size and position,
every splitter, and the signal table's column widths and order — all in
Qt's own state blobs, restored when a window opens and saved when it
closes. A `HEADER_VERSION` guard discards a layout saved before the
columns or panes changed, rather than restoring stale sizes onto a
different arrangement. `forget_layout()` clears the lot.

Layouts are keyed on the window *type*, so every Time Processing window
shares one — and a second instance is cascaded by `CASCADE_STEP` so it does
not land exactly on top of the first. Only splitters with an `objectName`
take part: the name is the storage key, which keeps the mapping stable when
the widget tree changes.

### Architecture

Each window owns a `SignalStore`; `WindowManager` is the registry that
replaces LabVIEW's VI-server plumbing (windows are named `TDP 00`, `TDP 01`,
… as the `.vit` clones were). *Signals → Import Signals … → Another Window*
then copies signals straight between windows — the feature that needed
queues and VI-server references in LabVIEW is a method call here.

Two distinct operations on a signal, and the difference matters:

* `signal.with_(...)` — a **revision**: same `sid`, so `store.update()`
  accepts it and every window showing that signal follows the change;
* `signal.copy(...)` — an **independent** signal with a fresh `sid`, which
  is what window import and *Duplicate Current Window* produce (matching
  the value semantics of LabVIEW wires).

The import dialog exposes both: *"Import as independent copies"* is checked
by default (LabVIEW behaviour); unchecking it shares the same objects, so
both windows show identical data.

## Development

```
pip install -e .[dev]
pytest                   # 530 tests: GUI ones run offscreen,
                         # test_separation.py enforces the Qt boundary
ruff check src tests tools examples
```

`tools/` requires LabVIEW 2022 + pywin32 and is only needed to regenerate
fixtures or re-export VI documentation from the original LabVIEW sources
(see the `SPWB` repo and `SPWB_export/`). The fixtures are committed, so
almost no one needs to run them.

CI covers both install paths: one job installs **without** the GUI extra on
a machine with no Qt at all and asserts the processing tests still run, and
another installs everything and runs the full suite offscreen on Linux,
macOS and Windows.

See [CONTRIBUTING.md](https://github.com/Charette-AI-Group/pySPWB/blob/main/CONTRIBUTING.md)
— especially the two rules that are
not negotiable (the Qt boundary, and fixtures pinning numerical behaviour).

## License

MIT, matching the original LabVIEW application.
See [LICENSE](https://github.com/Charette-AI-Group/pySPWB/blob/main/LICENSE).
