"""Check that a packaged build has everything it needs, and say what it found.

``spwb --selftest [report.txt]``, run in CI against the freshly built
executable before it is published.

**Why a bundled application needs this at all.** What PyInstaller drops, it
drops quietly. A missing ``scipy`` submodule, an icon left out of the
bundle, h5py without its HDF5 library, the Qt platform plugin not collected
- none of those stop the executable from starting. They surface on the
user's first transfer function, or as an application with no icon, or as a
File > Open that fails on SPWB's own native format. A build like that looks
fine to whoever built it and is broken for everyone who downloads it.

So this exercises the pieces packaging tends to lose, end to end and against
known numbers: a spectrum whose amplitude must come back 2.0, an HDF5 file
written and read again, all five analysis windows constructed.

**The Qt part deliberately runs offscreen.** A platform plugin that failed
to load aborts the process inside Qt (``qFatal``), which no ``except`` can
catch, so asking a CI runner for a real window risks a hard crash that
reports nothing. The native plugin is checked as a *file in the bundle*
instead - which is the packaging failure that actually happens - and the
windows are then built offscreen, where they cannot take the process down.
"""
from __future__ import annotations

import os
import platform
import sys
import tempfile
from pathlib import Path

__all__ = ["main", "run"]

#: the platform plugin whose absence means "this build cannot open a window"
_PLATFORM_PLUGIN = {
    "win32": "qwindows.dll",
    "darwin": "libqcocoa.dylib",
}.get(sys.platform, "libqxcb.so")

#: the manual each window asks for by name - see gui/*.add_help_menu(manual=)
_MANUALS = ("time-processing", "fft-analysis", "transfer-function",
            "time-frequency", "adaptive-filtering")


class Result:
    """One named check: whether it passed, and what it saw."""

    def __init__(self, name: str, required: bool = True) -> None:
        self.name = name
        self.required = required
        self.ok = False
        self.detail = "not run"

    def __str__(self) -> str:
        mark = "ok  " if self.ok else ("FAIL" if self.required else "warn")
        return f"[{mark}] {self.name}: {self.detail}"


def _run_check(name: str, check, required: bool = True) -> Result:
    """Run one check, turning any exception into a failed Result.

    Broad by design: this runs *after* the build, and its whole job is to
    report what a bundle is missing. An exception that escaped would lose
    every check after it, which is the opposite of useful.
    """
    result = Result(name, required)
    try:
        result.detail = check() or "ok"
        result.ok = True
    except Exception as exc:               # every exception, see above
        result.detail = f"{type(exc).__name__}: {exc}"
    return result


# -- the checks -------------------------------------------------------------
def _check_resources() -> str:
    """Every icon that ships in the bundle, present and non-empty."""
    from . import app_config

    icon = app_config.icon_file()
    if icon is None:
        raise AssertionError(
            f"no application icon at {app_config.ICON_FILE} "
            f"(resources dir: {app_config.RESOURCES_DIR})")

    missing = [key for key in app_config.WINDOW_ICONS
               if app_config.window_icon_file(key) is None]
    if missing:
        raise AssertionError(f"window icons missing: {missing}")

    empty = [p.name for p in app_config.RESOURCES_DIR.iterdir()
             if p.is_file() and p.stat().st_size == 0]
    if empty:
        raise AssertionError(f"zero-length resource files: {empty}")

    return (f"{icon.name} + {len(app_config.WINDOW_ICONS)} window icons "
            f"in {app_config.RESOURCES_DIR}")


def _check_numerics() -> str:
    """The DSP, against known answers - so a mangled scipy cannot pass.

    A windowed spectrum of a 2.0-amplitude sine reads 2.0, and a response
    scaled by two gives a gain of 2.0 at coherence 1.0. A build that lost
    part of scipy fails here rather than in someone's measurement.
    """
    import numpy as np

    from .processing import Signal
    from .processing.dsp import (
        auto_power_spectrums,
        lms_filter,
        resample,
        signal_statistics,
        stft_spectrogram,
        transfer_function,
    )

    fs = 1024.0
    dt = 1.0 / fs
    t = np.arange(int(fs * 2)) / fs
    sine = Signal("sine", 2.0 * np.sin(2 * np.pi * 128.0 * t), dt)

    spectrum = auto_power_spectrums(sine, freq_resolution=1.0, window="hanning")
    peak = float(spectrum.y[round(128.0 / spectrum.dt)])
    if abs(peak - 2.0) > 1e-6:
        raise AssertionError(f"spectrum peak {peak}, expected 2.0")

    response = sine.with_(name="response", y=sine.y * 2.0)
    tf, coherence = transfer_function(sine, response, freq_resolution=2.0)
    k = round(128.0 / tf.dt)
    gain, gamma2 = float(tf.y[k]), float(coherence.y[k])
    if abs(gain - 2.0) > 1e-6 or abs(gamma2 - 1.0) > 1e-6:
        raise AssertionError(f"transfer function {gain} at coherence {gamma2}, "
                             "expected a gain of 2.0 at coherence 1.0")

    # scipy.signal beyond the FFT: the spectrogram's windowing and the
    # polyphase resampler are separate code paths in the bundle. The
    # spectrogram keeps block_size // 2 bins - unlike a spectrum, it does
    # not duplicate the last one.
    spectrogram = stft_spectrogram(sine, block_size=256)
    if spectrogram.n_frames < 2 or spectrogram.n_bins != 128:
        raise AssertionError(f"spectrogram shape {spectrogram.shape}, "
                             "expected several frames of 128 bins")
    if resample(sine, 512.0).dt != 1.0 / 512.0:
        raise AssertionError("resample did not change the sample rate")

    # Normalized LMS, not plain LMS: the plain filter is stable only below
    # a step size that depends on the reference power, and lms_filter
    # rightly refuses to run past it. The normalized one rescales by that
    # power, so 0.5 is safely inside its documented 0 to 2 range wherever
    # this runs.
    rng = np.random.default_rng(0)
    noise = rng.standard_normal(t.size)
    contaminated = sine.with_(name="contaminated", y=sine.y + noise)
    lms = lms_filter(Signal("reference", noise, dt), contaminated,
                     filter_length=32, step_size=0.5,
                     filter_class="Normalized LMS")
    if lms.filtered.y.size != t.size:
        raise AssertionError("the adaptive filter returned the wrong length")
    # it must actually have removed the noise it was given the reference for
    if np.std(lms.filtered.y) >= np.std(contaminated.y):
        raise AssertionError("the adaptive filter removed nothing")

    stats = signal_statistics(sine)
    if abs(stats.rms - 2.0 / np.sqrt(2.0)) > 1e-3:
        raise AssertionError(f"rms {stats.rms}, expected {2.0 / np.sqrt(2.0)}")

    return (f"spectrum, transfer function, spectrogram {spectrogram.shape}, "
            f"resampling and adaptive filter all match their known values "
            f"(numpy {np.__version__})")


def _check_file_io() -> str:
    """HDF5 written and read back - the native format, and h5py's binaries.

    h5py is the dependency most likely to arrive without the C library it
    wraps, and HDF5 is what File > Save writes, so a build that cannot do
    this round trip cannot save a measurement.
    """
    import h5py
    import numpy as np

    from .processing import Signal
    from .processing.io import read_hdf5, write_hdf5

    fs = 1024.0
    t = np.arange(256) / fs
    original = Signal("selftest", np.sin(2 * np.pi * 64.0 * t), 1.0 / fs,
                      y_unit="Pa")

    with tempfile.TemporaryDirectory() as folder:
        path = write_hdf5(Path(folder) / "selftest.h5", [original])
        read_back = read_hdf5(path)
        if len(read_back) != 1:
            raise AssertionError(f"wrote 1 signal, read {len(read_back)}")
        if not np.allclose(read_back[0].y, original.y):
            raise AssertionError("the samples did not survive the round trip")
        if read_back[0].y_unit != "Pa":
            raise AssertionError("the unit did not survive the round trip")

    # Imported, not exercised: reading needs a real measurement file, and
    # nptdms is pure Python, so the import is the whole risk.
    import nptdms

    return (f"HDF5 round trip (h5py {h5py.__version__}, "
            f"libhdf5 {h5py.version.hdf5_version}), "
            f"TDMS reader present (nptdms {nptdms.__version__})")


def _check_qt_platform_plugin() -> str:
    """The native platform plugin is in the bundle.

    Not loaded - see this module's docstring - but its presence is what
    decides whether the downloaded application can open a window at all,
    and it is a plain file check that cannot crash.
    """
    from PySide6.QtCore import QLibraryInfo

    candidates = [Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath))]
    if (base := getattr(sys, "_MEIPASS", None)) is not None:
        candidates += [Path(base) / "PySide6" / "plugins", Path(base) / "plugins"]

    for plugins in candidates:
        platforms = plugins / "platforms"
        if not platforms.is_dir():
            continue
        found = sorted(p.name for p in platforms.iterdir() if p.is_file())
        if _PLATFORM_PLUGIN not in found:
            raise AssertionError(
                f"{_PLATFORM_PLUGIN} is not in {platforms} - this build "
                f"cannot open a window. Found: {found}")
        return f"{_PLATFORM_PLUGIN} in {platforms}"

    raise AssertionError(
        "no Qt platforms plugin directory found; looked in "
        + ", ".join(str(c) for c in candidates))


def _check_windows() -> str:
    """Every analysis window constructed, offscreen.

    Constructing them is what drags in pyqtgraph and the whole widget stack,
    so this is where a bundle missing part of either says so.
    """
    # Set before QApplication exists, so the plugin that could abort the
    # process is never the one asked for. Harmless when a display is present.
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

    import pyqtgraph
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from . import app_config
    from .gui.bridge import WindowManager
    from .gui.fft_analysis import FFTWindow
    from .gui.lms_analysis import LMSWindow
    from .gui.tf_analysis import TransferFunctionWindow
    from .gui.tfa_analysis import TimeFrequencyWindow
    from .gui.time_processing import TimeProcessingWindow

    app = QApplication.instance() or QApplication([])

    # the icon really decoding, not merely existing as a file
    if (icon := app_config.icon_file()) is not None:
        if QIcon(str(icon)).pixmap(64, 64).isNull():
            raise AssertionError(f"{icon.name} did not decode as an image")

    manager = WindowManager()
    built = []
    for cls in (TimeProcessingWindow, FFTWindow, TransferFunctionWindow,
                TimeFrequencyWindow, LMSWindow):
        window = cls(manager)
        try:
            if window.windowIcon().isNull():
                raise AssertionError(f"{cls.__name__} has no window icon")
            built.append(cls.__name__)
        finally:
            window.close()
    app.processEvents()

    return (f"{len(built)} windows built offscreen "
            f"(pyqtgraph {pyqtgraph.__version__})")


def _check_documentation_links() -> str:
    """F1 has somewhere to go. No network: only that the URLs are formed."""
    from . import app_config

    index = app_config.manual_url()
    pages = [app_config.manual_url(stem) for stem in _MANUALS]
    bad = [url for url in [index, *pages] if not url.startswith("https://")]
    if bad:
        raise AssertionError(f"malformed manual URLs: {bad}")
    return f"{len(pages)} manual URLs, index at {index}"


#: (name, check, required). A failed warning does not fail the build.
CHECKS = (
    ("resources", _check_resources, True),
    ("numerics", _check_numerics, True),
    ("file io", _check_file_io, True),
    ("qt platform plugin", _check_qt_platform_plugin, True),
    ("analysis windows", _check_windows, True),
    ("documentation links", _check_documentation_links, False),
)


def run() -> tuple[bool, str]:
    """Run every check. Returns (passed, the report as text)."""
    from . import app_config

    results = [_run_check(name, check, required)
               for name, check, required in CHECKS]
    passed = all(r.ok for r in results if r.required)

    header = [
        f"{app_config.APP_NAME} {app_config.APP_VERSION} self-test",
        f"result       {'PASS' if passed else 'FAIL'}",
        f"platform     {sys.platform} / {platform.machine()}",
        f"python       {sys.version.split()[0]}",
        f"frozen       {getattr(sys, 'frozen', False)}",
        f"executable   {sys.executable}",
        f"bundle       {getattr(sys, '_MEIPASS', '(not frozen)')}",
        "",
    ]
    return passed, "\n".join([*header, *(str(r) for r in results), ""])


def main(report_path: str | None = None) -> int:
    """``spwb --selftest [path]``: write the report, return an exit code.

    The report can go to a file because a windowed build has no console to
    print to - ``sys.stdout`` is None in a Windows ``--noconsole``
    executable, so CI reads the file instead.
    """
    passed, report = run()
    if report_path:
        Path(report_path).write_text(report, encoding="utf-8")
    if sys.stdout is not None:
        try:
            print(report)
        except (OSError, ValueError):      # no usable console in a GUI build
            pass
    return 0 if passed else 1
