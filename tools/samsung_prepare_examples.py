"""Private annotation preparation. Official answers are editor/evaluation metadata only.

propose_regions accepts pixels and recognition observations, never reference labels.
No model training or change to Samsung API decisions is performed here.
"""
import argparse
from collections import Counter
import copy
import hashlib
import json
from pathlib import Path
import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile

import cv2
import numpy as np

from backend.gate.image_input import read_image
from backend.gate.samsung_auto import parse_fields
from backend.gate.samsung_vision import locate_labels, box_geometry_candidates
from tools.samsung_region_annotations import validate, editor

S={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
W={'a':'http://schemas.openxmlformats.org/drawingml/2006/main',
   'r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
REASONS={'Photo without serial number':'IDENTIFICATION_MISSING',
         'blurry/dark/unreadable':'INFORMATION_QUALITY',
         'Cutted photo':'CRITICAL_CROP',
         'photo of photo from other device':'SCREEN_RECAPTURE','OK':'OK'}
TARGETS={'IDENTIFICATION_MISSING':('required_region',),
         'INFORMATION_QUALITY':('blur','darkness','glare','occlusion'),
         'CRITICAL_CROP':('crop',),'SCREEN_RECAPTURE':('screen_recapture',)}


def official_rows(path):
    """Read the authoritative final column and role-specific reasons, not registration."""
    result={}
    with zipfile.ZipFile(path) as z:
        if z.testzip():raise ValueError('INVALID_REFERENCE_XLSX')
        strings=[]
        if 'xl/sharedStrings.xml' in z.namelist():
            strings=[''.join(si.itertext()) for si in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('s:si',S)]
        for name in z.namelist():
            if not re.fullmatch(r'xl/worksheets/sheet\d+\.xml',name):continue
            rows=[]
            for row in ET.fromstring(z.read(name)).findall('s:sheetData/s:row',S):
                values={}
                for cell in row.findall('s:c',S):
                    value=cell.find('s:v',S);value=value.text if value is not None else ''
                    if cell.get('t')=='s':value=strings[int(value)]
                    elif cell.get('t')=='inlineStr':value=''.join(cell.find('s:is',S).itertext())
                    values[re.sub(r'\d','',cell.get('r',''))]=value
                rows.append((int(row.get('r')),values))
            header=next((values for _,values in rows if 'Final_Status' in values.values()),None)
            if not header:continue
            columns={v:k for k,v in header.items()}
            required=('SN/IMEI','Final_Status','Registration Status','Description','Scan (not a photo)')
            if not all(k in columns for k in required):raise ValueError('REFERENCE_COLUMNS_CHANGED')
            for ordinal,values in rows:
                category=values.get(columns['Final_Status'],'').strip().upper()
                if category not in {'APPROVED','REJECTED'}:continue
                key=values.get(columns['SN/IMEI'],'').strip()
                if not key or key in result:raise ValueError('AMBIGUOUS_OFFICIAL_CASE')
                reasons={role:values.get(columns[column],'').strip() for role,column in
                         [('device','Description'),('scan','Scan (not a photo)')]}
                if any(reason not in REASONS for reason in reasons.values()):raise ValueError('UNMAPPED_OFFICIAL_REASON')
                if category=='APPROVED' and any(v!='OK' for v in reasons.values()):raise ValueError('FINAL_REASON_CONFLICT_REQUIRES_REVIEW')
                if category=='REJECTED' and all(v=='OK' for v in reasons.values()):raise ValueError('REJECTED_WITHOUT_ROLE_REASON')
                registration=values.get(columns['Registration Status'],'').strip()
                result[key]=dict(category=category,case_id=key,case_alias=f'S{len(result)+1:02}',row=ordinal,
                                 reasons=reasons,reason_codes={r:REASONS[v] for r,v in reasons.items()},
                                 registration=registration,registration_conflict=registration.upper()!=category,
                                 cells=dict(status=f"{columns['Final_Status']}{ordinal}",
                                            device=f"{columns['Description']}{ordinal}",scan=f"{columns['Scan (not a photo)']}{ordinal}"))
    if not result:raise ValueError('NO_OFFICIAL_CASES')
    return result


def docx_photos(path,category):
    """Ordered drawing references, not ZIP media filenames or inferred case answers."""
    with zipfile.ZipFile(path) as z:
        if z.testzip():raise ValueError('INVALID_REFERENCE_DOCX')
        rels={r.get('Id'):r.get('Target') for r in ET.fromstring(z.read('word/_rels/document.xml.rels'))
              if r.get('TargetMode')!='External'}
        drawings=ET.fromstring(z.read('word/document.xml')).findall('.//a:blip',W)
        # The reviewed official DOCX documents list device examples first,
        # then scan examples. This is not a generic DOCX semantic classifier.
        count=len(drawings)
        if not count or count%2:raise ValueError('DOCX_ROLE_LAYOUT_CHANGED')
        found={}
        for i,blip in enumerate(drawings):
            target=rels[blip.get('{'+W['r']+'}embed')]
            name=posixpath.normpath(posixpath.join('word',target)) if not target.startswith('/') else target.lstrip('/')
            digest=hashlib.sha256(z.read(name)).hexdigest()
            if digest in found:raise ValueError('DUPLICATE_DOCX_PHOTO')
            found[digest]=dict(document=Path(path).name,example=i+1,role='device' if i<count//2 else 'scan',category=category)
        return found


def _polygon(points,w,h):
    try:q=np.asarray(points,dtype=float).reshape(-1,2)
    except (ValueError,TypeError):return None
    if not 3<=len(q)<=20 or not np.isfinite(q).all():return None
    q=np.clip(q/[w,h],0,1)
    if cv2.contourArea(q.astype('float32'))<1e-7:return None
    return q.round(7).tolist()


def propose_regions(image,recognition):
    """Value-free regions; no filenames, reference answers or prior manual polygons."""
    h,w=image.shape[:2];objects=[]
    def add(kind,points,source,*,localized=False,score=None,note='Semantic extent unconfirmed'):
        polygon=_polygon(points,w,h)
        if polygon is None:return
        # Repeated variants of one region are one proposal, never independent evidence.
        q=np.asarray(polygon);bbox=[*q.min(axis=0),*q.max(axis=0)]
        for o in objects:
            if o['class']!=kind:continue
            a=np.asarray(o['polygon']);b=[*a.min(axis=0),*a.max(axis=0)]
            intersection=max(0,min(b[2],bbox[2])-max(b[0],bbox[0]))*max(0,min(b[3],bbox[3])-max(b[1],bbox[1]))
            union=(b[2]-b[0])*(b[3]-b[1])+(bbox[2]-bbox[0])*(bbox[3]-bbox[1])-intersection
            if intersection/max(union,1e-12)>.72:return
        objects.append(dict(**{'class':kind},polygon=polygon,reviewed=False,source=source,
                            localization_verified=localized,confidence=score,confidence_calibrated=False,
                            semantic_verified=False,note=note))
    for code in recognition.get('barcodes',[]):
        if code.get('coordinate_space')!='original':continue
        add('barcode',code.get('polygon'), 'ZXing:'+code.get('variant','unknown'),
            localized=bool(code.get('checksum_valid')),note='Decoded symbol location; not proof of complete identification area')
    for line in recognition.get('pretrained_ocr',{}).get('lines',[]):
        # Text is used only to select an identifier region. Never retain its value.
        text=line.get('text','')
        parsed=[k for k,_,valid in parse_fields(text) if valid and (k.startswith('imei') or k=='serial')]
        if parsed or re.search(r'\bIMEI\s*[12]?\b|\bS\s*/\s*N\b|\bSerial\b',text,re.I):
            add('identifier_text',line.get('polygon'),'PP-OCRv5:identifier_context',score=line.get('score'),
                note='OCR line with identifier context; characters and complete field coverage unverified')
    proposals=recognition.get('proposals')
    if proposals is None:
        boxes=[c['bbox'] for c in recognition.get('barcodes',[]) if c.get('coordinate_space')=='original' and c.get('bbox')]
        proposals=locate_labels(image,boxes)
    for p in proposals[:4]:
        add('required_region',p['polygon'],'OpenCV:'+p.get('method','candidate'),score=p.get('score'),
            note='Candidate only; may include optional label content or background')
    boxes=recognition.get('box_candidates') or []
    if not boxes and proposals:boxes=box_geometry_candidates(image,proposals[0]['polygon'])
    for p in boxes[:3]:
        add('box_outline',p.get('polygon') if isinstance(p,dict) else p,'OpenCV:box_geometry',note='Geometric outline; physical box and faces unverified')
    for p in recognition.get('phone_candidates',[])[:3]:
        add('screen_frame',p['polygon'],'OpenCV:phone_frame',note='Frame candidate alone is not a recapture defect')
    return objects


def prepare(manifest,baseline,workbook,approved_docx,rejected_docx,output):
    output=Path(output)
    if any(p.exists() for p in (output,output.with_suffix('.html'),output.with_suffix('.summary.json'))):
        raise ValueError('OUTPUT_EXISTS_KEEP_PRIOR_VERSIONS')
    data=copy.deepcopy(validate(json.loads(Path(manifest).read_text(encoding='utf-8'))))
    refs=official_rows(workbook);proof={}
    for p,category in [(approved_docx,'APPROVED'),(rejected_docx,'REJECTED')]:
        for digest,row in docx_photos(p,category).items():
            if digest in proof:raise ValueError('PHOTO_IN_BOTH_CATEGORIES')
            proof[digest]=row
    baseline=json.loads(Path(baseline).read_text(encoding='utf-8'));mapping={}
    for c in baseline['cases']:
        for p in c['photos']:
            if p['sha256'] in mapping:raise ValueError('DUPLICATE_BASELINE_PHOTO')
            mapping[p['sha256']]=(c['case_id'],p)
    if set(proof)!=set(p['sha256'] for p in data['images']):raise ValueError('OFFICIAL_PHOTO_SET_DIFFERS')
    counts=Counter();proposals=Counter();seen_roles=Counter()
    for p in data['images']:
        digest=p['sha256'];key,recognition=mapping[digest];ref=refs[key];document=proof[digest]
        if document['category']!=ref['category'] or document['role']!=recognition['role']:raise ValueError('OFFICIAL_DOCUMENT_DISAGREEMENT')
        raw=Path(p['image']).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=digest:raise ValueError('SOURCE_CHANGED')
        pixels=read_image(raw);role=recognition['role']
        if pixels.shape[:2]!=(p['height'],p['width']):raise ValueError('SOURCE_DIMENSIONS_CHANGED')
        generated=propose_regions(pixels,recognition)  # No official metadata passed.
        # Keep prior explicit human regions; never make predictions into human truth.
        prior=[o for o in p['objects'] if o.get('reviewed') and not o.get('source','').startswith('OpenCV:')]
        p['objects']=prior+generated;p['role']=role
        p['official']=dict(category=ref['category'],case_id=key,case_alias=ref['case_alias'],
            role=role,reason=ref['reasons'][role],reason_code=ref['reason_codes'][role],
            target_classes=list(TARGETS.get(ref['reason_codes'][role],())),
            category_source='Final_Status',registration_status=ref['registration'],
            registration_conflict=ref['registration_conflict'],
            workbook=dict(file=Path(workbook).name,sha256=hashlib.sha256(Path(workbook).read_bytes()).hexdigest(),
                          status_cell=ref['cells']['status'],reason_cell=ref['cells'][role]),document=document)
        counts[ref['category']]+=1;proposals.update(o['class'] for o in generated);seen_roles[key,role]+=1
    if set(seen_roles)!={(key,role) for key in refs for role in ('device','scan')} or any(n!=1 for n in seen_roles.values()):
        raise ValueError('OFFICIAL_CASE_ROLES_INCOMPLETE_OR_DUPLICATE')
    data['images'].sort(key=lambda p:(p['official']['case_alias'],p['role']!='device'))
    data['notice']='Private official example context. Final_Status is authoritative. Labels are not inference inputs. Orange regions are unverified proposals, not training truth.'
    validate(data);output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    editor(output,output.with_suffix('.html'))
    summary=dict(photos=len(data['images']),categories=dict(counts),registration_conflicts=sum(r['registration_conflict'] for r in refs.values()),
                 docx_exact_matches=len(proof),proposals=dict(proposals),classification_changed=False)
    output.with_suffix('.summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    return summary


def learning_rows(data):
    """Export reviewed region targets only, with group metadata outside features.

    This is a dataset contract, not a fitted model. Never exports final-case
    answers, filenames, IDs, text values or watermark tokens as model features.
    Rejected is negative only for its documented role-specific criterion.
    """
    validate(data);rows=[]
    for p in data['images']:
        official=p.get('official')
        if not official:continue
        if (official['category']=='REJECTED' and official['reason_code']=='IDENTIFICATION_MISSING'
                and p['reviews']['required_region']=='ABSENT' and p.get('absence_review',{}).get('required_region')):
            rows.append(dict(group=p['case_group'],role=p['role'],target='negative_criterion_absence',
                             criterion='IDENTIFICATION_MISSING',region_class='required_region',polygon=None,
                             source='reviewed_absence',feature_policy='Image evidence only; absence target is not an inference feature'))
        for obj in p['objects']:
            if not obj.get('reviewed'):continue
            kind=obj['class'];reason=official['reason_code']
            if official['category']=='APPROVED':
                if kind not in {'box_outline','top_face','identification_face','required_region','barcode','identifier_text'}:continue
                target='positive_region'
            elif (reason=='INFORMATION_QUALITY' and kind=='required_region'
                  and obj.get('defect_kind')=='INFORMATION_QUALITY' and obj.get('official_quality_region')):
                # Official broad quality label + independently localized target.
                # Do not invent blur/darkness/glare sublabels from a combined reason.
                target='negative_criterion_region'
            elif kind in TARGETS.get(reason,()):
                # A combined quality reason cannot prove which quality defect occurred.
                if reason=='INFORMATION_QUALITY' and not obj.get('defect_verified'):continue
                if reason=='IDENTIFICATION_MISSING':continue  # Absence is not a positive region.
                target='negative_criterion_region'
            else:continue
            rows.append(dict(group=p['case_group'],role=p['role'],target=target,criterion=reason if target.startswith('negative') else kind,
                             region_class=kind,polygon=obj['polygon'],source='reviewed_region',
                             feature_policy='Pixels/relative geometry only; group/target/criterion are not inference features'))
    return dict(schema_version=1,rows=rows,trained_model=False,
                notice='Development annotations only. Split entire case groups before training; require new independent photos for quality evaluation.')


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='action',required=True)
    a=sub.add_parser('prepare');a.add_argument('manifest',type=Path);a.add_argument('baseline',type=Path);a.add_argument('description',type=Path);a.add_argument('output',type=Path)
    a=sub.add_parser('export-reviewed');a.add_argument('manifest',type=Path);a.add_argument('output',type=Path)
    a=p.parse_args()
    if a.action=='prepare':
        print(json.dumps(prepare(a.manifest,a.baseline,a.description/'VALIDATION.xlsx',a.description/'Approved_photo_cases.docx',a.description/'Rejected_photo_cases.docx',a.output)))
    else:
        if a.output.exists():raise ValueError('OUTPUT_EXISTS_KEEP_PRIOR_VERSIONS')
        result=learning_rows(json.loads(a.manifest.read_text(encoding='utf-8')))
        a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps(dict(reviewed_targets=len(result['rows']),trained_model=False)))

if __name__=='__main__':main()
