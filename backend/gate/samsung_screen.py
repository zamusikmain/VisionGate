"""Local gallery-UI evidence. No identity repair, watermark or expected labels."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import cv2
from .private_temp import private_directory


def read_screen_ui(image,cache_dir=None):
    if os.name!='nt':return dict(status='UNAVAILABLE',reason='Windows OCR not installed on this platform',reads=[])
    script=Path(__file__).resolve().parents[2]/'tools/windows_ui_ocr.ps1'
    h,w=image.shape[:2];scale=min(4.,2000/max(h,w));pixels=cv2.resize(image,None,fx=scale,fy=scale)
    key=hashlib.sha256(script.read_bytes()+str(pixels.shape).encode()+pixels.tobytes()).hexdigest()
    cached=Path(cache_dir)/(key+'.json') if cache_dir else None
    if cached and cached.exists():
        result=json.loads(cached.read_text(encoding='utf-8'));result['cache_hit']=True;return result
    folder=Path('reports/.screen-temp');folder.mkdir(parents=True,exist_ok=True)
    try:
        with private_directory(folder) as tmp:
            target=Path(tmp)/'pixels.png';cv2.imencode('.png',pixels)[1].tofile(str(target))
            manifest=Path(tmp)/'manifest.json';manifest.write_text(json.dumps([str(target)]),encoding='utf-8')
            process=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-File',str(script),'-ManifestPath',str(manifest)],capture_output=True,timeout=30)
            if process.returncode:raise ValueError('LOCAL_UI_OCR_FAILED')
            result=json.loads(process.stdout.decode('utf-8-sig'))[0]
            for reading in result.get('reads',[]):
                for line in reading['lines']:
                    for word in line.get('words',[]):
                        for k in ('x','y','width','height'):word[k]/=scale
            result.update(coordinate_space='original',cache_hit=False,confidence_calibrated=False,
                          source='installed_Windows_OCR_ui_languages')
            if cached:
                cached.parent.mkdir(parents=True,exist_ok=True);cached.write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
            return result
    except (OSError,ValueError,subprocess.TimeoutExpired):return dict(status='UNAVAILABLE',reads=[])


def gallery_evidence(ocr,barcodes,height):
    """Two separate explicit UI controls, above the inspected identification.

    A phone number alone or a background phone never suffices. Values are not
    corrected, inferred or used as identifiers. No fuzzy UI-token matching.
    """
    symbols=[b for b in barcodes if b.get('bbox') and b.get('checksum_valid') and b.get('type') in {'Code 128','Code 39','ITF'}]
    if not symbols:return None
    header=[];gallery=[]
    for read in ocr.get('reads',[]):
        for line in read.get('lines',[]):
            words=line.get('words',[])
            if not words:continue
            bbox=[min(w['x'] for w in words),min(w['y'] for w in words),
                  max(w['x']+w['width'] for w in words),max(w['y']+w['height'] for w in words)]
            if bbox[3]>height*.3:continue
            text=line['text'].strip()
            digits=re.sub(r'\D','',text)
            if re.match(r'^\+\d',text) and 7<=len(digits)<=15:header.append(bbox)
            # Cyrillic Ze is a common OCR glyph for a visible 3. This matches
            # only the small gallery-count UI token, never identifier digits.
            if re.search(r'\b[0-9\u0417]{1,3}\s+(?:\u0444\u043e\u0442\u043e|photos?)\b',text,re.I):gallery.append(bbox)
    for a in header:
        for b in gallery:
            if a[1]<=b[1] and any(s['bbox'][1]>b[3] and
                    s['bbox'][0]<=(a[0]+a[2])/2<=s['bbox'][2] and
                    s['bbox'][0]<=(b[0]+b[2])/2<=s['bbox'][2] for s in symbols):
                return dict(code='DISPLAYED_GALLERY_PHOTO',source='localized_gallery_UI',
                            regions=[a,b],coordinate_space='original',
                            reason='A telephone-contact header and explicit photo-count gallery control are aligned above the inspected coded image. A background phone alone is not used.')
    return None
