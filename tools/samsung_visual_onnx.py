"""Experimental fixed-size YOLO ONNX CPU runner. No approval/check decisions.

Does not import Torch or Ultralytics. This does NOT change the weights' license.
Caller must supply the SHA-256 and class names of a locally reviewed model.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time
import cv2
import numpy as np


class VisualONNX:
    def __init__(self,weights,expected_sha256,class_names,threads=4):
        import onnxruntime as ort
        path=Path(weights)
        if hashlib.sha256(path.read_bytes()).hexdigest()!=expected_sha256:raise ValueError('MODEL_HASH_MISMATCH')
        self.classes=tuple(class_names)
        if not self.classes or any(c not in {'box','factory_label','identification_region','phone_screen'} for c in self.classes):raise ValueError('OBJECT_CLASSES_REQUIRED')
        options=ort.SessionOptions();options.intra_op_num_threads=threads;options.inter_op_num_threads=1
        self.session=ort.InferenceSession(str(path),sess_options=options,providers=['CPUExecutionProvider'])
        self.input=self.session.get_inputs()[0]
        if self.input.shape!=[1,3,640,640]:raise ValueError('FIXED_640_MODEL_REQUIRED')

    @staticmethod
    def tensor(image):
        h,w=image.shape[:2];ratio=min(640/h,640/w);nw,nh=round(w*ratio),round(h*ratio)
        left=round((640-nw)/2-.1);top=round((640-nh)/2-.1)
        padded=np.full((640,640,3),114,np.uint8);padded[top:top+nh,left:left+nw]=cv2.resize(image,(nw,nh),interpolation=cv2.INTER_LINEAR)
        tensor=np.ascontiguousarray(padded[:,:,::-1].transpose(2,0,1)[None],dtype=np.float32)/255
        return tensor,ratio,left,top

    def predict(self,image):
        h,w=image.shape[:2];tensor,ratio,left,top=self.tensor(image)
        out=self.session.run(None,{self.input.name:tensor})[0]
        if out.ndim!=3 or out.shape[0]!=1 or out.shape[1]!=4+len(self.classes):raise ValueError('UNEXPECTED_MODEL_OUTPUT')
        rows=out[0].T;classes=np.argmax(rows[:,4:],axis=1);scores=rows[np.arange(len(rows)),4+classes]
        keep=scores>=.25;rows=rows[keep];scores=scores[keep];classes=classes[keep]
        detections=[]
        for cls in range(len(self.classes)):
            select=classes==cls;values=rows[select];conf=scores[select]
            boxes=np.column_stack((values[:,0]-values[:,2]/2,values[:,1]-values[:,3]/2,values[:,2],values[:,3]))
            picked=cv2.dnn.NMSBoxes(boxes.tolist(),conf.tolist(),.25,.7)
            for i in np.asarray(picked).reshape(-1):
                x,y,bw,bh=boxes[i];box=[float(np.clip((x-left)/ratio,0,w)),float(np.clip((y-top)/ratio,0,h)),float(np.clip((x+bw-left)/ratio,0,w)),float(np.clip((y+bh-top)/ratio,0,h))]
                if box[2]<=box[0] or box[3]<=box[1]:continue
                detections.append(dict(bbox=box,class_id=cls,class_name=self.classes[cls],confidence=float(conf[i]),calibrated=False))
        return sorted(detections,key=lambda d:-d['confidence'])[:300]


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('weights',type=Path);p.add_argument('sha256');p.add_argument('manifest',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=True);start=time.perf_counter();model=VisualONNX(a.weights,a.sha256,['identification_region']);load=time.perf_counter()-start
    data=json.loads(a.manifest.read_text(encoding='utf-8'));rows=[]
    for p in data['images']:
        raw=Path(p['image']).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=p['sha256']:raise ValueError('SOURCE_CHANGED')
        image=cv2.imdecode(np.frombuffer(raw,np.uint8),cv2.IMREAD_COLOR);start=time.perf_counter();detections=model.predict(image);seconds=time.perf_counter()-start
        rows.append(dict(sha256=p['sha256'],width=p['width'],height=p['height'],seconds=seconds,detections=detections))
    # Windows process-lifetime peak, including imports and model initialization.
    from tools.samsung_visual_resources import peak_working_set
    result=dict(rows=rows,total_seconds=sum(p['seconds'] for p in rows),load_seconds=load,os_peak_working_set_bytes=peak_working_set(),weights_sha256=a.sha256,threads=4,device='CPUExecutionProvider',imgsz=640,confidence_threshold=.25,iou_threshold=.7,classification_integration=False)
    (a.output/'results.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print('ONNX CPU',len(rows),'images',round(result['total_seconds'],2),'seconds')


if __name__=='__main__':main()
