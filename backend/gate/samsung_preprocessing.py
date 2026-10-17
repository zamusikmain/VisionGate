"""Fixed generic transforms validated locally; no watermark-specific processing."""
import cv2
import numpy as np

VERSION='samsung-preprocessing-1'


def normalize_illumination(image):
    lab=cv2.cvtColor(image,cv2.COLOR_BGR2LAB)
    light=lab[:,:,0].astype(np.float32);h,w=light.shape
    small=cv2.resize(light,(max(8,round(w*256/max(h,w))),max(8,round(h*256/max(h,w)))))
    background=cv2.resize(cv2.GaussianBlur(small,(0,0),8),(w,h))
    lab[:,:,0]=np.uint8(np.clip(light*np.median(background)/np.maximum(background,16),0,255))
    return cv2.cvtColor(lab,cv2.COLOR_LAB2BGR)


def scale2_bounded(image,max_side=6000):
    h,w=image.shape[:2];factor=min(2.,max_side/max(h,w))
    # This is an upscale fallback, never a downscale of an already large image.
    if factor<=1:return None,None
    pixels=cv2.resize(image,None,fx=factor,fy=factor,interpolation=cv2.INTER_CUBIC)
    return pixels,np.diag([pixels.shape[1]/w,pixels.shape[0]/h,1.]).tolist()


def variant_to_original(points,matrix):
    return cv2.perspectiveTransform(np.float32(points).reshape(1,-1,2),
                                    np.linalg.inv(np.float64(matrix)))[0].round(3).tolist()


def roi_variant_matrix(rectification,turns,width,height,variant_width,variant_height):
    rotations=[[[1,0,0],[0,1,0],[0,0,1]],
               [[0,1,0],[-1,0,width-1],[0,0,1]],
               [[-1,0,width-1],[0,-1,height-1],[0,0,1]],
               [[0,-1,height-1],[1,0,0],[0,0,1]]]
    rw,rh=(height,width) if turns%2 else (width,height)
    scale=np.diag([variant_width/rw,variant_height/rh,1.])
    return (scale@np.float64(rotations[turns])@rectification).tolist()
