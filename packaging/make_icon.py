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
    """A sheet of paper with one line blacked out. Apple's grid: the shape fills 824 of 1024, with a soft shadow."""
    W = size * S
    canvas = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    u = W / 1024  # unit: designed on a 1024 grid

    box = (100 * u, 100 * u, 924 * u, 924 * u)
    radius = 186 * u
    shadow = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((box[0], box[1] + 10 * u, box[2], box[3] + 10 * u), radius, fill=(0, 0, 0, 70))
    canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(12 * u)))

    # Warm paper, very slightly lighter at the top, with a fine edge so it shows on white
    column = Image.new("RGB", (1, W))
    for y in range(W):
        column.putpixel((0, y), _lerp((248, 245, 238), (237, 233, 223), min(1, max(0, (y - box[1]) / (box[3] - box[1])))))
    paper = column.resize((W, W)).convert("RGBA")
    mask = Image.new("L", (W, W), 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, radius, fill=255)
    canvas.paste(paper, (0, 0), mask)
    d = ImageDraw.Draw(canvas)
    d.rounded_rectangle(box, radius, outline=(214, 208, 195, 255), width=max(1, int(3 * u)))

    # Lines of text, one of them blacked out. Small sizes get thicker lines so they stay visible.
    bold = 1.35 if size <= 64 else 1.0
    x0, full = 100 * u + 0.22 * 824 * u, 0.56 * 824 * u
    grey, ink = (163, 158, 146, 255), (22, 24, 29, 255)
    for top, frac in ((0.27, 1.0), (0.38, 0.75), (0.65, 0.86), (0.76, 0.54)):
        h = 0.045 * 824 * u * bold
        y = 100 * u + top * 824 * u
        d.rounded_rectangle((x0, y, x0 + full * frac, y + h), h / 2, fill=grey)
    y = 100 * u + 0.48 * 824 * u
    d.rounded_rectangle((x0, y, x0 + full, y + 0.10 * 824 * u * (1.1 if bold > 1 else 1.0)), 12 * u, fill=ink)

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
    """660 x 400 points: a plain light background, a thin chevron between the two icons, one small line of help."""
    w, h = 660 * scale, 400 * scale
    img = Image.new("RGB", (w, h), (246, 246, 244))
    d = ImageDraw.Draw(img)
    cx, cy = 330 * scale, 185 * scale  # between the app and Applications, level with the icons
    a = 11 * scale
    d.line([(cx - a / 2, cy - a), (cx + a / 2, cy), (cx - a / 2, cy + a)], fill=(180, 179, 173), width=2 * scale, joint="curve")
    small = _font(12 * scale)
    note = "Drag Privatier into Applications. The first time, read First start."
    tw = d.textlength(note, font=small)
    d.text(((w - tw) / 2, 362 * scale), note, fill=(134, 134, 139), font=small)
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
