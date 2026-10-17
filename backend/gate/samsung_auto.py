"""Automatic local box/label research profile and explicit fail-closed final policy.

No filenames, case labels, expected IDs or dataset statistics enter photo analysis.
Rules are engineering rules, not claimed validated Samsung detectors.
"""
from collections import defaultdict
import hashlib
import os
import re
import time
from pathlib import Path

import cv2
import numpy as np

from .decoder import ZXingDecoder
from .local_ocr import read_local_variants
from .samsung import valid_imei
from .samsung_barcodes import enhanced_barcodes, scaled_barcodes, LINEAR_IMEI_FORMATS
from .samsung_preprocessing import roi_variant_matrix,variant_to_original
from .samsung_vision import locate_labels, rectify, variants, diagnostic, phone_frame_candidates, box_geometry_candidates

VERSION='samsung-auto-0.9.0'
REQUIRED=('label_present','label_complete','box_evidence','imei_readable',
          'no_crop','no_field_glare','no_field_occlusion','no_critical_blur','physical_object')
ADVISORY=('model_readable','serial_readable')


def parse_fields(text):
    """No fuzzy correction. A model family and a longer sellable SKU are separate."""
    fields=[]
    for m in re.finditer(r'\bIMEI\s*([12]?)\s*[:：-]?\s*([0-9][0-9 ]{13,23}[0-9])',text,re.I):
        value=m.group(2).replace(' ','')
        if len(value)==15:fields.append(('imei'+(m.group(1) or ''),value,valid_imei(value)))
    for m in re.finditer(r'\bSM-[A-Z0-9/]{4,24}\b',text,re.I):
        value=m.group().upper()
        if re.fullmatch(r'SM-[A-Z][0-9]{3}[A-Z0-9]?(?:/DS)?',value):key='model'
        else:key='sku'
        fields.append((key,value,key=='model' or bool(re.fullmatch(r'SM-[A-Z][0-9]{3}[A-Z0-9]{4,16}',value))))
    for m in re.finditer(r'(?:\bS\s*/\s*N|\bSerial(?:\s+No\.?)?)\s*[:：-]?\s*([A-Z0-9]{8,16})\b',text,re.I):
        fields.append(('serial',m.group(1).upper(),True))
    for m in re.finditer(r'\b(32|64|128|256|512|1024)\s*GB\b',text,re.I):
        fields.append(('storage_gb',m.group(1),True))
    return fields


def summarize_fields(records):
    grouped=defaultdict(list)
    for r in records:
        value=r['value'].removesuffix('/DS') if r['key']=='model' else r['value']
        grouped[(r['key'],value)].append(r)
    fields=[]
    for (key,value),evidence in sorted(grouped.items()):
        if key in {'imei1','imei2'}:
            evidence=evidence+[e for e in grouped.get(('imei',value),[]) if e['source']=='barcode']
        methods={e['variant'] for e in evidence if e['format_valid']}
        barcode=any(e['source']=='barcode' and e['format_valid'] for e in evidence)
        repeated=len(methods)>=2
        candidates={v for (k,v) in grouped if k==key}
        raw_conflict=key in {'imei1','imei2','model','sku','serial'} and len(candidates)>1
        # An invalid checksum string remains a raw OCR observation, but cannot
        # contradict a unique indexed IMEI exactly corroborated by a decode.
        # Two valid alternatives still conflict, even if only one is decoded.
        admissible={v for (k,v),items in grouped.items() if k==key and
                    valid_imei(v) and all(e['format_valid'] for e in items)}
        resolved_invalid_only=(key in {'imei1','imei2'} and barcode and
                               admissible=={value} and valid_imei(value))
        conflict=raw_conflict and not resolved_invalid_only
        fields.append(dict(key=key,value=value,format_valid=all(e['format_valid'] for e in evidence),
            confirmed=barcode and not conflict,mismatch_eligible=barcode and not conflict,
            conflicted=conflict,raw_conflicted=raw_conflict,repeat_consistent=repeated,independent_evidence=False,
            confirmation='conflicting_readings' if conflict else 'barcode_checksum_and_format' if barcode else 'same_photo_repeat_only' if repeated else 'single_read',
            evidence=evidence))
    return fields


def _union_bounds(boxes):
    return [min(b[0] for b in boxes),min(b[1] for b in boxes),max(b[2] for b in boxes),max(b[3] for b in boxes)]


def indexed_candidate_mismatches(photos):
    """Prove disjointness without selecting a preferred conflicting reading.

    Every format-valid alternative must be corroborated by an actual linear
    decode on its own photo. An uncorroborated valid alternative blocks proof.
    Invalid OCR strings remain in fields/findings; none are repaired or selected.
    Unindexed single-SIM subsets are deliberately not compared this way.
    """
    findings=[];comparisons=[]
    for key in ('imei1','imei2'):
        sides=[]
        for p in photos:
            candidates={f['value'] for f in p['fields'] if f['key']==key and f['format_valid'] and valid_imei(f['value'])}
            decoded={b['value'] for b in p.get('barcodes',[]) if b.get('checksum_valid') and
                     b['type'] in LINEAR_IMEI_FORMATS and valid_imei(b['value'])}
            sides.append(dict(role=p['role'],sha256=p['sha256'],candidates=sorted(candidates),
                              decoded_imeis=sorted(decoded),all_corroborated=bool(candidates) and candidates<=decoded))
        proof=any(a['role']=='device' and b['role']=='scan' and a['sha256']!=b['sha256'] and
                  a['all_corroborated'] and b['all_corroborated'] and
                  not set(a['candidates']).intersection(b['candidates']) and
                  not set(a['decoded_imeis']).intersection(b['decoded_imeis']) for a in sides for b in sides)
        comparisons.append(dict(field=key,state='FAIL' if proof else 'UNKNOWN',strategy='all_valid_indexed_candidates_corroborated',sides=sides,
                                selected_value=None,notice='No PASS from this comparison; ambiguous or incomplete matching sets do not prove photo quality.'))
        if proof:findings.append(dict(code=key.upper()+'_CANDIDATE_SET_MISMATCH',state='FAIL',category='identifier_mismatch',
            reason='All format-valid indexed candidates on both photos are exactly corroborated by linear barcodes and the sets are disjoint. No conflicting value was selected; invalid readings are retained.'))
    return findings,comparisons


def analyze_photo(image, data, role, use_ocr=True, cache_dir=None, diagnostic_dir=None):
    started=time.perf_counter()
    profile=os.getenv('SAMSUNG_RECOGNITION_PROFILE','original')
    if profile not in {'original','enhanced'}:raise ValueError('UNKNOWN_SAMSUNG_RECOGNITION_PROFILE')
    digest=hashlib.sha256(data).hexdigest();h,w=image.shape[:2]
    decoder=ZXingDecoder(); codes=[];records=[];seen=set()
    def collect_codes(pixels, variant, region=None,matrix=None):
        for b in decoder.decode(pixels):
            if not b.decoded or not b.value:continue
            signature=(b.type,b.value,variant)
            if signature in seen:continue
            seen.add(signature)
            polygon=variant_to_original(b.polygon,matrix) if matrix is not None else b.polygon
            q=np.float32(polygon)
            bbox=[float(q[:,0].min()),float(q[:,1].min()),float(q[:,0].max()),float(q[:,1].max())]
            codes.append(dict(type=b.type,value=b.value,variant=variant,region=region,bbox=bbox,polygon=polygon,
                              original_to_variant=matrix,coordinate_space='original',
                              source='barcode',checksum_valid=True))
            if b.type in LINEAR_IMEI_FORMATS and valid_imei(b.value):
                records.append(dict(key='imei',value=b.value,format_valid=True,source='barcode',variant=variant,region=region,
                                    bbox=bbox,polygon=polygon,coordinate_space='original',original_to_variant=matrix,
                                    symbology=b.type,checksum_valid=True,imei_luhn_valid=True,
                                    quality='native_pixels' if variant=='original' else 'rectified_preprocessed_pixels'))
    collect_codes(image,'original')
    original_boxes=[c['bbox'] for c in codes if c['bbox'] and c['type'] not in {'QR Code'}]
    proposals=locate_labels(image,original_boxes,limit=3)
    for code in enhanced_barcodes(image,proposals):
        codes.append(code)
        records.append(dict(key='imei',value=code['value'],format_valid=True,source='barcode',
                            variant=code['variant'],region=None,bbox=code['bbox'],
                            polygon=code['polygon'],coordinate_space='original',
                            quality=code['quality'],symbology=code['type'],checksum_valid=True))
    crops=[];ocr_images=[];meta=[]
    for i,p in enumerate(proposals):
        crop,matrix=rectify(image,p['polygon']);crops.append(crop)
        # Both portrait and upside-down input are covered, not only original camera orientation.
        for name,pixels in variants(crop,orientations=(0,2,1,3)):
            # Decode all variants; OCR uses two photometric variants for each orientation.
            transform=roi_variant_matrix(matrix,int(name.split('-')[0][1:])//90,
                crop.shape[1],crop.shape[0],pixels.shape[1],pixels.shape[0])
            collect_codes(pixels,f'roi{i}-{name}',p['polygon'],transform)
            if not name.endswith('binary'):
                ocr_images.append(pixels);meta.append(dict(variant=f'roi{i}-{name}',region=p['polygon'],
                    perspective_matrix=matrix.tolist(),original_to_variant=transform,variant_width=pixels.shape[1],variant_height=pixels.shape[0],
                    rectified_width=crop.shape[1],rectified_height=crop.shape[0]))
    scaling=dict(performed=False,reason='profile_original')
    if profile=='enhanced':
        if any(r['source']=='barcode' for r in records):scaling['reason']='existing_barcode_search_succeeded'
        elif max(h,w)>=6000:scaling['reason']='image_at_size_limit'
        else:
            scaling=dict(performed=True,reason='no_imei_after_existing_search',seconds=0.)
            scale_start=time.perf_counter()
            for code in scaled_barcodes(image):
                codes.append(code)
                records.append(dict(key='imei',format_valid=True,**{k:v for k,v in code.items() if k!='type'},symbology=code['type']))
            scaling['seconds']=round(time.perf_counter()-scale_start,3)
    # Full frame OCR is diagnostic (branding/screen UI), never enough to read the label.
    if use_ocr:
        scale=min(1.,2000/max(h,w));full=cv2.resize(image,(round(w*scale),round(h*scale)))
        ocr_images.append(full);meta.append(dict(variant='full-frame',region=None,
            original_to_variant=np.diag([full.shape[1]/w,full.shape[0]/h,1.]).tolist()))
        reads=read_local_variants(ocr_images,cache_dir)
    else:reads=[{'status':'NOT_RUN','lines':[]} for _ in ocr_images]
    ocr=[];text_by_roi=defaultdict(list)
    for info,read in zip(meta,reads):
        lines=read.get('lines',[]);text='\n'.join(l.get('text','') for l in lines)
        ocr.append(dict(**info,status=read.get('status'),language=read.get('language'),lines=lines))
        text_by_roi[info['variant'].split('-')[0]].append(text)
        for line in lines:
            for key,value,valid in parse_fields(line.get('text','')):
                # Full-frame OCR may assign a printed SIM slot only when the
                # exact digits are independently decoded from a linear symbol.
                # Branding/model text outside the label is never label evidence.
                if info['region'] is None and not (key in {'imei1','imei2'} and valid and
                        any(r['source']=='barcode' and r['value']==value for r in records)):
                    continue
                records.append(dict(key=key,value=value,format_valid=valid,source='windows_local_ocr',
                                    variant=info['variant'],region=info['region'],words=line.get('words',[]),
                                    quality='uncalibrated_ocr',confidence=None,
                                    coordinate_space='variant',perspective_matrix=info.get('perspective_matrix')))
                records[-1]['original_to_variant']=info.get('original_to_variant')
    pretrained=dict(status='NOT_SELECTED')
    if use_ocr and os.getenv('SAMSUNG_OCR_ENGINE','legacy')=='ppocrv5':
        try:
            from .samsung_pretrained import read_pretrained,extract_records
            pretrained=read_pretrained(image,Path(cache_dir)/'pretrained' if cache_dir else None,enhance=profile=='enhanced')
            records.extend(extract_records(pretrained))
        except (ImportError,OSError,ValueError,RuntimeError) as exc:
            # Optional deployment cannot silently claim model evidence on failure.
            pretrained=dict(status='UNAVAILABLE',reason=type(exc).__name__+': '+str(exc))
    for record in records:
        record.update(evidence_group=digest,independent_evidence=False)
        record.setdefault('coordinate_space','original')
        record.setdefault('processing',record['variant'])
        record.setdefault('confidence',None);record.setdefault('confidence_calibrated',False)
    fields=summarize_fields(records)
    checks={name:dict(state='UNKNOWN',reason='Insufficient verified evidence',source='local_rule',preliminary=True) for name in REQUIRED+('model_readable',)}
    problems=[]
    def setcheck(name,state,reason):checks[name]=dict(state=state,reason=reason,source='local_rule',preliminary=True)
    conflicts=sorted({f['key'] for f in fields if f.get('conflicted')})
    if conflicts:setcheck('recognition_conflicts','UNKNOWN','Conflicting same-photo readings retained: '+', '.join(conflicts))
    # Confirm the semantic label from text/identity evidence located in a proposed region.
    supported=[]
    for i,p in enumerate(proposals):
        prefix=f'roi{i}-'
        good=[r for r in records if r['variant'].startswith(prefix) and r['format_valid']]
        kinds={r['key'] for r in good}
        identity=any(k.startswith('imei') for k in kinds)
        model='model' in kinds
        if identity and model:supported.append(i)
    label_index=max(supported,key=lambda i:(proposals[i]['method'] in {'light_boundary','edge_boundary'},
                                          not proposals[i]['touches_border'],proposals[i]['score'])) if supported else None
    label=proposals[label_index] if label_index is not None else None
    if label:
        setcheck('label_present','PASS','Factory-format model and valid IMEI found in the same geometric ROI.')
        # Avoid equating a barcode-context crop to the whole physical label.
        if label['method']=='light_boundary' and not label['touches_border']:
            setcheck('no_crop','PASS','Observed light-region boundary lies inside the image; semantic completeness checked separately.')
        if label['touches_border']:
            setcheck('no_crop','UNKNOWN',
                     'Identification label proposal meets the frame edge; content may extend outside the frame.')
            problems.append(dict(code='LABEL_AT_BORDER',bbox=label['bbox']))
        gray=cv2.cvtColor(crops[label_index],cv2.COLOR_BGR2GRAY)
        sharp=float(cv2.Laplacian(gray,cv2.CV_64F).var())
        # Broad white connected stripe inside a textured label, not arbitrary frame glare.
        white=(gray>=252).astype('uint8')
        n,_,stats,_=cv2.connectedComponentsWithStats(white)
        glare=[s for s in stats[1:] if s[4]>gray.size*.025 and s[3]>gray.shape[0]*.4 and s[2]<gray.shape[1]*.3]
        if glare:
            setcheck('no_field_glare','UNKNOWN','Bright stripe intersects a candidate label; mandatory-field overlap needs verified localization.')
        setcheck('no_critical_blur','FAIL' if sharp<8 else 'PASS' if sharp>80 else 'UNKNOWN',
                 f'Original rectified label Laplacian variance={sharp:.2f}; engineering thresholds, not calibrated Samsung limits.')
    valid_imeis={f['value'] for f in fields if f['key'].startswith('imei') and f['confirmed'] and f['format_valid']}
    models={f['value'].removesuffix('/DS') for f in fields if f['key']=='model' and f['confirmed']}
    if valid_imeis:setcheck('imei_readable','PASS','At least one format-valid, confirmed IMEI. Full dual-SIM coverage is checked separately.')
    if len(models)==1:setcheck('model_readable','PASS','One independently corroborated model family; SKU kept separate.')
    elif len(models)>1:setcheck('model_readable','UNKNOWN','Conflicting recognized model families.')
    # Identity+model alone are not proof of the full label, no occlusion, or physical box.
    text='\n'.join(t for v in text_by_roi.values() for t in v).lower()
    screen_ui=any(marker in text for marker in ('whatsapp','telegram','message info','в сети','переслано','reply','ответить'))
    phones=phone_frame_candidates(image)
    if screen_ui and phones:
        setcheck('physical_object','FAIL','Phone-shaped dark frame and messaging-interface text jointly support screen recapture.')
        problems.append(dict(code='SCREEN_RECAPTURE_RULE',bbox=phones[0]['bbox']))
    elif screen_ui or phones:
        setcheck('physical_object','UNKNOWN','Screen frame or interface suspected; neither signal alone proves recapture.')
    # Cross-field coverage: if IMEI2 is explicitly printed, a single decoded IMEI is incomplete.
    expects_two=bool(re.search(r'\bimei\s*2\b',text,re.I))
    if expects_two and len(valid_imeis)<2:
        setcheck('additional_imei_readable','UNKNOWN','Observed IMEI2 marker; second value not confirmed. Field schema has not established mandatory cardinality.')
    boxes=box_geometry_candidates(image,label['polygon'] if label else None)
    # A closed geometric outline does not prove readable, unobstructed content.
    # Neither a pair of decoded IMEIs nor absence of skin establishes this.
    setcheck('label_complete','UNKNOWN','Whole-label visibility has no verified detector or required-field schema; decoded identifiers alone cannot establish completeness.')
    setcheck('no_field_occlusion','UNKNOWN','No validated arbitrary-occluder detector or field-coverage localization is installed.')
    if re.search(r'\bS\s*/\s*N\b|\bserial\b',text,re.I):
        setcheck('serial_readable','PASS' if any(f['key']=='serial' and f['confirmed'] for f in fields) else 'UNKNOWN',
                 'Serial marker is present; an unrecognized serial cannot be silently ignored.')
    if role=='scan':
        setcheck('box_evidence','PASS','Full box context is checked on device; scan is the label close-up.')
    elif boxes and label and 'galaxy' in text and not phones:
        # Branding is a secondary cue; Samsung top-left export watermark alone is not used.
        setcheck('box_evidence','PASS','Factory-format label, enclosing box-like contour and Galaxy text support apparent box geometry.')
        setcheck('physical_object','PASS','Box-like contour supported and no phone-frame/interface cue; preliminary screen-recapture rule, not authenticity proof.')
    photo=dict(sha256=digest,role=role,width=w,height=h,proposals=proposals,label_index=label_index,phone_candidates=phones,box_candidates=boxes,
                checks=checks,fields=fields,barcodes=codes,ocr=ocr,pretrained_ocr=pretrained,problems=problems,
                extraction=dict(confirmed_imeis=sorted(valid_imeis),confirmed_models=sorted(models),expects_two_imeis=expects_two),
                recognition_profile=profile,extra_passes=dict(zxing_scale2=scaling),
                elapsed_seconds=round(time.perf_counter()-started,3),algorithm_version=VERSION)
    if os.getenv('SAMSUNG_POLICY_PROFILE','role-v1')=='role-v1':
        from .samsung_policy import apply_role_policy
        if use_ocr and any(b.get('checksum_valid') and b.get('type') in {'Code 128','Code 39','ITF'} for b in codes):
            from .samsung_screen import read_screen_ui
            photo['screen_ui_ocr']=read_screen_ui(image,Path(cache_dir)/'screen' if cache_dir else None)
        elif use_ocr:
            photo['screen_ui_ocr']=dict(status='SKIPPED_NO_CODED_TARGET',reads=[])
        photo=apply_role_policy(photo,image)
        photo['elapsed_seconds']=round(time.perf_counter()-started,3)
    if diagnostic_dir:
        target=Path(diagnostic_dir);target.mkdir(parents=True,exist_ok=True)
        output=diagnostic(image,proposals,photo['problems'],boxes)
        factor=min(1.,1800/max(h,w));output=cv2.resize(output,(round(w*factor),round(h*factor)))
        cv2.imencode('.jpg',output)[1].tofile(str(target/f'{digest}.jpg'))
        for i,crop in enumerate(crops):cv2.imencode('.png',crop)[1].tofile(str(target/f'{digest}-roi{i}.png'))
    photo['elapsed_seconds']=round(time.perf_counter()-started,3)
    return photo


def classify_case(photos):
    """Final binary status and separate evidence coverage. Unknown never means APPROVED."""
    import copy
    photos=copy.deepcopy(photos)
    # A close-up may omit the box outline. Inherit case-level physical support only
    # when both model and the complete two-IMEI set agree and no recapture cue exists.
    devices=[p for p in photos if p['role']=='device' and p['checks'].get('physical_object',{}).get('state')=='PASS']
    for scan in (p for p in photos if p['role']=='scan'):
        if scan.get('phone_candidates') or scan['checks'].get('physical_object',{}).get('state')=='FAIL':continue
        for device in devices:
            a=device.get('extraction',{});b=scan.get('extraction',{})
            if len(a.get('confirmed_imeis',[]))>=2 and a.get('confirmed_imeis')==b.get('confirmed_imeis') and a.get('confirmed_models') and a.get('confirmed_models')==b.get('confirmed_models'):
                scan['checks']['physical_object']=dict(state='PASS',source='case_consistency',preliminary=True,reason='Complete two-IMEI set and model agree with device box evidence; no scan phone-frame cue.')
    findings=[];comparisons=[];advisories=[]
    for role in ('device','scan'):
        if not any(p['role']==role for p in photos):findings.append(dict(code='MISSING_'+role.upper(),state='FAIL',category='proven_defect'))
    for p in photos:
        grouped_values=defaultdict(set)
        for field in p['fields']:
            if field['key'] in {'imei1','imei2','model','sku','serial'}:
                grouped_values[field['key']].add(field['value'].removesuffix('/DS') if field['key']=='model' else field['value'])
        p['conflicting_fields']=sorted(k for k,v in grouped_values.items() if len(v)>1)
        p['raw_conflicting_fields']=list(p['conflicting_fields'])
        decoded={b['value'] for b in p.get('barcodes',[]) if b.get('checksum_valid') and
                 b.get('type') in LINEAR_IMEI_FORMATS and valid_imei(b['value'])}
        for key in ('imei1','imei2'):
            relevant=[f for f in p['fields'] if f['key']==key]
            valid={f['value'] for f in relevant if f['format_valid'] and valid_imei(f['value'])}
            if key in p['conflicting_fields'] and len(valid)==1 and valid<=decoded and any(
                    f['value'] in valid and f.get('confirmed') and not f.get('conflicted') for f in relevant):
                p['conflicting_fields'].remove(key)
                advisories.append(dict(code='INVALID_'+key.upper()+'_OCR_ALTERNATIVES',state='UNKNOWN',
                    photo_sha256=p['sha256'],reason='Invalid checksum observations retained; the unique valid indexed value is exactly corroborated by a linear decode. This does not prove photo completeness.'))
        for key in p['conflicting_fields']:
            target=advisories if p.get('policy_profile')=='role-v1' and key in {'model','sku'} else findings
            target.append(dict(code='CONFLICTING_'+key.upper()+'_READINGS',state='UNKNOWN',
                photo_sha256=p['sha256'],category='insufficient_evidence',
                reason='Same-photo variants disagree; no candidate selected automatically.'))
        mandatory=p.get('mandatory_checks',REQUIRED)
        for key in mandatory:
            if key not in p['checks']:
                findings.append(dict(code=key.upper(),state='UNKNOWN',photo_sha256=p['sha256'],category='insufficient_evidence',reason='Mandatory check missing from analyzer output.'))
        for key,check in p['checks'].items():
            if key not in mandatory and p.get('mandatory_checks'):
                if check['state']!='PASS':advisories.append(dict(code=key.upper(),state=check['state'],photo_sha256=p['sha256'],reason=check['reason']))
                continue
            if key in ADVISORY or key=='additional_imei_readable':
                if check['state']!='PASS':advisories.append(dict(code=key.upper(),state=check['state'],photo_sha256=p['sha256'],reason=check['reason']))
                continue
            if check['state']!='PASS':findings.append(dict(code=key.upper(),state=check['state'],
                photo_sha256=p['sha256'],category='proven_defect' if check.get('confirmed_failure') else 'observed_rule_failure' if check['state']=='FAIL' else 'insufficient_evidence',reason=check['reason']))
    for key in ('imei','imei1','imei2','serial','model','sku'):
        sets=[];reliable=[]
        for p in photos:
            values={f['value'].removesuffix('/DS') if key=='model' else f['value'] for f in p['fields']
                    if (f['key'].startswith('imei') if key=='imei' else f['key']==key) and f['confirmed'] and f['format_valid'] and f['key'] not in p['conflicting_fields']}
            sets.append(values)
            reliable.append({f['value'].removesuffix('/DS') if key=='model' else f['value'] for f in p['fields']
                if (f['key'].startswith('imei') if key=='imei' else f['key']==key) and f.get('mismatch_eligible',False) and f['format_valid'] and f['key'] not in p['conflicting_fields']})
        available=[v for v in sets if v]
        # Unindexed partial sets may refer to different slots of a valid dual-SIM device.
        comparable=key!='imei' or all(len(v)>=2 for v in sets)
        discrepancy=any(not a.intersection(b) for i,a in enumerate(available) for b in available[i+1:])
        strong=[v for v in reliable if v]
        strong_comparable=key!='imei' or all(len(v)>=2 for v in reliable)
        mismatch=strong_comparable and any(not a.intersection(b) for i,a in enumerate(strong) for b in strong[i+1:])
        match=len(sets)>=2 and all(sets) and all(v==sets[0] for v in sets)
        status='FAIL' if mismatch else 'PASS' if match else 'UNKNOWN'
        comparisons.append(dict(field=key,state=status,values=[sorted(v) for v in sets]))
        if mismatch:findings.append(dict(code=key.upper()+'_MISMATCH',state='FAIL',category='identifier_mismatch'))
        elif discrepancy:findings.append(dict(code='POSSIBLE_'+key.upper()+'_MISMATCH',state='UNKNOWN',category='insufficient_evidence',reason='Repeat OCR consensus is not independent confirmation.'))
        elif key=='imei' and not match:findings.append(dict(code=key.upper()+'_CONSISTENCY',state='UNKNOWN',category='insufficient_evidence'))
        if key=='imei' and not comparable and len(available)>1 and any(not a.intersection(b) for i,a in enumerate(available) for b in available[i+1:]):
            findings.append(dict(code='POSSIBLE_IMEI_MISMATCH',state='UNKNOWN',category='insufficient_evidence',reason='Unindexed partial sets cannot establish which SIM slot is being compared.'))
    candidate_findings,candidate_comparisons=indexed_candidate_mismatches(photos)
    findings.extend(candidate_findings);comparisons.extend(candidate_comparisons)
    if len({p['sha256'] for p in photos})<len(photos):
        findings.append(dict(code='REUSED_IMAGE',state='UNKNOWN',category='insufficient_evidence'))
    failures=[f for f in findings if f['state']=='FAIL'];unknown=[f for f in findings if f['state']=='UNKNOWN']
    diagnostic_state='FAIL' if failures else 'UNKNOWN' if unknown else 'PASS'
    reason='identifier_mismatch' if any(f['category']=='identifier_mismatch' for f in failures) else 'detected_defect' if failures else 'insufficient_evidence' if unknown else 'all_required_checks_passed'
    confirmed=any(f['category'] in {'identifier_mismatch','proven_defect','input_error'} for f in failures)
    evidence_decision='APPROVED' if diagnostic_state=='PASS' else 'REJECTED' if confirmed else 'REVIEW'
    return dict(final_decision='APPROVED' if diagnostic_state=='PASS' else 'REJECTED',diagnostic_state=diagnostic_state,
                evidence_decision=evidence_decision,
                rejection_status=None if diagnostic_state=='PASS' else 'REJECTED_CONFIRMED' if confirmed else 'REJECTED_UNVERIFIED',
                confirmed_decision=diagnostic_state=='PASS' or confirmed,advisories=advisories,
                review_required=bool(unknown),rejection_basis=reason,findings=findings,comparisons=comparisons,
                decisive_coverage=evidence_decision!='REVIEW',photos=photos,algorithm_version=VERSION,
                policy_version='fail-closed-v2',notice='Binary rejection for insufficient evidence is not a proven photo defect. Preliminary engineering detectors, no independent Samsung accuracy claim.')
