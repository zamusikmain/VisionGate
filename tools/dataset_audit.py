"""Private dataset intake: integrity, hashes and duplicate labels. No scoring/tuning."""
import argparse
import hashlib
import json
from pathlib import Path
from backend.gate.config import MAX_UPLOAD_BYTES
from backend.gate.image_input import InvalidImage, read_image

IGNORED = {'.gitkeep', '.DS_Store', 'Thumbs.db'}

def dataset_files(root):
    root=Path(root).resolve()
    for label,folder in [('GOOD','good'),('BAD','bad')]:
        directory=root/folder
        if directory.exists() and not directory.resolve().is_relative_to(root):
            raise ValueError(f'Dataset class folder escapes root: {folder}')
        for file in sorted(directory.rglob('*')):
            if file.name in IGNORED or not file.is_file():continue
            if file.is_symlink() or not file.resolve().is_relative_to(root):
                raise ValueError(f'Dataset file escapes root or is a symlink: {file.relative_to(root)}')
            yield label,file

def bounded_read(file):
    with file.open('rb') as stream:
        data=stream.read(MAX_UPLOAD_BYTES+1)
    if len(data)>MAX_UPLOAD_BYTES:raise InvalidImage('FILE_TOO_LARGE')
    return data

def audit_dataset(root):
    root=Path(root).resolve();rows=[];errors=[];counts={'GOOD':0,'BAD':0};seen={}
    for label,file in dataset_files(root):
        name=file.relative_to(root).as_posix();row={'filename':name,'label':label}
        try:
            data=bounded_read(file);digest=hashlib.sha256(data).hexdigest()
            row.update(sha256=digest,bytes=len(data))
            pixels=read_image(data)
            row.update(valid=True,normalized_width=pixels.shape[1],normalized_height=pixels.shape[0])
            counts[label]+=1;seen.setdefault(digest,[]).append({'filename':name,'label':label})
            del pixels
        except InvalidImage as exc:
            row.update(valid=False,error=str(exc));errors.append({'filename':name,'error':str(exc)})
        rows.append(row)
    duplicates=[{'sha256':digest,'files':files,'conflicting_labels':len({f['label'] for f in files})>1} for digest,files in seen.items() if len(files)>1]
    for label,count in counts.items():
        if not count:errors.append({'error':'EMPTY_CLASS','label':label})
    for d in duplicates:
        if d['conflicting_labels']:errors.append({'error':'CONFLICTING_DUPLICATE_LABELS','sha256':d['sha256']})
    manifest_hash=hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest()
    return {'ready_for_baseline':not errors,'class_counts':counts,'manifest_sha256':manifest_hash,'files':rows,'duplicates':duplicates,'errors':errors,'notice':'Intake integrity only. No quality score, accuracy estimate or threshold optimization. Byte hashes detect exact duplicates, not visually similar captures.'}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('dataset',type=Path);p.add_argument('--output',type=Path,default=Path('reports/intake.json'));args=p.parse_args()
    if args.output.resolve().is_relative_to(args.dataset.resolve()):p.error('Report must be outside the dataset')
    try:report=audit_dataset(args.dataset)
    except (ValueError,OSError) as exc:p.error(str(exc))
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({'ready_for_baseline':report['ready_for_baseline'],'class_counts':report['class_counts'],'errors':report['errors']},indent=2))
    if not report['ready_for_baseline']:raise SystemExit(2)

if __name__=='__main__':main()
