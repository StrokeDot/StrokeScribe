"""Builds assets/font_previews/<slug>.png: each font's name written in that font (exp.15).

The font list shows these, so a font can be seen before it is downloaded (as in Filmora).
White text on transparent, drawn at 2x for sharp screens; the app tints it to the theme.
Run when fonts are added to font_library.FONT_GROUPS:  python tools/make_font_previews.py
(needs the GitHub CLI `gh` or internet access to github.com/google/fonts).
"""
import json
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PIL import Image, ImageDraw, ImageFont  # noqa: E402
from font_library import STARTER_FONTS, font_slug  # noqa: E402

OUT = ROOT / 'assets' / 'font_previews'
HEIGHT = 44          # pixels (2x of the 22 px row text)


def listing(slug):
    for licence in ('ofl', 'apache', 'ufl'):
        try:
            out = subprocess.run(['gh', 'api', f'repos/google/fonts/contents/{licence}/{slug}'],
                                 capture_output=True, text=True, timeout=60)
            if out.returncode == 0:
                return json.loads(out.stdout)
        except FileNotFoundError:
            break
    raise RuntimeError(f'not found: {slug}')


def guess_file(family, folder):
    """Without the listing: try the usual file names in google/fonts."""
    slug, name = font_slug(family), family.replace(' ', '')
    for licence in ('ofl', 'apache', 'ufl'):
        for file in (f'{name}-Regular.ttf', f'{name}%5Bwght%5D.ttf', f'{name}.ttf',
                     f'{name}%5Bwdth,wght%5D.ttf', f'{name}%5Bopsz,wdth,wght%5D.ttf',
                     f'{name}%5Bopsz,wght%5D.ttf', f'{name}-Regular.otf'):
            url = f'https://raw.githubusercontent.com/google/fonts/main/{licence}/{slug}/{file}'
            try:
                with urllib.request.urlopen(url, timeout=30) as r:
                    data = r.read()
            except Exception:
                continue
            path = Path(folder) / file.replace('%5B', '[').replace('%5D', ']')
            path.write_bytes(data)
            return path
    raise RuntimeError(f'not found: {slug}')


def font_file(family, folder):
    try:
        found = listing(font_slug(family))
    except RuntimeError:
        return guess_file(family, folder)
    files = [f for f in found if f['name'].lower().endswith(('.ttf', '.otf'))]
    regular = [f for f in files if 'italic' not in f['name'].lower()]
    pick = sorted(regular or files, key=lambda f: ('Regular' not in f['name'], len(f['name'])))[0]
    path = Path(folder) / pick['name']
    with urllib.request.urlopen(pick['download_url'], timeout=60) as r:
        path.write_bytes(r.read())
    return path


def render(family, path):
    size = 30

    def load(sz):
        f = ImageFont.truetype(str(path), sz)
        try:
            f.set_variation_by_name('Regular')          # variable fonts: the normal weight
        except Exception:
            pass
        return f
    font = load(size)
    for _ in range(12):                                   # fit the height, whatever the font
        l, t, r, b = font.getbbox(family)
        if b - t <= HEIGHT - 6 or size < 14:
            break
        size -= 2; font = load(size)
    l, t, r, b = font.getbbox(family)
    w = min(520, r - l + 8)
    img = Image.new('LA', (w, HEIGHT), (255, 0))
    ImageDraw.Draw(img).text((4 - l, (HEIGHT - (b - t)) / 2 - t), family, font=font, fill=(255, 255))
    return img


def main(families=STARTER_FONTS):
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        for family in families:
            target = OUT / f'{font_slug(family)}.png'
            if target.exists():
                continue
            try:
                render(family, font_file(family, tmp)).save(target, optimize=True)
                print('ok', family)
            except Exception as exc:
                print('FAILED', family, exc)


if __name__ == '__main__':
    main()
