"""Stateless browser batch intake/export. Names suggest pairs, never decisions."""
import base64
import io
import re
import stat
import zipfile
from pathlib import PurePosixPath
from typing import Literal
from pydantic import BaseModel, Field
from .image_input import read_image, InvalidImage
from .config import MAX_UPLOAD_BYTES

MAX_FILES=100
MAX_EXPANDED=64*1024*1024

def preview_archive(data):
    if len(data)>MAX_UPLOAD_BYTES:raise ValueError('FILE_TOO_LARGE')
    assets=[];groups={};total=0
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries=archive.infolist()
            if len(entries)>MAX_FILES*2:raise ValueError('TOO_MANY_ENTRIES')
            for entry in entries:
                name=entry.orig_filename;p=PurePosixPath(name)
                if '\x00' in name or '\\' in name or '..' in p.parts or p.is_absolute() or ':' in name or stat.S_ISLNK(entry.external_attr>>16):
                    raise ValueError('UNSAFE_ARCHIVE_PATH')
                if entry.is_dir():continue
                if entry.flag_bits&1:raise ValueError('ENCRYPTED_STOP')
                total+=entry.file_size
                if entry.file_size>MAX_UPLOAD_BYTES or total>MAX_EXPANDED:raise ValueError('ARCHIVES_TOO_LARGE')
                if len(assets)>=MAX_FILES:raise ValueError('TOO_MANY_ENTRIES')
                with archive.open(entry) as stream:raw=stream.read(MAX_UPLOAD_BYTES+1)
                if len(raw)>MAX_UPLOAD_BYTES:raise ValueError('FILE_TOO_LARGE')
                if raw.startswith(b'<## NASCA'):raise ValueError('NASCA_DRM_STOP')
                asset=dict(id=f'f{len(assets)+1}',name=name,size=len(raw),error=None,data=None)
                mime={'.jpg':'image/jpeg','.jpeg':'image/jpeg','.png':'image/png','.webp':'image/webp'}.get(p.suffix.lower())
                try:
                    if not mime:raise InvalidImage('INVALID_IMAGE_TYPE')
                    pixels=read_image(raw,mime)
                    asset.update(width=int(pixels.shape[1]),height=int(pixels.shape[0]),mime=mime,
                                 data=base64.b64encode(raw).decode('ascii'))
                except InvalidImage as exc:asset['error']=str(exc)
                assets.append(asset)
                match=re.fullmatch(r'(device|scan)(?:[_-](.+))?',p.stem,re.I)
                if match:
                    role,suffix=match.groups();group=str(p.parent)+'/'+(suffix or '')
                    item=groups.setdefault(group,dict(name=str(p.parent) if not suffix else suffix,device=[],scan=[]))
                    item[role.lower()].append(asset['id'])
            if not assets:raise ValueError('EMPTY_ARCHIVE')
    except (zipfile.BadZipFile,NotImplementedError,RuntimeError) as exc:
        raise ValueError('INVALID_ZIP') from exc
    pairs=[dict(name=g['name'],device=g['device'][0] if len(g['device'])==1 else '',
                scan=g['scan'][0] if len(g['scan'])==1 else '') for g in groups.values()]
    return dict(assets=assets,pairs=pairs,expanded_bytes=total,
                notice='Pair suggestions only. Review and correct before analysis; no labels enter classification.')

class Evidence(BaseModel):
    source:str=Field(max_length=120)
    variant:str=Field(max_length=120)
class ExportField(BaseModel):
    key:str=Field(max_length=40)
    value:str=Field(max_length=500)
    format_valid:bool
    confirmed:bool
    confirmation:str=Field(max_length=600)
    evidence:list[Evidence]=Field(max_length=100)
class Check(BaseModel):
    state:Literal['PASS','FAIL','UNKNOWN']
    reason:str=Field(default='',max_length=1200)
class Extraction(BaseModel):
    confirmed_imeis:list[str]=Field(default_factory=list,max_length=20)
    confirmed_models:list[str]=Field(default_factory=list,max_length=20)
class ExportPhoto(BaseModel):
    role:Literal['device','scan']
    sha256:str=Field(max_length=64)
    width:int=Field(ge=0,le=24000000)
    height:int=Field(ge=0,le=24000000)
    label_index:int|None=Field(default=None,ge=0,le=1000)
    extraction:Extraction
    checks:dict[str,Check]=Field(max_length=50)
    fields:list[ExportField]=Field(max_length=200)
class Finding(BaseModel):
    code:str=Field(max_length=120)
class ExportCase(BaseModel):
    case_id:str=Field(min_length=1,max_length=200)
    final_decision:Literal['APPROVED','REJECTED']
    diagnostic_state:Literal['PASS','FAIL','UNKNOWN']
    review_required:bool
    rejection_basis:str=Field(max_length=120)
    rejection_status:Literal['REJECTED_CONFIRMED','REJECTED_UNVERIFIED']|None=None
    findings:list[Finding]=Field(max_length=200)
    photos:list[ExportPhoto]=Field(max_length=2)
class ExportRequest(BaseModel):
    cases:list[ExportCase]=Field(min_length=1,max_length=100)

def export_cases(payload):
    from tools.samsung_export import export_report
    cases=[c.model_dump() for c in payload.cases]
    rows=[dict(case_id=c['case_id'],expected='',actual=c['final_decision'],
               diagnostic=c['diagnostic_state'],review=c['review_required'],basis=c['rejection_basis'],
               issues=[c['rejection_status'] or '']+[f['code'] for f in c['findings']]) for c in cases]
    report=dict(cases=cases,evaluation=dict(rows=rows,false_approved=None,false_rejected=None),
                evaluation_notice='User-selected cases. Expected outcomes are unknown; accuracy is not measured. UNKNOWN is not a proven defect.')
    output=io.BytesIO();export_report(report,output);return output.getvalue()
