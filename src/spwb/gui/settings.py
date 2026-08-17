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
from PySide6.QtWidgets import (
    QFileDialog,
    QHeaderView,
    QSplitter,
    QWidget,
)

__all__ = [
    "CASCADE_STEP",
    "KINDS",
    "MODES",
    "forget_dirs",
    "forget_layout",
    "last_dir",
    "open_file",
    "open_files",
    "remember_dir",
    "restore_geometry",
    "restore_header",
    "restore_splitter",
    "restore_window",
    "save_file",
    "save_geometry",
    "save_header",
    "save_splitter",
    "save_window",
]

#: file-type slugs, one remembered folder per (kind, mode) pair. Slugs are
#: stable storage keys - renaming one silently forgets that folder.
KINDS: tuple[str, ...] = ("hdf5", "tdms", "wave", "text", "rpc", "head_hdf",
                          "demo")

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


def save_splitter(name: str, splitter: QSplitter) -> None:
    """Remember where a splitter's handles sit."""
    store = _store()
    store.setValue(f"{_LAYOUT}/{name}/state", splitter.saveState())
    store.setValue(f"{_LAYOUT}/{name}/version", HEADER_VERSION)


def restore_splitter(name: str, splitter: QSplitter) -> bool:
    """Put a splitter's handles back. Returns whether a layout was used."""
    store = _store()
    if store.value(f"{_LAYOUT}/{name}/version", 0, type=int) != HEADER_VERSION:
        return False
    state = store.value(f"{_LAYOUT}/{name}/state")
    if not state:
        return False
    return bool(splitter.restoreState(state))


def save_geometry(name: str, widget: QWidget) -> None:
    """Remember a window's size and position."""
    _store().setValue(f"{_LAYOUT}/{name}/geometry", widget.saveGeometry())


def restore_geometry(name: str, widget: QWidget) -> bool:
    """Put a window back where it was. Returns whether it was moved.

    ``restoreGeometry`` is the right call rather than ``move``/``resize``:
    Qt checks the saved position against the screens that exist *now*, so a
    window last used on a monitor that is no longer attached comes back on
    screen instead of somewhere invisible.
    """
    state = _store().value(f"{_LAYOUT}/{name}/geometry")
    return bool(state) and bool(widget.restoreGeometry(state))


#: how far each extra window of the same type is nudged, so a second one
#: does not land exactly on top of the first
CASCADE_STEP = 30
_CASCADE_WRAP = 6


def save_window(window_name: str, window: QWidget) -> None:
    """Remember a window's geometry and every named splitter inside it.

    ``window_name`` is the manager's name (``"TDP 01"``); the layout is
    keyed on the type prefix, so all Time Processing windows share one
    remembered layout rather than fighting over separate ones.
    """
    prefix = window_name.split()[0]
    save_geometry(prefix, window)
    for splitter in window.findChildren(QSplitter):
        if splitter.objectName():
            save_splitter(f"{prefix}/{splitter.objectName()}", splitter)


def restore_window(window_name: str, window: QWidget) -> bool:
    """Re-apply a saved window layout, cascading extra instances.

    Only splitters with an ``objectName`` take part - the name is the
    storage key, so an unnamed splitter is deliberately not persisted.
    """
    prefix, _, index = window_name.partition(" ")
    restored = restore_geometry(prefix, window)
    try:
        step = int(index) % _CASCADE_WRAP
    except ValueError:
        step = 0
    if restored and step:
        offset = step * CASCADE_STEP
        window.move(window.x() + offset, window.y() + offset)
    for splitter in window.findChildren(QSplitter):
        if splitter.objectName():
            restore_splitter(f"{prefix}/{splitter.objectName()}", splitter)
    return restored


def forget_layout() -> None:
    """Drop every saved layout - tables, splitters and window geometry."""
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


def choose_folder(parent: QWidget | None, caption: str, kind: str) -> str:
    """``QFileDialog.getExistingDirectory`` that remembers where it was."""
    folder = QFileDialog.getExistingDirectory(parent, caption,
                                              last_dir(kind, "save"))
    if folder:
        remember_dir(kind, "save", folder)
    return folder
