"""CPU open-vocabulary experiment; predicted labels are candidates, not photo approval."""
import hashlib
import json
from pathlib import Path
import re
import time

import numpy as np
from PIL import Image

PROMPTS=('a cardboard box.','a white sticker label.','a mobile phone.')
CLASSES=('box','label','phone')


class GroundingONNX:
    def __init__(self,model_root=None):
        import onnxruntime as ort
        root=Path(model_root) if model_root else Path(__file__).resolve().parents[2]/'data/Samsung/models/grounding-dino'
        expected={'onnx/model_quantized.onnx':'70bf2d3310d1ae73769c96a71e00cbf2861eb33a1f4d97d84a108a7bf02c03c9',
                  'vocab.txt':'07eced375cec144d27c900241f3e339478dec958f92fddbc551f295c992038a3',
                  'preprocessor_config.json':'ffc8a8a93bb1782cc6f84a37b83babb0660bb19146e52600c122335a798b503f'}
        for name,digest in expected.items():
            if hashlib.sha256((root/name).read_bytes()).hexdigest()!=digest:raise ValueError('MODEL_HASH_MISMATCH')
        self.config=json.loads((root/'preprocessor_config.json').read_text())
        self.vocab={word:i for i,word in enumerate((root/'vocab.txt').read_text(encoding='utf-8').splitlines())}
        self.ids=[self.vocab['[CLS]']];self.spans=[]
        # Frozen English prompt; standard greedy BERT WordPiece. No image text,
        # case identifier, watermark or dataset label enters the prompt/tokenizer.
        for phrase in PROMPTS:
            positions=[]
            for word in re.findall(r'\w+|[^\w\s]',phrase.lower()):
                pieces=[];offset=0
                while offset<len(word):
                    end=len(word)
                    while end>offset:
                        piece=('##' if offset else '')+word[offset:end]
                        if piece in self.vocab:break
                        end-=1
                    if end==offset:raise ValueError('Frozen prompt contains unknown token')
                    pieces.append(self.vocab[piece]);offset=end
                if word not in {'a','.'}:positions.extend(range(len(self.ids),len(self.ids)+len(pieces)))
                self.ids.extend(pieces)
            self.spans.append(positions)
        self.ids.append(self.vocab['[SEP]'])
        options=ort.SessionOptions();options.intra_op_num_threads=4;options.inter_op_num_threads=1
        options.log_severity_level=3;options.graph_optimization_level=ort.GraphOptimizationLevel.ORT_ENABLE_BASIC
        self.session=ort.InferenceSession(str(root/'onnx/model_quantized.onnx'),sess_options=options,providers=['CPUExecutionProvider'])

    def predict(self,image):
        start=time.perf_counter();h,w=image.shape[:2]
        rgb=np.asarray(Image.fromarray(image[:,:,::-1]).resize((800,800),Image.Resampling.BILINEAR)).astype(np.float32)/255.
        pixels=((rgb-np.float32(self.config['image_mean']))/np.float32(self.config['image_std'])).transpose(2,0,1)[None]
        ids=np.array([self.ids],np.int64)
        feed=dict(pixel_values=pixels,input_ids=ids,token_type_ids=np.zeros_like(ids),
                  attention_mask=np.ones_like(ids),pixel_mask=np.ones((1,800,800),np.int64))
        logits,boxes=self.session.run(['logits','pred_boxes'],feed)
        probabilities=1/(1+np.exp(-np.clip(logits[0],-80,80)))
        scores=np.stack([probabilities[:,span].max(axis=1) for span in self.spans],axis=1)
        result=[]
        for query in np.flatnonzero(scores.max(axis=1)>=.3):
            label=int(scores[query].argmax());cx,cy,bw,bh=boxes[0,query]
            bbox=[float(np.clip((cx-bw/2)*w,0,w)),float(np.clip((cy-bh/2)*h,0,h)),
                  float(np.clip((cx+bw/2)*w,0,w)),float(np.clip((cy+bh/2)*h,0,h))]
            result.append(dict(kind=CLASSES[label],score=float(scores[query,label]),bbox=bbox,
                               preliminary=True,query=int(query)))
        return dict(detections=result,seconds=round(time.perf_counter()-start,3),threshold=.3,prompts=PROMPTS,
                    source='GroundingDINO-tiny-ONNX-community-uint8',provider='CPUExecutionProvider',
                    notice='Open-vocabulary candidates. A label prediction is not confirmation of factory-sticker completeness or physical authenticity.')
