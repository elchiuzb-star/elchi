"""Turn raw emulator captures into Play-compliant store screenshots.

Modern phone screens are around 9:20, but Play caps phone screenshots at 9:16.
Cropping to fit would cut away app content, so each capture is instead placed on
a branded 1080x1920 canvas with a caption — which satisfies the ratio and looks
deliberate rather than like a raw grab.

    python scripts/make_store_screenshots.py IN_DIR OUT_DIR

Captions are matched by filename prefix (see CAPTIONS); anything unmatched is
framed without one.
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

CANVAS = (1080, 1920)
INK = (13, 17, 23)
FG = (255, 255, 255)
MUTED = (150, 160, 175)
ACCENT = (27, 79, 216)

# Filename prefix -> (headline, supporting line)
CAPTIONS = {
    "1-home": ("Yuk jo'natish", "Qayerdan qayerga — bir necha qadamda"),
    "2-menu": ("Hammasi bir joyda", "Buyurtmalar, bildirishnomalar, profil"),
    "3-cities": ("Barcha viloyatlar", "Shaharlararo yo'nalishlar"),
    "4-map": ("Aniq manzil", "Xaritadan tanlang yoki qidiring"),
    "5-settings": ("To'liq nazorat", "Til, bildirishnoma va hisob sozlamalari"),
    "6-offers": ("Narxni siz tanlaysiz", "Haydovchilar taklif qiladi"),
    "7-driver": ("Haydovchilar uchun", "Yo'nalishingiz bo'yicha buyurtmalar"),
}

FONT_BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
FONT_REG = "/System/Library/Fonts/Supplemental/Arial.ttf"
FONT_FALLBACK = "/Library/Fonts/Arial Unicode.ttf"


def load_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    for candidate in (path, FONT_FALLBACK):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def rounded(img: Image.Image, radius: int) -> Image.Image:
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([(0, 0), img.size], radius=radius, fill=255)
    out = img.convert("RGBA")
    out.putalpha(mask)
    return out


def frame(src: Path, dst: Path) -> None:
    shot = Image.open(src).convert("RGB")

    canvas = Image.new("RGB", CANVAS, INK)
    draw = ImageDraw.Draw(canvas)

    key = next((k for k in CAPTIONS if src.stem.startswith(k)), None)
    headline, sub = CAPTIONS.get(key, ("", ""))

    top = 60
    if headline:
        draw.text((64, top), headline, font=load_font(FONT_BOLD, 62), fill=FG)
        draw.text((64, top + 82), sub, font=load_font(FONT_REG, 34), fill=MUTED)
        # A short accent rule ties the caption to the brand without a gradient.
        draw.rectangle([(64, top + 148), (64 + 96, top + 152)], fill=ACCENT)
        device_top = top + 200
    else:
        device_top = 90

    # Scale the capture to fit the remaining space, preserving its aspect ratio.
    avail_h = CANVAS[1] - device_top - 60
    avail_w = CANVAS[0] - 128
    scale = min(avail_w / shot.width, avail_h / shot.height)
    size = (int(shot.width * scale), int(shot.height * scale))
    shot = shot.resize(size, Image.LANCZOS)
    shot = rounded(shot, 28)

    x = (CANVAS[0] - size[0]) // 2
    canvas.paste(shot, (x, device_top), shot)

    dst.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(dst, "PNG", optimize=True)
    print(f"  {dst.name}  {CANVAS[0]}x{CANVAS[1]}")


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    src_dir, out_dir = Path(sys.argv[1]), Path(sys.argv[2])
    shots = sorted(src_dir.glob("*.png"))
    if not shots:
        raise SystemExit(f"No PNGs in {src_dir}")
    print(f"Framing {len(shots)} screenshot(s) to {CANVAS[0]}x{CANVAS[1]} (9:16):")
    for shot in shots:
        frame(shot, out_dir / shot.name)


if __name__ == "__main__":
    main()
