"""A fixed colored PNG for the headset (same input for both versions)."""
import sys
from PIL import Image, ImageDraw
im = Image.new('RGBA', (1600, 1600), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
d.pieslice((330, 60, 1270, 1000), 180, 360, fill=(120, 84, 52, 255))      # headband
d.rounded_rectangle((250, 560, 560, 1180), 120, fill=(40, 40, 46, 255))  # left cup
d.rounded_rectangle((1040, 560, 1350, 1180), 120, fill=(40, 40, 46, 255)) # right cup
d.ellipse((310, 650, 500, 1090), fill=(160, 40, 40, 255))
d.ellipse((1100, 650, 1290, 1090), fill=(160, 40, 40, 255))
d.rectangle((560, 1180, 1040, 1300), fill=(200, 170, 110, 255))          # mic arm
im.save(sys.argv[1])
