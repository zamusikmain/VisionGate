"""Local geometric proposals, rectification and bounded image variants.

Scores rank proposals; they are not calibrated probabilities or proof of a box.
"""
import cv2
import numpy as np


def ordered_quad(points):
    points = np.asarray(points, dtype=np.float32).reshape(4, 2)
    center = points.mean(axis=0)
    points = points[np.argsort(np.arctan2(points[:, 1]-center[1], points[:, 0]-center[0]))]
    points = np.roll(points, -np.argmin(points.sum(axis=1)), axis=0)
    return points.astype(np.float32)


def rectify(image, quad):
    q = ordered_quad(quad)
    w = max(np.linalg.norm(q[1]-q[0]), np.linalg.norm(q[2]-q[3]))
    h = max(np.linalg.norm(q[3]-q[0]), np.linalg.norm(q[2]-q[1]))
    bounded=min(1.,2400/max(w,h))
    w, h = max(16, round(w*bounded)), max(16, round(h*bounded))
    matrix = cv2.getPerspectiveTransform(q, np.float32([[0,0],[w-1,0],[w-1,h-1],[0,h-1]]))
    crop = cv2.warpPerspective(image, matrix, (w,h), flags=cv2.INTER_CUBIC,
                               borderMode=cv2.BORDER_REPLICATE)
    return crop, matrix


def _iou(a, b):
    x=max(0,min(a[2],b[2])-max(a[0],b[0])); y=max(0,min(a[3],b[3])-max(a[1],b[1]))
    return x*y/max(1,(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-x*y)


def locate_labels(image, barcode_boxes=(), limit=4):
    h,w=image.shape[:2]; scale=min(1.,1500/max(h,w))
    small=cv2.resize(image,(round(w*scale),round(h*scale)))
    gray=cv2.cvtColor(small,cv2.COLOR_BGR2GRAY); hsv=cv2.cvtColor(small,cv2.COLOR_BGR2HSV)
    light=((hsv[:,:,1]<100)&(gray>115)).astype('uint8')*255
    masks=[('light_boundary',cv2.morphologyEx(light,cv2.MORPH_CLOSE,np.ones((5,9),np.uint8)))]
    # Dense horizontal text/bar groups supply proposals when paper joins the white box.
    dark=(gray<100).astype('uint8')*255
    count,components,stats,_=cv2.connectedComponentsWithStats(dark)
    keep=np.zeros(count,dtype=np.uint8)
    for i,(cx,cy,cw,ch,area) in enumerate(stats[1:],1):
        if 2<=ch<=gray.shape[0]*.09 and 1<=cw<=gray.shape[1]*.18 and 2<=area<=gray.size*.002:
            keep[i]=255
    dark=keep[components]
    text=cv2.morphologyEx(dark,cv2.MORPH_CLOSE,cv2.getStructuringElement(cv2.MORPH_RECT,(25,13)))
    masks.append(('text_cluster',text))
    edges=cv2.Canny(gray,45,130)
    edges=cv2.morphologyEx(edges,cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
    masks.append(('edge_boundary',edges))
    proposals=[]
    for method,mask in masks:
        contours,_=cv2.findContours(mask,cv2.RETR_LIST if method=='edge_boundary' else cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        for c in contours:
            area=cv2.contourArea(c)
            if area<gray.size*.002: continue
            rect=cv2.minAreaRect(c); a,b=rect[1]
            if min(a,b)<12 or max(a,b)/min(a,b)>10: continue
            if method=='edge_boundary':
                if area/max(1,a*b)<.7 or max(a,b)/min(a,b)<1.8:continue
            # Preserve perspective corners where an actual convex quadrilateral
            # is observed. minAreaRect alone only corrects in-plane rotation.
            approx=cv2.approxPolyDP(c,.02*cv2.arcLength(c,True),True)
            perspective=len(approx)==4 and cv2.isContourConvex(approx) and area/max(1,a*b)>.65
            q=ordered_quad(approx.reshape(4,2) if perspective else cv2.boxPoints(rect))/scale
            if np.linalg.norm(q[1]-q[0])<np.linalg.norm(q[3]-q[0]):
                q=np.roll(q,-1,axis=0)
            xs,ys=q[:,0],q[:,1]
            bbox=[max(0,int(xs.min())),max(0,int(ys.min())),min(w,int(xs.max()+1)),min(h,int(ys.max()+1))]
            ratio=area/gray.size
            if ratio>.65: continue
            x1,y1,x2,y2=bbox
            if x2<=x1 or y2<=y1:continue
            crop=gray[round(y1*scale):max(round(y1*scale)+1,round(y2*scale)),round(x1*scale):max(round(x1*scale)+1,round(x2*scale))]
            if not crop.size:continue
            dark_ratio=float(np.mean(crop<100)); contrast=float(crop.std())
            if not .015<dark_ratio<.65 or contrast<18:continue
            horizontal=max(a,b)/min(a,b)
            # Factory stickers generally combine dense text, a light surface and codes.
            contained=sum(x1 <= (b[0]+b[2])/2 <= x2 and y1 <= (b[1]+b[3])/2 <= y2 for b in barcode_boxes)
            score=contained*3+min(horizontal,5)*.2+min(contrast/60,1)+min(ratio/.03,1)
            if method=='light_boundary':score+=.4
            if method=='edge_boundary':score+=.5
            if ratio>.2:score-=3
            proposals.append(dict(polygon=q.round().astype(int).tolist(),bbox=bbox,score=round(score,3),
                                  method=method,code_centers=contained,
                                  geometry='observed_quadrilateral' if perspective else 'minimum_rotated_rectangle',
                                  touches_border=x1<=2 or y1<=2 or x2>=w-2 or y2>=h-2))
    context_boxes=list(barcode_boxes)
    if len(barcode_boxes)>1:
        context_boxes.insert(0,[min(b[0] for b in barcode_boxes),min(b[1] for b in barcode_boxes),
                                max(b[2] for b in barcode_boxes),max(b[3] for b in barcode_boxes)])
    for box in context_boxes:
        x1,y1,x2,y2=box; bw,bh=x2-x1,y2-y1
        # A fallback is explicitly incomplete; it cannot prove a whole sticker.
        x1=max(0,int(x1-bw*.18));x2=min(w,int(x2+bw*.18))
        y1=max(0,int(y1-max(bh*2.6,bw*.3)));y2=min(h,int(y2+max(bh*1.8,bw*.15)))
        q=[[x1,y1],[x2-1,y1],[x2-1,y2-1],[x1,y2-1]]
        proposals.append(dict(polygon=q,bbox=[x1,y1,x2,y2],score=3.5,method='barcode_context',code_centers=1,
                              touches_border=x1==0 or y1==0 or x2==w or y2==h))
    selected=[]
    for p in sorted(proposals,key=lambda p:p['score'],reverse=True):
        if not any(_iou(p['bbox'],q['bbox'])>.72 for q in selected):selected.append(p)
        if len(selected)==limit:break
    return selected


def variants(crop, orientations=(0,)):
    # Keep original pixels and provenance. No inpainting/watermark removal.
    for turns in orientations:
        rotated=np.ascontiguousarray(np.rot90(crop,turns))
        gray=cv2.cvtColor(rotated,cv2.COLOR_BGR2GRAY) if rotated.ndim==3 else rotated
        scale=min(4.,max(1.,1600/max(gray.shape)),2400/max(gray.shape))
        up=cv2.resize(gray,None,fx=scale,fy=scale,interpolation=cv2.INTER_CUBIC)
        yield f'r{turns*90}-gray',up
        yield f'r{turns*90}-clahe',cv2.createCLAHE(2.,(8,8)).apply(up)
        yield f'r{turns*90}-binary',cv2.adaptiveThreshold(up,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,cv2.THRESH_BINARY,31,9)


def diagnostic(image, proposals, problems=(), boxes=()):
    output=image.copy();h,w=image.shape[:2]
    thickness=max(2,round(max(h,w)/650))
    for i,p in enumerate(proposals):
        cv2.polylines(output,[np.int32(p['polygon'])],True,(0,180,255),thickness)
        x,y=p['bbox'][:2]
        cv2.putText(output,f'candidate {i+1}: {p["method"]}',(max(0,x),max(25,y)),
                    cv2.FONT_HERSHEY_SIMPLEX,max(.45,max(h,w)/2600),(0,120,255),thickness)
    for p in problems:
        x1,y1,x2,y2=[int(round(v)) for v in p['bbox']];cv2.rectangle(output,(x1,y1),(x2,y2),(0,0,255),thickness)
        cv2.putText(output,p['code'],(x1,max(25,y1)),cv2.FONT_HERSHEY_SIMPLEX,.6,(0,0,255),thickness)
    for polygon in boxes:
        cv2.polylines(output,[np.int32(polygon)],True,(255,120,0),thickness)
    return output


def phone_frame_candidates(image):
    """Phone-shaped dark-border quadrilaterals; never proof of screen recapture alone."""
    h,w=image.shape[:2];scale=min(1.,1000/max(h,w))
    small=cv2.resize(image,(round(w*scale),round(h*scale)))
    gray=cv2.cvtColor(small,cv2.COLOR_BGR2GRAY)
    edge=cv2.Canny(gray,50,130)
    contours,_=cv2.findContours(edge,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
    out=[]
    for c in sorted(contours,key=cv2.contourArea,reverse=True)[:100]:
        area=cv2.contourArea(c)/gray.size
        if not .16<area<.95:continue
        q=cv2.approxPolyDP(c,.025*cv2.arcLength(c,True),True)
        if len(q)!=4 or not cv2.isContourConvex(q):continue
        rect=cv2.minAreaRect(q);a,b=rect[1]
        if min(a,b)<=0 or not 1.45<max(a,b)/min(a,b)<2.8:continue
        boundary=np.zeros_like(gray);cv2.polylines(boundary,[q],True,255,8)
        dark=float(np.mean(gray[boundary>0]<90))
        if dark<.45:continue
        polygon=(q.reshape(4,2)/scale).round().astype(int)
        x,y,bw,bh=cv2.boundingRect(polygon)
        out.append(dict(polygon=polygon.tolist(),bbox=[x,y,x+bw,y+bh],dark_border_ratio=dark))
        if len(out)==3:break
    return out


def box_geometry_candidates(image,label_polygon):
    """Contours supporting an apparent box footprint, not a trained semantic detector."""
    if label_polygon is None:return []
    h,w=image.shape[:2];scale=min(1.,1200/max(h,w))
    gray=cv2.cvtColor(cv2.resize(image,(round(w*scale),round(h*scale))),cv2.COLOR_BGR2GRAY)
    edges=cv2.Canny(gray,40,120);edges=cv2.morphologyEx(edges,cv2.MORPH_CLOSE,np.ones((5,5),np.uint8))
    contours,_=cv2.findContours(edges,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
    center=np.asarray(label_polygon,dtype=float).mean(axis=0)*scale
    label_area=cv2.contourArea(np.float32(label_polygon))*scale*scale
    out=[]
    for c in sorted(contours,key=cv2.contourArea,reverse=True)[:150]:
        area=cv2.contourArea(c)
        if not max(gray.size*.025,label_area*1.4)<area<gray.size*.8:continue
        q=cv2.approxPolyDP(c,.025*cv2.arcLength(c,True),True)
        if not 4<=len(q)<=6 or not cv2.isContourConvex(q):continue
        if cv2.pointPolygonTest(q,tuple(center),False)<0:continue
        out.append((q.reshape(-1,2)/scale).round().astype(int).tolist())
        if len(out)==3:break
    return out
