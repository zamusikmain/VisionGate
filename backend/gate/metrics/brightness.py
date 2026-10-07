import numpy as np

def measure(gray):
    return float(gray.mean()), float(np.mean(gray < 25)), float(np.mean(gray >= 250))
