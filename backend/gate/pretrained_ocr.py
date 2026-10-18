"""Offline PP-OCRv5 ONNX experiment. No downloads, labels or expected values at inference.

DB/CTC implementation follows PaddleOCR's Apache-2.0 model configs and documented
algorithms: ppocr/postprocess/{db_postprocess,rec_postprocess}.py. Model weights
remain separately installed under their upstream Apache-2.0 license.
"""
import hashlib
from pathlib import Path
import time

import cv2
import numpy as np

from .samsung_vision import ordered_quad

MODELS={
    'PP-OCRv5_server_det_onnx':('10803475a591f7dc623e24670fb5752ec94d39a1f8cf069aac1b6f0ce19cfc85','28fb721efc3634fc8aa677e474b9602cb815a91cf569ef357a7a553d7b3ce685'),
    'PP-OCRv5_mobile_det_onnx':('a431985659dc921974177a95adcfbb90fd9e51989a5e04d70d0b75f597b6e61d','98069072e1b6b37d727fd9d9f11725faa46d6ea0de012f2ed26caea011c37699'),
    'latin_PP-OCRv5_mobile_rec_onnx':('7888113072263cb471b93f66dd5e2ad70548dc526fa1ace760d0d973dd121498','0bbe984570f597af3638e50bdf2e8276f3ab26a61966096538b3b0d1849f5c84'),
    'PP-OCRv5_server_rec_onnx':('d9dc333c9c7b042c6dffb8e33d72b6f65c9c1d463d0a3c2f78174fea55e94752','2c719dba044c4e2228aef8ff92f5f575394d75d24c16de096a33b7cfd902f66d'),
}


def ctc_decode(prediction, alphabet):
    indices=prediction.argmax(axis=1);scores=prediction.max(axis=1)
    selected=indices!=0
    selected[1:] &= indices[1:]!=indices[:-1]
    return ''.join(alphabet[i] for i in indices[selected]),float(scores[selected].mean()) if selected.any() else 0.


def text_crop(image,polygon):
    q=ordered_quad(polygon)
    w=max(4,round(max(np.linalg.norm(q[1]-q[0]),np.linalg.norm(q[2]-q[3]))))
    h=max(4,round(max(np.linalg.norm(q[3]-q[0]),np.linalg.norm(q[2]-q[1]))))
    matrix=cv2.getPerspectiveTransform(q,np.float32([[0,0],[w-1,0],[w-1,h-1],[0,h-1]]))
    crop=cv2.warpPerspective(image,matrix,(w,h),flags=cv2.INTER_CUBIC,borderMode=cv2.BORDER_REPLICATE)
    return np.ascontiguousarray(np.rot90(crop)) if h/w>=1.5 else crop


class PaddleONNX:
    def __init__(self,model_root=None,threads=4,long_side=1600,recognizer='latin',detector='mobile',memory_profile='default'):
        import onnxruntime as ort
        import yaml
        root=Path(model_root) if model_root else Path(__file__).resolve().parents[2]/'data/Samsung/models'
        self.sessions=[];self.configs=[];self.long_side=long_side
        self.model_hashes={}
        if memory_profile not in {'default','bounded'}:raise ValueError('UNKNOWN_OCR_MEMORY_PROFILE')
        options=ort.SessionOptions();options.intra_op_num_threads=1 if memory_profile=='bounded' else threads;options.inter_op_num_threads=1
        if memory_profile=='bounded':
            # Reuse no unbounded CPU arena across dynamic text sizes. This changes
            # allocation/threading only, not pixels, weights, operators or thresholds.
            options.enable_cpu_mem_arena=False
            options.enable_mem_pattern=False
        options.log_severity_level=3
        if recognizer=='server' or detector=='server':options.graph_optimization_level=ort.GraphOptimizationLevel.ORT_ENABLE_BASIC
        if recognizer not in {'latin','server'}:raise ValueError('UNKNOWN_RECOGNIZER')
        if detector not in {'mobile','server'}:raise ValueError('UNKNOWN_DETECTOR')
        names=['PP-OCRv5_'+detector+'_det_onnx','latin_PP-OCRv5_mobile_rec_onnx' if recognizer=='latin' else 'PP-OCRv5_server_rec_onnx']
        for name in names:
            hashes=MODELS[name]
            for filename,expected in zip(('inference.onnx','inference.yml'),hashes):
                path=root/name/filename
                if not path.is_file():raise ValueError('LOCAL_MODEL_MISSING: '+str(path))
                actual=hashlib.sha256(path.read_bytes()).hexdigest()
                if actual!=expected:raise ValueError('LOCAL_MODEL_HASH_MISMATCH: '+str(path))
                self.model_hashes[name+'/'+filename]=actual
            self.configs.append(yaml.safe_load((root/name/'inference.yml').read_text(encoding='utf-8')))
            self.sessions.append(ort.InferenceSession(str(root/name/'inference.onnx'),sess_options=options,providers=['CPUExecutionProvider']))
        self.det,self.rec=self.sessions
        self.alphabet=['blank']+self.configs[1]['PostProcess']['character_dict']+[' ']
        if len(self.alphabet)!=self.rec.get_outputs()[0].shape[-1]:raise ValueError('CTC_DICTIONARY_SIZE_MISMATCH')

    def detect(self,image):
        import pyclipper
        h,w=image.shape[:2];scale=self.long_side/max(h,w)
        rh=max(32,round(h*scale/32)*32);rw=max(32,round(w*scale/32)*32)
        pixels=cv2.resize(image,(rw,rh)).astype(np.float32)/255.
        pixels=(pixels-np.float32([.485,.456,.406]))/np.float32([.229,.224,.225])
        pred=self.det.run(None,{self.det.get_inputs()[0].name:pixels.transpose(2,0,1)[None]})[0][0,0]
        config=self.configs[0]['PostProcess'];mask=(pred>config['thresh']).astype(np.uint8)*255
        contours,_=cv2.findContours(mask,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
        result=[]
        for contour in contours[:config['max_candidates']]:
            rect=cv2.minAreaRect(contour)
            if min(rect[1])<3:continue
            q=cv2.boxPoints(rect);x,y,bw,bh=cv2.boundingRect(q)
            x1=max(0,x);y1=max(0,y);x2=min(pred.shape[1],x+bw);y2=min(pred.shape[0],y+bh)
            if x2<=x1 or y2<=y1:continue
            region=np.zeros((y2-y1,x2-x1),np.uint8)
            cv2.fillPoly(region,[np.int32(q-[x1,y1])],1)
            score=float(cv2.mean(pred[y1:y2,x1:x2],region)[0])
            if score<config['box_thresh']:continue
            perimeter=cv2.arcLength(q,True)
            offset=pyclipper.PyclipperOffset()
            offset.AddPath(np.rint(q).astype(int).tolist(),pyclipper.JT_ROUND,pyclipper.ET_CLOSEDPOLYGON)
            expanded=offset.Execute(cv2.contourArea(q)*config['unclip_ratio']/max(perimeter,1))
            if len(expanded)!=1:continue
            rect=cv2.minAreaRect(np.float32(expanded[0]))
            if min(rect[1])<5:continue
            q=ordered_quad(cv2.boxPoints(rect));q[:,0]*=w/pred.shape[1];q[:,1]*=h/pred.shape[0]
            q[:,0]=q[:,0].clip(0,w-1);q[:,1]=q[:,1].clip(0,h-1)
            result.append(dict(polygon=q.round(2).tolist(),detection_score=score))
        return sorted(result,key=lambda r:(min(p[1] for p in r['polygon']),min(p[0] for p in r['polygon'])))

    def recognize(self,crop):
        h,w=crop.shape[:2];width=min(3200,max(320,round(48*w/h)))
        resized_width=min(width,max(1,round(48*w/h)))
        pixels=cv2.resize(crop,(resized_width,48)).astype(np.float32)/127.5-1.
        padded=np.zeros((1,3,48,width),np.float32)
        padded[0,:,:,:resized_width]=pixels.transpose(2,0,1)
        prediction=self.rec.run(None,{self.rec.get_inputs()[0].name:padded})[0][0]
        return ctc_decode(prediction,self.alphabet)

    def read(self,image,detections=None):
        start=time.perf_counter();lines=[]
        for detection in (self.detect(image) if detections is None else detections):
            crop=text_crop(image,detection['polygon']);readings=[]
            for turns in ((int(detection['rotation_hint'])//90,) if 'rotation_hint' in detection else (0,2)):
                text,score=self.recognize(np.ascontiguousarray(np.rot90(crop,turns)))
                readings.append(dict(text=text,score=score,rotation=turns*90))
            best=max(readings,key=lambda r:r['score'])
            lines.append(dict(**detection,**best,alternatives=readings,source='PP-OCRv5_ONNX_CPU',
                              score_calibrated=False))
        return dict(lines=lines,seconds=round(time.perf_counter()-start,3),models=self.model_hashes,
                    detector_long_side=self.long_side,provider='CPUExecutionProvider')
