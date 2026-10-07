def measure(box, shape):
    h, w = shape[:2]
    x1,y1,x2,y2 = box
    area = max(0,x2-x1)*max(0,y2-y1)
    return area, area/(w*h), (x2-x1)/w, (y2-y1)/h
