"""Draw the application icon and one icon per analysis window.

Every icon is drawn with QPainter *at each size* rather than scaled down
from one big rendering, because a 16 px icon made by shrinking a 256 px one
is mush - the strokes fall below a pixel and the shape stops reading. The
per-size drawing thickens strokes and drops detail as it gets smaller.

The artwork says what the window shows: a waveform for Time Processing,
spectrum bars for FFT, a resonance curve for Transfer Function, a
spectrogram over its two cross-sections for Time-Frequency, and noise
resolving into a clean tone for Adaptive Filtering. They share one
background so they read as a family, and each carries a different accent so
they stay apart on a taskbar.

    python tools/make_icons.py [names ...]

Writes into ``src/spwb/resources/``, which ships in the wheel. The
application picks the icon up through ``app_config`` - never by path.
"""
from __future__ import annotations

import math
import os
import struct
import sys
from pathlib import Path

# Must happen before QApplication exists: the offscreen plugin has no fonts,
# and while these icons carry no text, the same rule keeps rendering honest.
os.environ.pop("QT_QPA_PLATFORM", None)

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

OUTPUT_DIR = REPO / "src" / "spwb" / "resources"
REVIEW_DIR = REPO / ".screenshots"

from PySide6.QtCore import QBuffer, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QApplication

#: what a .ico carries. 16 is the taskbar and title bar, 256 the file
#: dialog's extra-large view; the ones between are what Windows actually
#: picks at various DPI settings.
ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)

#: the shared background, a deep technical blue rather than CloakClip's
#: indigo-violet - related, not identical
BACKGROUND_TOP = QColor("#6366F1")
BACKGROUND_BOTTOM = QColor("#1E3A8A")

#: The application itself is gold instead, so it is not one more blue tile
#: among its own windows. A taskbar shows one SPWB and several windows, and
#: the one you want to click is the odd-coloured one.
APP_BACKGROUND_TOP = QColor("#FBBF24")
APP_BACKGROUND_BOTTOM = QColor("#B45309")
#: navy on gold, which is the same contrast as white on blue
APP_GLYPH = QColor("#12235C")

TRACE = QColor("#FFFFFF")
#: per-icon accent, so a taskbar full of SPWB windows is still readable
ACCENTS = {
    "spwb": QColor("#FBBF24"),      # amber, the odd one out: the app itself
    "tdp": QColor("#7DD3FC"),       # sky
    "fft": QColor("#FBBF24"),       # amber
    "tf": QColor("#34D399"),        # green
    "tfa": QColor("#F472B6"),       # pink, picked up by the colour bands
    "lms": QColor("#F87171"),       # red, the noise being removed
}

_app: QApplication | None = None


def session() -> QApplication:
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication([])
    return _app


# --------------------------------------------------------------------------
# drawing helpers
# --------------------------------------------------------------------------
def stroke(size: int, weight: float = 1.0) -> float:
    """A stroke width that stays visible when the icon is tiny.

    Scaling a stroke linearly with the icon makes it vanish below about
    24 px, so the floor is one whole pixel and small sizes get a
    proportionally fatter line.
    """
    return max(1.0, size * 0.075 * weight)


def trace_pen(colour: QColor, size: int, weight: float = 1.0) -> QPen:
    pen = QPen(colour, stroke(size, weight))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def polyline(points) -> QPainterPath:
    path = QPainterPath()
    for i, point in enumerate(points):
        (path.moveTo if i == 0 else path.lineTo)(point)
    return path


def wave(box: QRectF, cycles: float, samples: int = 96,
         envelope=None) -> QPainterPath:
    """A sine across ``box``; ``envelope(u)`` scales it, u running 0..1."""
    points = []
    for i in range(samples + 1):
        u = i / samples
        amplitude = 1.0 if envelope is None else envelope(u)
        y = box.center().y() - math.sin(2 * math.pi * cycles * u) * (
            box.height() / 2) * amplitude
        points.append(QPointF(box.left() + u * box.width(), y))
    return polyline(points)


def content_box(size: int) -> QRectF:
    """Where artwork may go: inside the rounded background, with margin."""
    inset = size * 0.20
    return QRectF(inset, inset, size - 2 * inset, size - 2 * inset)


# --------------------------------------------------------------------------
# the six designs
# --------------------------------------------------------------------------
def draw_spwb(painter: QPainter, size: int, accent: QColor) -> None:
    """The workbench: a wave becoming a spectrum - time on the left,
    frequency on the right, which is what the application does.

    ``accent`` is unused: this one is navy on gold throughout, and adding a
    third colour at 16 px only muddies it.
    """
    box = content_box(size)
    small = size < 32
    half = box.width() * 0.46

    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(trace_pen(APP_GLYPH, size, 1.05))
    painter.drawPath(wave(QRectF(box.left(), box.top() + box.height() * 0.12,
                                 half, box.height() * 0.76),
                          1.0 if small else 1.25))

    heights = (0.55, 1.0, 0.72) if not small else (0.6, 1.0)
    gap = (box.width() - half) / (len(heights) * 2 - 1)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(APP_GLYPH)
    for i, height in enumerate(heights):
        bar = QRectF(box.right() - (box.width() - half) + i * 2 * gap,
                     box.bottom() - box.height() * height * 0.88,
                     gap, box.height() * height * 0.88)
        painter.drawRoundedRect(bar, gap * 0.3, gap * 0.3)


def draw_tdp(painter: QPainter, size: int, accent: QColor) -> None:
    """Time Processing: a time signal on its baseline."""
    box = content_box(size)
    painter.setPen(trace_pen(accent, size, 0.55))
    painter.drawLine(QPointF(box.left(), box.center().y()),
                     QPointF(box.right(), box.center().y()))

    painter.setPen(trace_pen(TRACE, size, 1.15))
    cycles = 1.0 if size < 32 else 1.75
    # a swelling envelope, so it reads as a measurement rather than a
    # textbook sine
    painter.drawPath(wave(box, cycles,
                          envelope=lambda u: 0.45 + 0.55 * math.sin(math.pi * u)))


def draw_fft(painter: QPainter, size: int, accent: QColor) -> None:
    """FFT: a spectrum, one peak taller than the rest."""
    box = content_box(size)
    small = size < 32
    heights = (0.30, 0.55, 1.0, 0.42, 0.22) if not small else (0.35, 1.0, 0.5)
    gap = box.width() / (len(heights) * 2 - 1)

    painter.setPen(Qt.PenStyle.NoPen)
    for i, height in enumerate(heights):
        painter.setBrush(accent if height == 1.0 else TRACE)
        bar = QRectF(box.left() + i * 2 * gap,
                     box.bottom() - box.height() * height,
                     gap, box.height() * height)
        painter.drawRoundedRect(bar, gap * 0.35, gap * 0.35)


def draw_tf(painter: QPainter, size: int, accent: QColor) -> None:
    """Transfer Function: a resonance - flat, a peak, then roll-off."""
    box = content_box(size)
    points = []
    samples = 64
    for i in range(samples + 1):
        u = i / samples
        # a peak at u = 0.45 sitting on a gently falling baseline
        peak = math.exp(-((u - 0.45) ** 2) / 0.012)
        level = 0.30 + 0.70 * peak - 0.22 * u
        points.append(QPointF(box.left() + u * box.width(),
                              box.bottom() - level * box.height() * 0.95))

    painter.setPen(trace_pen(accent, size, 0.55))
    painter.drawLine(QPointF(box.left(), box.bottom()),
                     QPointF(box.right(), box.bottom()))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(trace_pen(TRACE, size, 1.15))
    painter.drawPath(polyline(points))


def draw_tfa(painter: QPainter, size: int, accent: QColor) -> None:
    """Time-Frequency: a colour map above its two cross-sections."""
    box = content_box(size)
    small = size < 32
    map_height = box.height() * (0.72 if small else 0.62)
    colour_map = QRectF(box.left(), box.top(), box.width(), map_height)

    # a spectrogram reads as bands of colour with a bright diagonal ridge
    gradient = QLinearGradient(colour_map.bottomLeft(), colour_map.topRight())
    gradient.setColorAt(0.00, QColor("#1E3A8A"))
    gradient.setColorAt(0.35, QColor("#0EA5E9"))
    gradient.setColorAt(0.60, accent)
    gradient.setColorAt(0.80, QColor("#FDE047"))
    gradient.setColorAt(1.00, QColor("#FFFFFF"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(gradient)
    painter.drawRoundedRect(colour_map, size * 0.05, size * 0.05)

    if small:
        return                      # the two sections would be sub-pixel

    # the Time Section and Frequency Section under it
    painter.setPen(trace_pen(TRACE, size, 0.6))
    lane = box.height() - map_height
    baseline = box.bottom() - lane * 0.25
    painter.drawPath(wave(QRectF(box.left(), baseline - lane * 0.30,
                                 box.width() * 0.46, lane * 0.55), 1.0))
    painter.drawPath(wave(QRectF(box.center().x() + box.width() * 0.04,
                                 baseline - lane * 0.30,
                                 box.width() * 0.46, lane * 0.55), 1.5))


def draw_lms(painter: QPainter, size: int, accent: QColor) -> None:
    """Adaptive Filtering: noisy in, clean out.

    Two stacked lanes rather than two halves of one trace - overlapping
    them made a smear at every size, and in/out is the whole idea.
    """
    box = content_box(size)
    lane = box.height() * 0.38
    painter.setBrush(Qt.BrushStyle.NoBrush)

    # in: a tone buried under noise
    top = QRectF(box.left(), box.top(), box.width(), lane)
    rough = (0.30, -0.95, 0.75, -0.45, 1.0, -0.7, 0.5, -1.0, 0.8, -0.35, 0.6)
    step = box.width() / (len(rough) - 1)
    painter.setPen(trace_pen(accent, size, 0.8))
    painter.drawPath(polyline([
        QPointF(box.left() + i * step, top.center().y() - v * lane * 0.5)
        for i, v in enumerate(rough)]))

    # out: the tone on its own
    bottom = QRectF(box.left(), box.bottom() - lane, box.width(), lane)
    painter.setPen(trace_pen(TRACE, size, 1.05))
    painter.drawPath(wave(bottom, 1.0 if size < 32 else 1.25))


DESIGNS = {
    "spwb": ("spwb", draw_spwb),
    "tdp": ("window-tdp", draw_tdp),
    "fft": ("window-fft", draw_fft),
    "tf": ("window-tf", draw_tf),
    "tfa": ("window-tfa", draw_tfa),
    "lms": ("window-lms", draw_lms),
}


# --------------------------------------------------------------------------
# rendering and packing
# --------------------------------------------------------------------------
def render(key: str, size: int) -> QPixmap:
    """One icon at one size, drawn rather than scaled."""
    session()
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)

    # tighter corners when small, or the rounding eats the artwork
    radius = size * (0.18 if size < 32 else 0.22)
    background = QLinearGradient(QPointF(0, 0), QPointF(0, size))
    top, bottom = ((APP_BACKGROUND_TOP, APP_BACKGROUND_BOTTOM) if key == "spwb"
                   else (BACKGROUND_TOP, BACKGROUND_BOTTOM))
    background.setColorAt(0.0, top)
    background.setColorAt(1.0, bottom)
    painter.setBrush(background)
    painter.drawRoundedRect(QRectF(0, 0, size, size), radius, radius)

    DESIGNS[key][1](painter, size, ACCENTS[key])
    painter.end()
    return pixmap


def png_bytes(pixmap: QPixmap) -> bytes:
    buffer = QBuffer()
    buffer.open(QBuffer.OpenModeFlag.WriteOnly)
    pixmap.save(buffer, "PNG")
    return bytes(buffer.data())


def pack_ico(images: list[tuple[int, bytes]]) -> bytes:
    """A multi-resolution .ico holding PNG-encoded entries.

    Written by hand rather than through Qt's ico writer so every size is
    the one that was drawn at that size. Vista and later accept PNG inside
    an ICO, which is what keeps the 256 px entry from being enormous.
    """
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries, payload = [], []
    for size, data in images:
        entries.append(struct.pack(
            "<BBBBHHII",
            0 if size >= 256 else size,      # 0 means 256 in an ICO
            0 if size >= 256 else size,
            0, 0, 1, 32, len(data), offset))
        payload.append(data)
        offset += len(data)
    return header + b"".join(entries) + b"".join(payload)


def build(key: str) -> list[Path]:
    stem = DESIGNS[key][0]
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)

    images = [(size, png_bytes(render(key, size))) for size in ICON_SIZES]
    ico = OUTPUT_DIR / f"{stem}.ico"
    ico.write_bytes(pack_ico(images))

    written = [ico]
    if key == "spwb":
        # macOS wants a large PNG, as resources/README.md records
        png = OUTPUT_DIR / f"{stem}.png"
        render(key, 1024).save(str(png), "PNG")
        written.append(png)

    # a contact sheet for review, next to the manuals' screenshots
    preview = REVIEW_DIR / f"icon-{stem}.png"
    render(key, 256).save(str(preview), "PNG")

    sizes = "/".join(str(s) for s in ICON_SIZES)
    print(f"   {ico.name:20} {ico.stat().st_size / 1024:6.1f} kB  ({sizes})")
    return written


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    wanted = argv[1:] or list(DESIGNS)
    unknown = [name for name in wanted if name not in DESIGNS]
    if unknown:
        raise SystemExit(f"unknown icon(s) {unknown}; known: {list(DESIGNS)}")

    print(f"drawing {len(wanted)} icon(s) -> {OUTPUT_DIR}\n")
    for key in wanted:
        build(key)
    print(f"\n{len(wanted)} icon(s). Previews in {REVIEW_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
