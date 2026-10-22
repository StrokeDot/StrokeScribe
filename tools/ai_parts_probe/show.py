"""Colour a label image so the parts can be seen."""
import colorsys, random, sys
import numpy as np
from PIL import Image
labels = np.asarray(Image.open(sys.argv[1]))
random.seed(4)
pal = np.zeros((int(labels.max()) + 1, 3), np.uint8); pal[0] = 255
for i in range(1, len(pal)):
    pal[i] = [int(c * 255) for c in colorsys.hsv_to_rgb(random.random(), .6, .95)]
Image.fromarray(pal[labels]).save(sys.argv[2])
