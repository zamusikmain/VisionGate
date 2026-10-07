import cv2

def measure(gray):
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())
