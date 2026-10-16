"""Draw the built-in tool images (paint brush, pencil, marker). Original artwork.

Each tool lies diagonally with its tip at the upper left, like the pen of the
built-in hand, so it looks natural moving over the drawing. The script prints
each tip position (fractions of the image) for tools.py.
"""
import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter

S = 4                                    # supersampling
ANGLE = 38                               # degrees below horizontal, tip at upper left
ASSETS = Path(__file__).resolve().parent.parent / 'assets'


def make(name, parts, length, size=(620, 470), tip=(46, 40)):
    """parts: [(x0, x1, half_width_at_x0, half_width_at_x1, colour)] along the tool axis
    (x = distance from the tip). Drawn as tapered quads, then rotated."""
    W, H = size
    img = Image.new('RGBA', (W * S, H * S), (0, 0, 0, 0))
    a = math.radians(ANGLE)
    ux, uy = math.cos(a), math.sin(a)            # along the tool
    nx, ny = -uy, ux                             # across

    def pt(x, y):
        return ((tip[0] + x * ux + y * nx) * S, (tip[1] + x * uy + y * ny) * S)

    shadow = Image.new('RGBA', img.size, (0, 0, 0, 0))
    ds = ImageDraw.Draw(shadow)
    for x0, x1, w0, w1, _ in parts:
        quad = [pt(x0, -w0), pt(x1, -w1), pt(x1, w1), pt(x0, w0)]
        ds.polygon([(x + 26 * S, y + 30 * S) for x, y in quad], fill=(0, 0, 0, 60))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(12 * S)))
    d = ImageDraw.Draw(img)
    for x0, x1, w0, w1, colour in parts:
        if callable(colour):
            colour(d, pt, x0, x1, w0, w1)
        else:
            d.polygon([pt(x0, -w0), pt(x1, -w1), pt(x1, w1), pt(x0, w0)], fill=colour)
    # A soft highlight along the upper side.
    hl = Image.new('RGBA', img.size, (0, 0, 0, 0))
    dh = ImageDraw.Draw(hl)
    for x0, x1, w0, w1, colour in parts:
        if x1 - x0 > 30 and not callable(colour):
            dh.polygon([pt(x0 + 6, -w0 * .55), pt(x1 - 6, -w1 * .55), pt(x1 - 6, -w1 * .25), pt(x0 + 6, -w0 * .25)],
                       fill=(255, 255, 255, 46))
    img.alpha_composite(hl.filter(ImageFilter.GaussianBlur(2 * S)))
    out = img.resize((W, H), Image.LANCZOS)
    out.save(ASSETS / f'{name}.png')
    print(name, 'tip', round(tip[0] / W, 3), round(tip[1] / H, 3))


def bristles(d, pt, x0, x1, w0, w1):
    # Bristle bundle: wet paint at the tip blending into natural hair.
    steps = 24
    for i in range(steps):
        f0, f1 = i / steps, (i + 1) / steps
        xa, xb = x0 + (x1 - x0) * f0, x0 + (x1 - x0) * f1
        # rounded, pointed bundle: widest near the ferrule
        wa = w1 * math.sin(min(1., .15 + f0 * 1.1) * math.pi / 2)
        wb = w1 * math.sin(min(1., .15 + f1 * 1.1) * math.pi / 2)
        t = min(1., f0 / .45)
        paint, hair = (38, 112, 196), (176, 132, 82)
        colour = tuple(round(paint[k] * (1 - t) + hair[k] * t) for k in range(3)) + (255,)
        d.polygon([pt(xa, -wa), pt(xb, -wb), pt(xb, wb), pt(xa, wa)], fill=colour)
    for k in range(-3, 4):                       # hair lines
        d.line([pt(x0 + 20, k * w1 / 5), pt(x1 - 2, k * w1 / 4.2)], fill=(120, 86, 50, 120), width=S)


make('default_brush', [
    (0, 70, 2, 17, bristles),
    (70, 128, 18, 19, (196, 200, 208, 255)),        # ferrule
    (88, 96, 19, 19, (150, 156, 166, 255)),          # crimp
    (110, 116, 19, 19, (150, 156, 166, 255)),
    (128, 300, 15, 11, (178, 52, 44, 255)),          # lacquered handle
    (300, 560, 11, 15, (196, 64, 52, 255)),
    (560, 572, 15, 13, (150, 40, 34, 255)),
], 572, size=(560, 420), tip=(30, 34))

make('default_pencil', [
    (0, 16, 0, 4, (40, 40, 44, 255)),                # graphite
    (16, 64, 4, 15, (232, 196, 150, 255)),           # sharpened wood
    (64, 470, 15, 15, (246, 192, 40, 255)),          # yellow body
    (470, 482, 15, 15, (170, 172, 178, 255)),        # metal band
    (482, 490, 16, 16, (140, 142, 150, 255)),
    (490, 520, 15, 14, (236, 132, 150, 255)),        # rubber
], 520, size=(520, 390), tip=(28, 30))

make('default_marker', [
    (0, 18, 4, 7, (24, 26, 30, 255)),                # felt tip
    (18, 52, 9, 16, (60, 64, 72, 255)),              # nose
    (52, 330, 20, 20, (238, 240, 244, 255)),         # white barrel
    (120, 250, 20.5, 20.5, (34, 38, 46, 255)),       # label band
    (330, 400, 21, 20, (30, 34, 40, 255)),           # cap end
], 400, size=(440, 340), tip=(30, 30))
