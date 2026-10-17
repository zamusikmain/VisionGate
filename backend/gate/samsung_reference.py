"""Read Final_Status for post-prediction evaluation only; never inference inputs."""
from pathlib import PurePosixPath
import zipfile
import xml.etree.ElementTree as E

N={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}


def final_status_labels(path):
    labels={}
    with zipfile.ZipFile(path) as z:
        if z.testzip() is not None:raise ValueError('INVALID_REFERENCE_XLSX')
        strings=[]
        if 'xl/sharedStrings.xml' in z.namelist():
            strings=[''.join(v.itertext()) for v in E.fromstring(z.read('xl/sharedStrings.xml')).findall('s:si',N)]
        for name in z.namelist():
            if not name.startswith('xl/worksheets/sheet') or not name.endswith('.xml'):continue
            rows=[]
            for row in E.fromstring(z.read(name)).findall('s:sheetData/s:row',N):
                cells={}
                for c in row.findall('s:c',N):
                    value=c.find('s:v',N);text=value.text if value is not None else ''
                    if c.get('t')=='s':text=strings[int(text)]
                    elif c.get('t')=='inlineStr':text=''.join(c.find('s:is',N).itertext())
                    cells[''.join(x for x in c.get('r','') if x.isalpha())]=text
                rows.append(cells)
            header=next((r for r in rows if 'Final_Status' in r.values()),None)
            if not header:continue
            status_col=next(k for k,v in header.items() if v=='Final_Status')
            identity_col=next((k for k,v in header.items() if v=='SN/IMEI'),None)
            if not identity_col:raise ValueError('MISSING_REFERENCE_KEY')
            for row in rows:
                key=row.get(identity_col,'');status=row.get(status_col,'').upper()
                if status not in {'APPROVED','REJECTED'}:continue
                if key in labels and labels[key]!=status:raise ValueError('CONFLICTING_REFERENCE_LABELS')
                labels[key]=status
    if not labels:raise ValueError('NO_FINAL_STATUS_LABELS')
    return labels
