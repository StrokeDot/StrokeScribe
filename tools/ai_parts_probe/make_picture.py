"""A shaded cartoon object (two ear cups, a band, speakers) to try the part finder on."""
import sys
from PIL import Image, ImageDraw, ImageFilter
W, H = 900, 700
im = Image.new('RGBA', (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
d.arc((170, 40, 730, 600), 180, 360, fill=(222, 210, 180, 255), width=70)       # band
for x in (120, 560):
    d.rounded_rectangle((x, 300, x + 220, 640), 90, fill=(232, 222, 196, 255))   # cushions
    d.ellipse((x + 40, 350, x + 180, 590), fill=(60, 50, 40, 255) if x < 400 else (170, 120, 60, 255))
    d.ellipse((x + 75, 390, x + 145, 460), fill=(30, 30, 30, 255))                # speakers
    d.ellipse((x + 75, 480, x + 145, 550), fill=(30, 30, 30, 255))
shade = Image.new('L', (W, H), 0); ImageDraw.Draw(shade).ellipse((-200, -100, 600, 900), fill=60)
shade = shade.filter(ImageFilter.GaussianBlur(80))
dark = Image.new('RGBA', (W, H), (0, 0, 0, 255)); dark.putalpha(shade)
out = im.copy(); out.alpha_composite(dark); out.putalpha(im.getchannel('A'))
out.save(sys.argv[1])
