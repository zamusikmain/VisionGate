import math
import numpy as np

def measure(points):
    if len(points) != 4:
        return 0., 0.
    p = np.array(points, dtype=float)
    lengths = [np.linalg.norm(p[(i+1)%4]-p[i]) for i in range(4)]
    score = max(abs(lengths[0]-lengths[2])/max(lengths[0],lengths[2],1), abs(lengths[1]-lengths[3])/max(lengths[1],lengths[3],1))
    angle = math.degrees(math.atan2(*(p[1]-p[0])[::-1]))
    return float(angle), float(score)
