"""Private post-inference diagnostics; source labels never enter photo analysis."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile
import cv2
import numpy as np
from backend.gate.samsung_paths import input_archives

SOURCES={
 'device_top_visible':'R02: Approved DOCX blocks 4,8; examples 1-5',
 'identification_visible':'R01: Approved blocks 3,8,11; Rejected blocks 3,4,6',
 'identifier_readable':'R01/R04: Approved blocks 3,8,11; Rejected blocks 4,6',
 'barcode_readable':'R03: Approved blocks 8,11; Rejected block 3',
 'identification_not_cropped':'R05: Rejected block 7, scan examples 13-15; XLSX F10:F12',
 'information_image_quality':'R04: Rejected blocks 4,6; XLSX E10:E12,F7:F9',
 'screen_recapture_absent':'R06: Rejected blocks 5,8; XLSX E13:F15',
}

def metrics(image):
 g=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
 return dict(width=g.shape[1],height=g.shape[0],gray_min=int(g.min()),gray_max=int(g.max()),
  mean=float(g.mean()),std=float(g.std()),laplacian_variance=float(cv2.Laplacian(g,cv2.CV_64F).var()),
  bright_pixel_fraction=float(np.mean(g>=252)),dark_pixel_fraction=float(np.mean(g<30)),
  notice='Descriptive native-pixel metrics, not calibrated defect thresholds; bright pixels are not proven glare.')

def evidence_polygon(e):
 if e.get('source')=='windows_local_ocr' and not e.get('words'):return None
 q=e.get('polygon') or e.get('region')
 if e.get('words'):
  words=e['words'];x1=min(w['x'] for w in words);y1=min(w['y'] for w in words)
  x2=max(w['x']+w['width'] for w in words);y2=max(w['y']+w['height'] for w in words)
  q=[[x1,y1],[x2,y1],[x2,y2],[x1,y2]]
 elif e.get('bbox'):
  x1,y1,x2,y2=e['bbox'];q=[[x1,y1],[x2,y1],[x2,y2],[x1,y2]]
 if q is None:return None
 q=np.float32(q).reshape(-1,2)
 if e.get('coordinate_space')=='variant':
  matrix=e.get('original_to_variant')
  if matrix is None:return None
  q=cv2.perspectiveTransform(q[None],np.linalg.inv(np.float64(matrix)))[0]
 return q.round(2).tolist()

def run(report,labels,output,archives=None):
 report=json.loads(Path(report).read_text(encoding='utf-8'));labels=json.loads(Path(labels).read_text(encoding='utf-8'))
 output=Path(output);output.mkdir(parents=True,exist_ok=True)
 archive_map={p.name:p for p in (archives or input_archives())}
 entries={r['sha256']:r for r in report['intake']['files'] if r.get('status')=='OK'}
 cases={c['case_id']:c for c in report['cases']};rows=[];md=['# Private Approved blocker diagnostics','Original-coordinate overlays contain corporate photographs. Keep local; never include in release ZIP.','Metrics do not prove glare, blur, crop, physicality or complete coverage. Null coordinates mean no verified localization exists.']
 for ref in labels:
  if ref['expected']!='APPROVED':continue
  case=cases[ref['case_id']];alias=f'S{ref["row"]-1:02d}'
  for p in case['photos']:
   entry=entries[p['sha256']]
   with zipfile.ZipFile(archive_map[entry['archive']]) as z:raw=z.read(entry['path'])
   assert hashlib.sha256(raw).hexdigest()==p['sha256']
   image=cv2.imdecode(np.frombuffer(raw,np.uint8),cv2.IMREAD_COLOR);h,w=image.shape[:2];overlay=image.copy()
   proposals=[]
   for i,a in enumerate(p['proposals']):
    x1,y1,x2,y2=a['bbox'];roi=image[y1:y2,x1:x2]
    proposals.append(dict(**a,native_axis_aligned_metrics=metrics(roi) if roi.size else None))
    cv2.polylines(overlay,[np.int32(a['polygon'])],True,(0,160,255),2)
    cv2.putText(overlay,'candidate '+str(i),(max(0,x1),max(20,y1)),cv2.FONT_HERSHEY_SIMPLEX,.5,(0,100,255),1)
   fields=[]
   for f in p['fields']:
    evidence=[]
    for e in f['evidence']:
     polygon=evidence_polygon(e)
     evidence.append(dict(source=e['source'],processing=e.get('processing',e.get('variant')),confidence=e.get('confidence'),confidence_calibrated=False,polygon=polygon,
                          granularity='OCR line or decoded symbol, not a verified complete critical-information region'))
     if polygon is not None and f['key'] in {'imei1','imei2','serial'}:cv2.polylines(overlay,[np.int32(polygon)],True,(30,190,30),1)
    fields.append(dict(key=f['key'],masked_value='***'+f['value'][-3:] if f['key'].startswith('imei') or f['key']=='serial' else f['value'],format_valid=f['format_valid'],confirmed=f['confirmed'],conflicted=f.get('conflicted',False),evidence=evidence))
   for b in p['barcodes']:
    if b.get('polygon'):cv2.polylines(overlay,[np.int32(b['polygon'])],True,(255,80,0),1)
   blockers=[]
   for key,c in p['checks'].items():
    if key not in p.get('mandatory_checks',[]) or c['state']!='UNKNOWN':continue
    cause='missing_verified_detector'
    if key in {'identifier_readable','barcode_readable','identification_visible'}:cause='recognition_or_binding_incomplete'
    source=SOURCES.get(key)
    if key=='identification_not_cropped' and p['role']=='device':
     source='R01/R04: Approved block 8 requires visible readable identification; user requires no critical clipping. No universal whole-label border requirement.'
    blockers.append(dict(check=key,reason=c['reason'],official_source=source,cause=cause,
     verified_target_polygon=None,measurement=None,measurement_unavailable='No verified detector output for this criterion; descriptive ROI/field measurements follow separately.'))
   target=output/f'{alias}-{p["role"]}.png';cv2.imwrite(str(target),overlay)
   row=dict(alias=alias,role=p['role'],sha256=p['sha256'],image_metrics=metrics(image),proposals=proposals,fields=fields,
    unique_decoded_symbols=len({(b['type'],b['value']) for b in p['barcodes']}),
    decoded_symbol_regions=[dict(type=b['type'],bbox=b['bbox'],processing=b['variant']) for b in p['barcodes']],
    verified_box_faces=None,verified_critical_region=None,checks=p['checks'],blockers=blockers,diagnostic_image=target.name,
    ppocr_status=p['pretrained_ocr']['status'],screen_ocr_status=p.get('screen_ui_ocr',{}).get('status'),
    identity_conflicts=[f['key'] for f in fields if f['conflicted'] and f['key'].startswith('imei')])
   rows.append(row)
   md.extend([f'## {alias} / {p["role"]}',f'Image: {w}x{h}; native Laplacian variance {row["image_metrics"]["laplacian_variance"]:.2f}; std {row["image_metrics"]["std"]:.2f}; bright fraction {row["image_metrics"]["bright_pixel_fraction"]:.4f}; decoded symbols {row["unique_decoded_symbols"]}; PP-OCR {row["ppocr_status"]}.',
    f'![Private diagnostic]({target.resolve().as_posix()})','| UNKNOWN | Cause | Official source |','|---|---|---|']+[f'| {b["check"]} | {b["cause"]}: {b["reason"]} | {b["official_source"]} |' for b in blockers])
   md.extend(['','| Candidate | Native bbox x1,y1,x2,y2 | Geometry / method | Score | Laplacian |','|---|---|---|---|---|']+[f'| {i} | {a["bbox"]} | {a.get("geometry","fallback")} / {a["method"]} | {a["score"]} | {a["native_axis_aligned_metrics"]["laplacian_variance"]:.2f} |' for i,a in enumerate(proposals)])
   md.extend(['','| Field | Masked value | Valid / confirmed / conflict | Source / processing / confidence / original polygon |','|---|---|---|---|']+[f'| {f["key"]} | {f["masked_value"]} | {f["format_valid"]} / {f["confirmed"]} / {f["conflicted"]} | '+ '; '.join(str(e) for e in f['evidence'])+' |' for f in fields])
 (output/'blockers.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
 (output/'APPROVED_BLOCKERS.md').write_text('\n\n'.join(md),encoding='utf-8')
 print('Private diagnostics:',len(rows),'photos,',sum(len(r['blockers']) for r in rows),'UNKNOWN checks')
 return rows

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('report',type=Path);p.add_argument('labels',type=Path);p.add_argument('output',type=Path)
 a=p.parse_args();run(a.report,a.labels,a.output)
