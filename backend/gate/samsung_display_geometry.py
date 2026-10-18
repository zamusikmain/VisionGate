"""Scale-normalized display-boundary candidates; no names, IDs, labels or models.

Geometry alone never proves screen recapture. A confirmed finding additionally
requires two explicit gallery controls inside the same foreground boundary.
"""
import cv2
import numpy as np
import re

def display_boundaries(image):
    h,w=image.shape[:2];scale=1200/max(h,w)
    gray=cv2.cvtColor(cv2.resize(image,(round(w*scale),round(h*scale))),cv2.COLOR_BGR2GRAY)
    sh,sw=gray.shape
    edges=cv2.Canny(gray,50,130)
    nearby_dark=cv2.dilate((gray<90).astype('uint8'),np.ones((3,3),np.uint8))
    lines=cv2.HoughLinesP(edges,1,np.pi/360,threshold=max(30,round(sh*.04)),
                          minLineLength=round(sh*.4),maxLineGap=round(sh*.08))
    if lines is None:return []
    sides=[]
    for row in np.asarray(lines).reshape(-1,4):
        a,b=np.asarray(row[:2],float),np.asarray(row[2:],float)
        if a[1]>b[1]:a,b=b,a
        if b[1]-a[1]<sh*.45 or abs(b[0]-a[0])>(b[1]-a[1])*.45:continue
        mask=np.zeros_like(gray);cv2.line(mask,tuple(a.astype(int)),tuple(b.astype(int)),255,7)
        # A detected edge straddles both colours. Include its immediate dark
        # neighbour instead of depending on which Canny pixel was selected.
        if np.mean(nearby_dark[mask>0])<.55:continue
        sides.append((a,b))
    sides=sorted(sides,key=lambda p:p[1][1]-p[0][1],reverse=True)[:30]
    candidates=[]
    for i,left in enumerate(sides):
        for right in sides[i+1:]:
            if np.mean([p[0] for p in left])>np.mean([p[0] for p in right]):leftside,rightside=right,left
            else:leftside,rightside=left,right
            a,d=leftside;b,c=rightside
            if min(b[0]-a[0],c[0]-d[0])<sw*.22:continue
            if abs(a[1]-b[1])>sh*.18 or abs(c[1]-d[1])>sh*.18:continue
            q=np.float32([a,b,c,d]);area=cv2.contourArea(q)
            if not cv2.isContourConvex(q) or not .28<=area/(sh*sw)<=.96:continue
            width=(np.linalg.norm(b-a)+np.linalg.norm(c-d))/2
            height=(np.linalg.norm(d-a)+np.linalg.norm(c-b))/2
            if not 1.3<=height/max(1,width)<=3.8:continue
            # Both observed borders must enclose the foreground, not a small
            # phone elsewhere in the scene. No pixel-position template is used.
            if cv2.pointPolygonTest(q,(sw/2,sh/2),False)<0:continue
            original=q/scale
            candidates.append(dict(polygon=original.round().astype(int).tolist(),area_ratio=round(area/(sh*sw),4),
                source='paired_observed_dark_display_sides',semantic_status='CANDIDATE_ONLY'))
    selected=[]
    for c in sorted(candidates,key=lambda p:p['area_ratio'],reverse=True):
        q=np.float32(c['polygon'])
        if any(cv2.intersectConvexConvex(q,np.float32(p['polygon']))[0]/max(1,min(cv2.contourArea(q),cv2.contourArea(np.float32(p['polygon']))))>.85 for p in selected):continue
        selected.append(c)
        if len(selected)>=3:break
    return selected

def framed_gallery_evidence(ocr,boundaries):
    for frame in boundaries:
        q=np.float32(frame['polygon']);minimum=q[:,1].min();height=q[:,1].max()-minimum
        headers=[];controls=[]
        for reading in ocr.get('reads',[]):
            for line in reading.get('lines',[]):
                words=line.get('words',[])
                if not words:continue
                box=[min(w['x'] for w in words),min(w['y'] for w in words),max(w['x']+w['width'] for w in words),max(w['y']+w['height'] for w in words)]
                corners=[(box[0],box[1]),(box[2],box[1]),(box[2],box[3]),(box[0],box[3])]
                if any(cv2.pointPolygonTest(q,p,False)<0 for p in corners):continue
                text=line['text'].strip();digits=re.sub(r'\D','',text)
                if box[3]<=minimum+.3*height:
                    if re.match(r'^\+\d',text) and 7<=len(digits)<=15:headers.append(box)
                    if re.search(r'\b[0-9\u0417]{1,3}\s+(?:\u0444\u043e\u0442\u043e|photos?)\b',text,re.I):controls.append(box)
                # A reply input at the bottom is another explicit viewer
                # control. It is never a device identifier or watermark cue.
                if box[1]>=minimum+.65*height and re.match(r'^(?:reply|\u043e\u0442\u0432\u0435\u0442\u0438\u0442\u044c)\b',text,re.I):controls.append(box)
        for a in headers:
            for b in controls:
                if a[3]<=b[1] and abs((a[0]+a[2]-b[0]-b[2])/2)<(q[:,0].max()-q[:,0].min())*.3:
                    return dict(code='FOREGROUND_DISPLAY_GALLERY',source='gallery_UI_inside_observed_display_boundary',
                        regions=[a,b],display_polygon=frame['polygon'],coordinate_space='original',
                        reason='Two distinct gallery controls are contained above the displayed content within the same large foreground display boundary. Border geometry alone is not used as a defect.')
    return None

def read_framed_ui(image,boundaries,cache_dir=None):
    """One observed frame, two fixed UI bands, mapped back to original pixels.

    This is automatic geometric rectification, not a manually supplied ROI.
    No inpainting, identifier reconstruction or watermark removal is performed.
    """
    from .samsung_vision import rectify
    from .samsung_preprocessing import variant_to_original
    from .samsung_screen import read_screen_ui
    if not boundaries:return dict(status='SKIPPED_NO_DISPLAY_BOUNDARY',reads=[])
    frame=boundaries[0];crop,matrix=rectify(image,frame['polygon']);h=crop.shape[0];reads=[]
    for start,end in [(0,round(h*.3)),(round(h*.65),h)]:
        # Existing Windows OCR works locally on each band and supplies pixel
        # coordinates. The crop offset is part of the inverse homography.
        offset=np.array([[1.,0.,0.],[0.,1.,-start],[0.,0.,1.]])
        result=read_screen_ui(crop[start:end],cache_dir)
        for reading in result.get('reads',[]):
            for line in reading.get('lines',[]):
                for word in line.get('words',[]):
                    x,y,w,hh=[word[k] for k in ('x','y','width','height')]
                    q=np.asarray(variant_to_original([[x,y],[x+w,y],[x+w,y+hh],[x,y+hh]],offset@matrix))
                    word.update(x=float(q[:,0].min()),y=float(q[:,1].min()),width=float(np.ptp(q[:,0])),height=float(np.ptp(q[:,1])))
            reads.append(reading)
    return dict(status='OK' if reads else 'UNAVAILABLE',reads=reads,coordinate_space='original',
                source='automatic_display_rectification_ui_bands',manual_region=False,
                confidence_calibrated=False,variant_count=2)
