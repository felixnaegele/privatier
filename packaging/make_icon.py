"""Draws the Privatier app icon (icon.icns) and the disk image background (dmg_background.tiff).

Run:  .venv/bin/python packaging/make_icon.py
Needs Pillow and the Mac tool tiffutil. build_app.py runs this when the files are missing.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
S = 4  # supersampling for smooth edges


def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def draw_icon(size: int = 1024) -> Image.Image:
    """A document whose sensitive lines are masked, with a shield in front. Apple's grid: the shape fills 80%."""
    W = size * S
    canvas = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    u = W / 1024  # unit: designed on a 1024 grid

    # Rounded square (Apple template: 824 of 1024, soft shadow beneath)
    box = (100 * u, 100 * u, 924 * u, 924 * u)
    radius = 186 * u
    shadow = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((box[0], box[1] + 12 * u, box[2], box[3] + 12 * u), radius, fill=(0, 0, 0, 110))
    canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(14 * u)))

    gradient = Image.new("RGBA", (W, W))
    top, bottom = (46, 104, 168), (16, 40, 92)
    column = Image.new("RGB", (1, W))
    for y in range(W):
        column.putpixel((0, y), _lerp(top, bottom, min(1, max(0, (y - box[1]) / (box[3] - box[1])))))
    gradient = column.resize((W, W)).convert("RGBA")
    mask = Image.new("L", (W, W), 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, radius, fill=255)
    canvas.paste(gradient, (0, 0), mask)

    layer = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    # Document with a folded corner
    left, top_, right, bottom_ = 262 * u, 214 * u, 706 * u, 770 * u
    fold = 112 * u
    page = [(left, top_), (right - fold, top_), (right, top_ + fold), (right, bottom_), (left, bottom_)]
    docshadow = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    ImageDraw.Draw(docshadow).polygon([(x, y + 14 * u) for x, y in page], fill=(0, 0, 0, 90))
    layer.alpha_composite(docshadow.filter(ImageFilter.GaussianBlur(12 * u)))
    d.polygon(page, fill=(250, 251, 253, 255))
    d.polygon([(right - fold, top_), (right, top_ + fold), (right - fold, top_ + fold)], fill=(206, 216, 232, 255))

    # Text lines: some readable (grey), some masked (dark bars)
    x0 = left + 52 * u
    rows = [(330, 0.50, "text"), (400, 0.82, "mask"), (470, 0.72, "text"), (540, 0.90, "mask"), (610, 0.62, "text"), (680, 0.40, "text")]
    full = (right - 52 * u) - x0
    for y, frac, kind in rows:
        y = y * u
        h = 34 * u
        if kind == "text":
            d.rounded_rectangle((x0, y, x0 + full * frac, y + h), h / 2, fill=(176, 190, 212, 255))
        else:
            d.rounded_rectangle((x0 - 6 * u, y - 6 * u, x0 + full * frac, y + h + 6 * u), 10 * u, fill=(18, 36, 74, 255))

    # Shield with a check mark, lower right
    cx, cy = 690 * u, 700 * u
    sw, sh = 330 * u, 390 * u
    pts = []
    import math

    def shield(scale):
        w, h = sw * scale, sh * scale
        top_y = cy - h / 2
        poly = [(cx - w / 2, top_y + h * 0.10), (cx, top_y), (cx + w / 2, top_y + h * 0.10), (cx + w / 2, top_y + h * 0.52)]
        for i in range(1, 25):  # right curve down to the tip
            t = i / 24
            poly.append((cx + w / 2 * (1 - t) ** 0.9 * math.cos(t * 0.0) , top_y + h * (0.52 + 0.48 * math.sin(t * math.pi / 2))))
        poly.append((cx, top_y + h))
        for i in range(24, 0, -1):
            t = i / 24
            poly.append((cx - w / 2 * (1 - t) ** 0.9, top_y + h * (0.52 + 0.48 * math.sin(t * math.pi / 2))))
        poly.append((cx - w / 2, top_y + h * 0.52))
        return poly

    ring = shield(1.0)
    d.polygon([(x, y + 10 * u) for x, y in ring], fill=(0, 0, 0, 70))
    d.polygon(ring, fill=(250, 251, 253, 255))
    inner = shield(0.84)
    d.polygon(inner, fill=(30, 168, 142, 255))
    tick = [(cx - 62 * u, cy + 6 * u), (cx - 18 * u, cy + 52 * u), (cx + 66 * u, cy - 50 * u)]
    d.line(tick, fill=(255, 255, 255, 255), width=int(34 * u), joint="curve")
    for x, y in (tick[0], tick[2]):
        r = 17 * u
        d.ellipse((x - r, y - r, x + r, y + r), fill=(255, 255, 255, 255))

    canvas.alpha_composite(layer)
    return canvas.resize((size, size), Image.LANCZOS)


# icns entry types and the pixel size each one holds. PNG-compressed entries, as modern macOS expects.
_ICNS = [("icp4", 16), ("icp5", 32), ("icp6", 64), ("ic07", 128), ("ic08", 256), ("ic09", 512), ("ic10", 1024),
         ("ic11", 32), ("ic12", 64), ("ic13", 256), ("ic14", 512)]


def make_icns(out: Path) -> None:
    """Writes the .icns file itself (the format is simple), so it works without the iconutil tool."""
    import io
    import struct

    master = draw_icon(1024)
    cache: dict[int, bytes] = {}
    body = b""
    for kind, px in _ICNS:
        if px not in cache:
            img = draw_icon(px) if px <= 64 else master.resize((px, px), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, "PNG")
            cache[px] = buf.getvalue()
        body += kind.encode() + struct.pack(">I", len(cache[px]) + 8) + cache[px]
    out.write_bytes(b"icns" + struct.pack(">I", len(body) + 8) + body)


def _font(size: int):
    for path in ("/System/Library/Fonts/SFNS.ttf", "/System/Library/Fonts/Helvetica.ttc", "/Library/Fonts/Arial.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_background(scale: int = 1) -> Image.Image:
    """660 x 400 points: light background, an arrow from the app to the Applications folder, one line of help."""
    w, h = 660 * scale, 400 * scale
    img = Image.new("RGB", (w, h))
    for y in range(h):
        img.paste(_lerp((247, 249, 252), (226, 233, 244), y / h), (0, y, w, y + 1))
    d = ImageDraw.Draw(img)
    cy = 190 * scale
    d.line((255 * scale, cy, 395 * scale, cy), fill=(120, 140, 175), width=6 * scale)
    d.polygon([(412 * scale, cy), (388 * scale, cy - 20 * scale), (388 * scale, cy + 20 * scale)], fill=(120, 140, 175))
    text = "Drag Privatier onto Applications"
    font = _font(17 * scale)
    tw = d.textlength(text, font=font)
    d.text(((w - tw) / 2, 52 * scale), text, fill=(52, 70, 104), font=font)
    small = _font(13 * scale)
    note = "First time: please read \"First start.txt\""
    tw = d.textlength(note, font=small)
    d.text(((w - tw) / 2, 368 * scale), note, fill=(110, 124, 150), font=small)
    return img


def make_background(out: Path) -> None:
    """A two-resolution TIFF, so the background is sharp on Retina screens."""
    with tempfile.TemporaryDirectory() as tmp:
        a, b = Path(tmp) / "bg.tiff", Path(tmp) / "bg@2x.tiff"
        for path, scale in ((a, 1), (b, 2)):
            draw_background(scale).save(path, dpi=(72 * scale, 72 * scale))
        try:
            subprocess.run(["tiffutil", "-cathidpicheck", str(a), str(b), "-out", str(out)], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (subprocess.CalledProcessError, FileNotFoundError):
            one, two = draw_background(1), draw_background(2)  # the same thing, written by Pillow
            two.encoderinfo = {"dpi": (144, 144)}
            one.save(out, save_all=True, append_images=[two], dpi=(72, 72))


def main() -> None:
    make_icns(HERE / "icon.icns")
    make_background(HERE / "dmg_background.tiff")
    draw_icon(1024).save(HERE / "icon_1024.png")  # for looking at; not needed by the build
    print("wrote icon.icns, dmg_background.tiff, icon_1024.png")


if __name__ == "__main__":
    main()
