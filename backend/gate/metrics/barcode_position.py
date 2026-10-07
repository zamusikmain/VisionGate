def measure(box, shape, margin):
    h,w = shape[:2]
    x1,y1,x2,y2 = box
    distance = min(x1/w,y1/h,(w-x2)/w,(h-y2)/h)
    return distance, distance < margin, x1 <= 1 or y1 <= 1 or x2 >= w-1 or y2 >= h-1
