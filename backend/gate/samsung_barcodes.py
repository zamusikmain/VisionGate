"""Bounded local barcode search. No inferred digits, expected IDs or filename inputs."""
import cv2
import numpy as np
import zxingcpp

from .samsung import valid_imei

LINEAR_IMEI_FORMATS={'Code 128','Code 39','ITF'}


def scaled_barcodes(image):
    """One bounded full-frame fallback; original coordinates retained exactly."""
    from .samsung_preprocessing import scale2_bounded,variant_to_original
    pixels,matrix=scale2_bounded(image)
    if pixels is None:return []
    results=[];seen=set()
    for downscale in (False,True):
        for b in zxingcpp.read_barcodes(pixels,try_rotate=True,try_downscale=downscale,
                                      try_invert=True,return_errors=False):
            if not b.valid or str(b.format) not in LINEAR_IMEI_FORMATS or not valid_imei(b.text):continue
            points=[[p.x,p.y] for p in (b.position.top_left,b.position.top_right,b.position.bottom_right,b.position.bottom_left)]
            original=variant_to_original(points,matrix)
            signature=(b.text,str(original))
            if signature in seen:continue
            seen.add(signature);q=np.float32(original)
            results.append(dict(type=str(b.format),value=b.text,variant='full-scale2-bounded',
                bbox=[float(q[:,0].min()),float(q[:,1].min()),float(q[:,0].max()),float(q[:,1].max())],
                polygon=original,variant_polygon=points,original_to_variant=matrix,coordinate_space='original',
                region=None,source='barcode',recognizer='ZXing-C++',checksum_valid=True,imei_luhn_valid=True,
                quality='resampled_pixels',confidence=None,confidence_calibrated=False,
                processing='bicubic_scale2_max6000',independent_evidence=False))
    return results


def enhanced_barcodes(image,proposals=()):
    h,w=image.shape[:2];results=[];seen=set()
    def read(view,offset,method,scale=1.):
        if min(view.shape[:2])<8:return
        padded=cv2.copyMakeBorder(view,12,12,12,12,cv2.BORDER_CONSTANT,value=255 if view.ndim==2 else (255,255,255))
        for b in zxingcpp.read_barcodes(padded,formats=[zxingcpp.BarcodeFormat.Code128,zxingcpp.BarcodeFormat.Code39,zxingcpp.BarcodeFormat.ITF],
                try_rotate=True,try_downscale=False,binarizer=zxingcpp.Binarizer.GlobalHistogram,return_errors=False):
            if not b.valid or not valid_imei(b.text):continue
            points=np.float32([[p.x,p.y] for p in (b.position.top_left,b.position.top_right,b.position.bottom_right,b.position.bottom_left)])
            points=(points-12)/scale+np.float32(offset)
            bbox=[int(points[:,0].min()),int(points[:,1].min()),int(points[:,0].max()),int(points[:,1].max())]
            signature=(b.text,method)
            if signature in seen:continue
            seen.add(signature)
            results.append(dict(type=str(b.format),value=b.text,variant=method,bbox=bbox,
                polygon=points.round().astype(int).tolist(),region=None,source='barcode',checksum_valid=True,
                imei_luhn_valid=True,quality='native_pixels' if scale==1 else 'resampled_pixels',padding='12px white quiet zone; original image unchanged'))
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
    read(gray,(0,0),'native-global')
    # Whole-image overlapping tiles avoid losing small bars during decoder downscaling.
    for iy,yfrac in enumerate((0.,.25,.5)):
        for ix,xfrac in enumerate((0.,.25,.5)):
            x=int(w*xfrac);y=int(h*yfrac);view=gray[y:min(h,y+round(h*.5)),x:min(w,x+round(w*.5))]
            read(view,(x,y),f'native-tile-{iy}-{ix}')
    # Split dense rows: tightly adjacent IMEI1/IMEI2 symbols can defeat multi-code search.
    for i,p in enumerate(proposals[:4]):
        x1,y1,x2,y2=p['bbox'];crop=gray[max(0,y1):min(h,y2),max(0,x1):min(w,x2)]
        if not crop.size:continue
        for j,fraction in enumerate((0.,.25,.5)):
            left=round(crop.shape[1]*fraction);view=crop[:,left:min(crop.shape[1],left+round(crop.shape[1]*.5))]
            for scale in (1.,2.):
                if max(view.shape)*scale>3600:continue
                variant=view if scale==1 else cv2.resize(view,None,fx=scale,fy=scale,interpolation=cv2.INTER_CUBIC)
                read(variant,(x1+left,y1),f'roi{i}-split{j}-x{scale:g}',scale)
    return results
