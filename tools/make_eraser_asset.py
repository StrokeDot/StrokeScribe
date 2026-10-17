"""Draw the built-in eraser image (assets/default_eraser.png). Original artwork."""
import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter

S = 4                                   # supersampling
W, H = 560, 420
img = Image.new('RGBA', (W * S, H * S), (0, 0, 0, 0))


def rot(points, angle, cx, cy):
    a = math.radians(angle)
    return [((x - cx) * math.cos(a) - (y - cy) * math.sin(a) + cx,
             (x - cx) * math.sin(a) + (y - cy) * math.cos(a) + cy) for x, y in points]


def poly(draw, pts, fill):
    draw.polygon([(x * S, y * S) for x, y in pts], fill=fill)


angle = -32
cx, cy = 300, 210
# Block: rubber end (pink) at the left, paper sleeve (blue) at the right.
x0, x1, y0, y1 = 70, 500, 150, 260
depth = 26                              # visible bottom face
shadow = Image.new('RGBA', img.size, (0, 0, 0, 0))
ds = ImageDraw.Draw(shadow)
poly(ds, rot([(x0 + 14, y0 + 30), (x1 + 14, y0 + 30), (x1 + 14, y1 + depth + 22), (x0 + 14, y1 + depth + 22)],
             angle, cx, cy), (0, 0, 0, 70))
shadow = shadow.filter(ImageFilter.GaussianBlur(14 * S))
img.alpha_composite(shadow)
d = ImageDraw.Draw(img)
split = 215
# bottom faces (darker)
poly(d, rot([(x0, y1), (split, y1), (split, y1 + depth), (x0 + 6, y1 + depth)], angle, cx, cy), (205, 98, 118, 255))
poly(d, rot([(split, y1), (x1, y1), (x1, y1 + depth), (split, y1 + depth)], angle, cx, cy), (36, 74, 140, 255))
# top faces
poly(d, rot([(x0, y0), (split, y0), (split, y1), (x0, y1)], angle, cx, cy), (244, 142, 160, 255))
poly(d, rot([(split, y0), (x1, y0), (x1, y1), (split, y1)], angle, cx, cy), (58, 110, 196, 255))
# sleeve stripe and highlight
poly(d, rot([(split + 30, y0), (split + 52, y0), (split + 52, y1), (split + 30, y1)], angle, cx, cy), (236, 242, 250, 255))
poly(d, rot([(x0 + 8, y0 + 10), (split - 8, y0 + 10), (split - 8, y0 + 22), (x0 + 8, y0 + 22)], angle, cx, cy),
     (252, 186, 198, 255))
# rubbed, rounded tip edge
poly(d, rot([(x0 - 6, y0 + 8), (x0, y0), (x0, y1 + depth), (x0 - 6, y1 + depth - 8)], angle, cx, cy),
     (226, 118, 138, 255))
out = img.resize((W, H), Image.LANCZOS)
target = Path(__file__).resolve().parent.parent / 'assets' / 'default_eraser.png'
out.save(target)
tip = rot([(x0 - 3, y1 + depth - 4)], angle, cx, cy)[0]
print('saved', target, 'tip', round(tip[0] / W, 3), round(tip[1] / H, 3))
