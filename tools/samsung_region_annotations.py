"""Private polygon editor. Optional official context is never inference input."""
import argparse
import hashlib
import json
import math
import base64
from pathlib import Path

CLASSES=('box_outline','top_face','identification_face','required_region','barcode','identifier_text',
         'crop','blur','darkness','glare','occlusion','screen_recapture','screen_frame','screen_ui')
STATES=('UNKNOWN','PRESENT','ABSENT','NOT_APPLICABLE')

def polygon_area(points):
    return abs(sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(points,points[1:]+points[:1])))/2

def validate(data):
    if data.get('schema_version')!=2 or data.get('classes')!=list(CLASSES):raise ValueError('REGION_SCHEMA_REQUIRED')
    seen=set()
    for item in data['images']:
        digest=item['sha256']
        if len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest) or digest in seen:raise ValueError('INVALID_OR_DUPLICATE_DIGEST')
        seen.add(digest)
        if item.get('role') not in {None,'device','scan'}:raise ValueError('INVALID_ROLE')
        context=item.get('official')
        if context is not None:
            if context.get('category') not in {'APPROVED','REJECTED'} or context.get('category_source')!='Final_Status':raise ValueError('INVALID_OFFICIAL_CATEGORY')
            if context.get('role')!=item.get('role') or not context.get('case_id') or not context.get('reason'):raise ValueError('INVALID_OFFICIAL_CONTEXT')
        if not item.get('case_group'):raise ValueError('CASE_GROUP_REQUIRED')
        if set(item['reviews'])!=set(CLASSES) or any(s not in STATES for s in item['reviews'].values()):raise ValueError('INVALID_REVIEW')
        for obj in item['objects']:
            points=obj.get('polygon',[])
            if obj.get('class') not in CLASSES or not 3<=len(points)<=20:raise ValueError('INVALID_POLYGON')
            if any(len(p)!=2 or any(not isinstance(v,(int,float)) or not math.isfinite(v) or not 0<=v<=1 for v in p) for p in points):raise ValueError('INVALID_POLYGON')
            if polygon_area(points)<1e-7:raise ValueError('DEGENERATE_POLYGON')
            # Crossing non-neighbour edges are never valid visible regions.
            def side(a,b,c):return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
            edges=list(zip(points,points[1:]+points[:1]))
            for i,(a,b) in enumerate(edges):
                for j,(c,d) in enumerate(edges):
                    if j<=i+1 or (i==0 and j==len(edges)-1):continue
                    if side(a,b,c)*side(a,b,d)<0 and side(c,d,a)*side(c,d,b)<0:raise ValueError('SELF_INTERSECTING_POLYGON')
        for kind,state in item['reviews'].items():
            reviewed=any(o['class']==kind and o.get('reviewed') is True for o in item['objects'])
            if state=='PRESENT' and not reviewed:raise ValueError('PRESENT_WITHOUT_REVIEWED_REGION')
            if state in {'ABSENT','NOT_APPLICABLE'} and reviewed:raise ValueError('REVIEW_CONTRADICTS_REGION')
    return data

def initialize(old):
    result=dict(schema_version=2,classes=list(CLASSES),
                notice='Manual semantic regions only. UNKNOWN is not ABSENT. No expected outcomes, identifier values or automatic decisions.',images=[])
    mapping={'box':'box_outline','factory_label':'required_region','identification_region':'required_region','phone_screen':'screen_frame'}
    for p in old['images']:
        row={k:p[k] for k in ['photo_id','sha256','image','width','height','case_group']}
        row.update(role=p.get('role'),objects=[],reviews={c:'UNKNOWN' for c in CLASSES})
        for obj in p.get('objects',[]):
            if obj['class'] not in mapping:continue
            x,y,r,b=obj['bbox'];row['objects'].append(dict(**{'class':mapping[obj['class']]},polygon=[[x,y],[r,y],[r,b],[x,b]],reviewed=False,source='migrated_bbox_proposal'))
        result['images'].append(row)
    return validate(result)

def editor(manifest,output):
    data=validate(json.loads(Path(manifest).read_text(encoding='utf-8')))
    for item in data['images']:
        raw=Path(item['image']).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=item['sha256']:raise ValueError('SOURCE_CHANGED')
        item['data_url']='data:image/jpeg;base64,'+base64.b64encode(raw).decode('ascii')
    template=Path(__file__).with_suffix('.html').read_text(encoding='utf-8')
    target=Path(output)
    if target.resolve()==Path(manifest).resolve() or target.exists():raise ValueError('OUTPUT_EXISTS_KEEP_PRIOR_VERSIONS')
    target.parent.mkdir(parents=True,exist_ok=True)
    serialized=json.dumps(data,ensure_ascii=False).replace('<',chr(92)+'u003c')
    target.write_text(template.replace('/*LOCAL_MANIFEST*/{}',serialized),encoding='utf-8')

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['init','editor','validate']);p.add_argument('manifest',type=Path);p.add_argument('output',type=Path,nargs='?');a=p.parse_args()
    data=json.loads(a.manifest.read_text(encoding='utf-8'))
    if a.action=='validate':validate(data);print('Local region annotations valid; no automatic decisions');return
    if not a.output:p.error('Output required')
    if a.output.exists():p.error('Output exists; preserve prior versions')
    if a.action=='init':a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(initialize(data),indent=2),encoding='utf-8')
    else:editor(a.manifest,a.output)

if __name__=='__main__':main()
