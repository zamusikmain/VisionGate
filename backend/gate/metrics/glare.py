import cv2
import numpy as np

def measure(gray):
    # A white label background is expected. Only wide bright gaps disrupting
    # neighboring dark bars contribute; this remains an advisory heuristic.
    if gray.shape[1] < 16 or gray.shape[0] < 8:
        return 0.0
    dark = np.mean(gray < 90, axis=0)
    bright = np.mean(gray >= 250, axis=0)
    gap = (bright > .95) & (dark < .01)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(gap.astype('uint8')[None,:])
    covered = 0
    for x, y, width, height, area in stats[1:]:
        if width > gray.shape[1]*.08 and x > 0 and x+width < len(dark) and dark[max(0,x-5):x].max() > .15 and dark[x+width:x+width+5].max() > .15:
            covered += width
    return float(covered/gray.shape[1])
