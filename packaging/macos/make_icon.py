"""
packaging.macos.make_icon — draw the app icon and pack it into an .icns.

PURPOSE
    Produce `ESXBankStudio.icns` for the .app bundle without a binary asset in
    the repo. The icon is DRAWN from the same palette as `ui/theme.py`, so a
    theme change can be carried into the icon by re-running the build.
    Does NOT touch the app itself; build tooling only.

FLOW
    main() → render(size) for each size macOS asks for → PNGs into an
    `.iconset` folder → `iconutil -c icns` (ships with macOS) → .icns.

TO CHANGE THE LOOK: edit `paint()`. Colors come from `ui.theme.Palette`, so
retheme there rather than hard-coding hex here.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile

# The repo root must be importable so `ui.theme` resolves when this runs as a script.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import (  # noqa: E402
    QColor,
    QFont,
    QGuiApplication,
    QImage,
    QPainter,
    QPen,
)

from ui.theme import Palette  # noqa: E402

#: The base sizes an .iconset must contain; each also gets an @2x variant.
#: Names and sizes are fixed by Apple's `iconutil` — it rejects anything else.
ICON_SIZES = (16, 32, 128, 256, 512)


# O(p) time, O(p) space — p = pixels in the icon (≤ 1024×1024)
def paint(img: QImage) -> None:
    """Draw one icon: a rounded chassis, an amber LCD reading 'ESX', 16 step keys."""
    p = Palette()
    s = img.width()
    g = QPainter(img)
    g.setRenderHint(QPainter.RenderHint.Antialiasing)

    # macOS Big Sur+ icon grid: the tile fills ~80% of the canvas, corner ≈ 22%.
    m = s * 0.1
    tile = QRectF(m, m, s - 2 * m, s - 2 * m)
    g.setPen(QPen(QColor(p.line), max(1.0, s * 0.008)))
    g.setBrush(QColor(p.panel))
    g.drawRoundedRect(tile, tile.width() * 0.22, tile.height() * 0.22)

    # The LCD window.
    lcd = QRectF(
        tile.left() + tile.width() * 0.14,
        tile.top() + tile.height() * 0.16,
        tile.width() * 0.72,
        tile.height() * 0.36,
    )
    g.setPen(Qt.PenStyle.NoPen)
    g.setBrush(QColor(p.chassis))
    g.drawRoundedRect(lcd, lcd.height() * 0.12, lcd.height() * 0.12)
    font = QFont("Menlo")
    font.setBold(True)
    font.setPixelSize(max(1, int(lcd.height() * 0.62)))
    g.setFont(font)
    g.setPen(QColor(p.lcd))
    g.drawText(lcd, Qt.AlignmentFlag.AlignCenter, "ESX")

    # Sixteen step keys in two rows of eight; beat keys (every 4th) lit amber.
    cols, rows = 8, 2
    area = QRectF(
        lcd.left(), tile.top() + tile.height() * 0.60, lcd.width(), tile.height() * 0.24
    )
    gap = area.width() * 0.035
    kw = (area.width() - gap * (cols - 1)) / cols
    kh = (area.height() - gap * (rows - 1)) / rows
    # O(k) time, O(1) space — k = 16 step keys
    for i in range(cols * rows):
        r, c = divmod(i, cols)
        key = QRectF(area.left() + c * (kw + gap), area.top() + r * (kh + gap), kw, kh)
        g.setBrush(QColor(p.step if i % 4 == 0 else p.line))
        g.drawRoundedRect(key, kw * 0.18, kw * 0.18)
    g.end()


# O(p) time, O(p) space — p = pixels in the icon
def render(size: int) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    paint(img)
    return img


# O(P) time, O(p) space — P = pixels across all 10 iconset PNGs; p = pixels in the largest
def main(out_path: str) -> int:
    _app = QGuiApplication.instance() or QGuiApplication([])  # fonts need a Gui app
    with tempfile.TemporaryDirectory() as tmp:
        iconset = os.path.join(tmp, "ESXBankStudio.iconset")
        os.mkdir(iconset)
        # O(z) time, O(1) space — z = 5 base sizes × 2 scales
        for base in ICON_SIZES:
            render(base).save(os.path.join(iconset, f"icon_{base}x{base}.png"))
            render(base * 2).save(os.path.join(iconset, f"icon_{base}x{base}@2x.png"))
        subprocess.run(["iconutil", "-c", "icns", iconset, "-o", out_path], check=True)
    print(f"icon written: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "ESXBankStudio.icns"))
