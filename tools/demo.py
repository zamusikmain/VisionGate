"""Generate explicitly synthetic regression samples, never customer accuracy data."""
from pathlib import Path
import cv2
import numpy as np
import zxingcpp
from PIL import Image

def clean_image():
    code=zxingcpp.create_barcode('ABC123456',zxingcpp.BarcodeFormat.Code128)
    bars=np.asarray(code.to_image(scale=4))
    if bars.ndim==3: bars=cv2.cvtColor(bars,cv2.COLOR_RGB2GRAY)
    image=np.full((600,1000),210,np.uint8)
    h,w=bars.shape
    image[200:200+h,(1000-w)//2:(1000+w)//2]=bars
    return cv2.cvtColor(image,cv2.COLOR_GRAY2BGR)

def main():
    root=Path('demo/synthetic')
    (root/'good').mkdir(parents=True,exist_ok=True);(root/'bad').mkdir(exist_ok=True)
    image=clean_image()
    cv2.imwrite(str(root/'good/clean-code128.png'),image)
    cv2.imwrite(str(root/'bad/blur.png'),cv2.GaussianBlur(image,(41,41),12))
    cv2.imwrite(str(root/'bad/dark.png'),(image*.1).astype('uint8'))
    cv2.imwrite(str(root/'bad/no-barcode.png'),np.full_like(image,180))
    (root/'NOTICE.txt').write_text('SYNTHETIC DEMO ONLY. These labels test controlled scenarios, not target-domain accuracy.')

if __name__=='__main__':main()
