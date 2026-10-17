"""Independent OOXML checks on portable export, including hostile literal strings."""
import json
import os
from pathlib import Path
import subprocess
import sys
from xml.etree import ElementTree as E
from zipfile import ZipFile
import pytest


@pytest.mark.parametrize('identifier',['000154203237518','=HYPERLINK("https://invalid.example","x")'])
def test_export_preserves_identifiers_as_literal_text(tmp_path,identifier):
    python=Path(os.environ.get('VISIONGATE_EXPORT_PYTHON',sys.executable))
    if not python.exists():pytest.skip('Optional export runtime unavailable')
    if subprocess.run([str(python),'-c','import openpyxl'],capture_output=True,timeout=10).returncode:
        pytest.skip('Optional openpyxl unavailable in selected export runtime')
    row=dict(case_id=identifier,expected='APPROVED',actual='REJECTED',diagnostic='UNKNOWN',review=True,basis='insufficient_evidence',issues=['MISSING_EVIDENCE'])
    report={'evaluation':{'rows':[row],'false_approved':0,'false_rejected':1},'cases':[{'case_id':identifier,'photos':[]}]}
    src=tmp_path/'input.json';out=tmp_path/'output.xlsx';src.write_text(json.dumps(report),encoding='utf-8')
    run=subprocess.run([str(python),'-m','tools.samsung_export',str(src),str(out)],capture_output=True,timeout=30)
    assert run.returncode==0,run.stderr
    ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with ZipFile(out) as z:
        assert z.testzip() is None
        root=E.fromstring(z.read('xl/worksheets/sheet1.xml'))
        c=root.find('.//s:c[@r="A9"]',ns)
        assert c.attrib['t']=='inlineStr'
        assert ''.join(c.find('s:is',ns).itertext())==identifier
        assert not root.findall('.//s:f',ns)
        assert not any(n.startswith('xl/externalLinks/') for n in z.namelist())
