"""Persistent application settings: remembered folders and table layouts.

Browsing back to the same directory on every import is one of those small
frictions that adds up, so the folder last used is stored **per file type
and per operation**: opening a TDMS and saving a WAV remember different
places, which is how people actually work - read from a measurement folder,
write to a report folder.

Settings live wherever Qt puts them for the platform (the registry on
Windows, ``~/.config`` on Linux, a plist on macOS), under the organisation
and application names :func:`spwb.gui.app.main` sets. Nothing here needs a
config file of its own.

**A remembered folder is only a hint.** Drives get unmounted and folders get
renamed, so :func:`last_dir` checks the directory still exists and falls
back to the user's home folder when it does not. A stale setting can never
leave the file dialog pointing at nothing.

Use the three wrappers rather than calling :class:`QFileDialog` directly -
they read the remembered folder on the way in and record it on the way out,
so a call site cannot accidentally do one without the other::

    path = settings.open_file(self, "Open TDMS File", "tdms",
                              "National Instruments (*.tdms)")

Table layouts work the same way: :func:`restore_header` after building a
header, :func:`save_header` on close. Column widths and column order both
ride in Qt's own state blob, so adding a column needs no new code here -
only a :data:`HEADER_VERSION` bump so stale layouts are discarded.
"""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QFileDialog, QHeaderView, QWidget

__all__ = [
    "KINDS",
    "MODES",
    "forget_dirs",
    "forget_layout",
    "last_dir",
    "open_file",
    "open_files",
    "remember_dir",
    "restore_header",
    "save_file",
    "save_header",
]

#: file-type slugs, one remembered folder per (kind, mode) pair. Slugs are
#: stable storage keys - renaming one silently forgets that folder.
KINDS: tuple[str, ...] = ("hdf5", "tdms", "wave", "text", "rpc", "head_hdf")

#: the operations tracked separately for each kind
MODES: tuple[str, ...] = ("open", "save")

_GROUP = "paths"
_LAYOUT = "layout"

#: Bump whenever a table's columns change. Unlike ``QMainWindow``,
#: ``QHeaderView.saveState`` takes no version argument, so the check is
#: done here: a layout saved under a different version is discarded rather
#: than restoring widths onto columns that have since moved or been
#: renamed, which would look like corruption to the user.
HEADER_VERSION = 1


def _key(kind: str, mode: str) -> str:
    if kind not in KINDS:
        raise ValueError(f"unknown file kind {kind!r}; known: {list(KINDS)}")
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}; known: {list(MODES)}")
    return f"{_GROUP}/{kind}/{mode}"


def _store() -> QSettings:
    """The settings object, built fresh on each call.

    Deliberately not a module-level constant: a ``QSettings`` captures the
    organisation and application names at construction, and ``app.main``
    sets those *after* the module is imported. Building it lazily means it
    always lands in the right place - and lets tests redirect it.
    """
    return QSettings()


def last_dir(kind: str, mode: str) -> str:
    """Where to start browsing for this file type and operation.

    The remembered folder if it still exists, the user's home folder
    otherwise - never an empty or missing path.
    """
    saved = _store().value(_key(kind, mode), "", type=str)
    if saved and os.path.isdir(saved):
        return saved
    return str(Path.home())


def remember_dir(kind: str, mode: str, path: str | os.PathLike) -> None:
    """Record the folder of ``path`` as the next start point."""
    if not path:
        return
    candidate = Path(path)
    folder = candidate if candidate.is_dir() else candidate.parent
    if folder.is_dir():
        _store().setValue(_key(kind, mode), str(folder))


def forget_dirs() -> None:
    """Drop every remembered folder, so browsing starts at home again."""
    store = _store()
    store.remove(_GROUP)
    store.sync()


# -- table layouts ---------------------------------------------------------
def save_header(name: str, header: QHeaderView) -> None:
    """Remember a table's column order, widths and sort for next time.

    ``QHeaderView.saveState`` packs all of it into one blob, so there is
    nothing to keep in step by hand when a column is added.
    """
    store = _store()
    store.setValue(f"{_LAYOUT}/{name}/state", header.saveState())
    store.setValue(f"{_LAYOUT}/{name}/version", HEADER_VERSION)


def restore_header(name: str, header: QHeaderView) -> bool:
    """Re-apply a saved layout. Returns whether one was found and used.

    ``False`` means the caller's defaults stand - either nothing was saved
    yet, or it was saved under a different :data:`HEADER_VERSION`, meaning
    the columns have changed since and the old widths no longer describe
    this table.
    """
    store = _store()
    if store.value(f"{_LAYOUT}/{name}/version", 0, type=int) != HEADER_VERSION:
        return False
    state = store.value(f"{_LAYOUT}/{name}/state")
    if not state:
        return False
    return bool(header.restoreState(state))


def forget_layout() -> None:
    """Drop every saved table layout, so the defaults come back."""
    store = _store()
    store.remove(_LAYOUT)
    store.sync()


# -- the dialog wrappers ---------------------------------------------------
def open_file(parent: QWidget | None, caption: str, kind: str,
              filters: str) -> str:
    """``QFileDialog.getOpenFileName`` that remembers where it was."""
    path, _ = QFileDialog.getOpenFileName(parent, caption,
                                          last_dir(kind, "open"), filters)
    if path:
        remember_dir(kind, "open", path)
    return path


def open_files(parent: QWidget | None, caption: str, kind: str,
               filters: str) -> list[str]:
    """``QFileDialog.getOpenFileNames`` that remembers where it was."""
    paths, _ = QFileDialog.getOpenFileNames(parent, caption,
                                            last_dir(kind, "open"), filters)
    if paths:
        remember_dir(kind, "open", paths[0])
    return list(paths)


def save_file(parent: QWidget | None, caption: str, kind: str,
              filters: str) -> str:
    """``QFileDialog.getSaveFileName`` that remembers where it was."""
    path, _ = QFileDialog.getSaveFileName(parent, caption,
                                          last_dir(kind, "save"), filters)
    if path:
        remember_dir(kind, "save", path)
    return path
