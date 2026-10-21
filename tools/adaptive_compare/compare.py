"""Side-by-side sheet and pixel differences: old (top) vs new (bottom)."""
import json, sys
from pathlib import Path
from PIL import Image, ImageChops
old, new, out = map(Path, sys.argv[1:4])
rows, report = [], []
for i in range(12):
    a = Image.open(old / f'frame_{i:02d}.png').convert('RGBA'); b = Image.open(new / f'frame_{i:02d}.png').convert('RGBA')
    diff = ImageChops.difference(a, b).convert('L')
    changed = sum(diff.point(lambda v: 255 if v > 8 else 0).histogram()[255:])
    report.append(f'frame {i:02d}: {changed} pixels differ')
    rows.append((a, b))
pick = [rows[i] for i in (1, 3, 5, 7, 9, 11)]
W = sum(a.width for a, _ in pick) // 2; H = pick[0][0].height // 2
sheet = Image.new('RGB', (W, H * 2), 'white')
x = 0
for a, b in pick:
    for k, im in enumerate((a, b)):
        bg = Image.new('RGBA', im.size, (255, 255, 255, 255)); bg.alpha_composite(im)
        sheet.paste(bg.convert('RGB').resize((im.width // 2, im.height // 2)), (x, k * H))
    x += a.width // 2
sheet.save(out / 'sheet.png')
report.append('old ' + (old / 'info.json').read_text().replace('\n', ''))
report.append('new ' + (new / 'info.json').read_text().replace('\n', ''))
(out / 'report.txt').write_text('\n'.join(report) + '\n'); print('\n'.join(report))
