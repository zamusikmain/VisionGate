"""Portable local XLSX report. Optional dependency: requirements-samsung-export.txt.

The bundled native renderer crashes on process shutdown on this host; this exporter
uses openpyxl without native rendering and verifies the saved string identifiers.
"""
import argparse
import json
from pathlib import Path


def export_report(report,output):
    from openpyxl import Workbook,load_workbook
    from openpyxl.styles import Alignment,Font,PatternFill
    from openpyxl.worksheet.table import Table,TableStyleInfo
    from openpyxl.utils import get_column_letter
    wb=Workbook();wb.remove(wb.active)
    rows=report['evaluation']['rows']
    cases=[[r['case_id'],r['expected'],r['actual'],r['diagnostic'],r['review'],r['basis'],', '.join(r['issues'])] for r in rows]
    photos=[];fields=[]
    for c in report['cases']:
        for p in c['photos']:
            photos.append([c['case_id'],p['role'],p['sha256'],p['width'],p['height'],
                'UNKNOWN' if p['label_index'] is None else f'ROI {p["label_index"]+1}',
                ', '.join(p['extraction']['confirmed_imeis']),', '.join(p['extraction']['confirmed_models']),
                ', '.join(f'{k}: {v["state"]}' for k,v in p['checks'].items() if v['state']!='PASS')])
            for f in p['fields']:
                fields.append([c['case_id'],p['role'],f['key'],f['value'],f['format_valid'],f['confirmed'],
                    f['confirmation'],', '.join(sorted({e['source'] for e in f['evidence']})),
                    ', '.join(e['variant'] for e in f['evidence'])])
    def sheet(name,title,headers,data,widths):
        s=wb.create_sheet(name);s.sheet_view.showGridLines=False
        s['A2']=title;s['A2'].font=Font(name='Arial',size=14,bold=True)
        for i,heading in enumerate(headers,1):
            cell=s.cell(8,i,heading);cell.fill=PatternFill('solid',fgColor='1E3A5F')
            cell.font=Font(name='Arial',size=10,bold=True,color='FFFFFF');cell.alignment=Alignment(horizontal='center',vertical='center',wrap_text=True)
        for row_index,row in enumerate(data,9):
            for column,value in enumerate(row,1):
                cell=s.cell(row_index,column,value)
                if isinstance(value,str):
                    cell.data_type='s';cell.number_format='@'  # literal, including = + - @ and leading zeros
                cell.font=Font(name='Arial',size=10)
                cell.alignment=Alignment(vertical='center',wrap_text=column==len(headers))
            s.row_dimensions[row_index].height=84 if name!='Fields' else 66
        for i,width in enumerate(widths,1):s.column_dimensions[get_column_letter(i)].width=width
        s.row_dimensions[8].height=30;s.freeze_panes='B9'
        if data:
            table=Table(displayName=name+'Data',ref=f'A8:{get_column_letter(len(headers))}{8+len(data)}')
            table.tableStyleInfo=TableStyleInfo(name='TableStyleMedium2',showRowStripes=True)
            s.add_table(table)
        return s
    s=sheet('Cases','Samsung Photo Validation — known development examples',
            ['Case ID','Expected','Actual','Diagnostic','Review','Basis','Findings'],cases,[22,16,16,16,12,30,90])
    s['A4']='Known examples, not an independent evaluation. Rejection for UNKNOWN is not a proven defect.'
    s['A5']='APPROVED';s['B5']=sum(r['actual']=='APPROVED' for r in rows)
    s['C5']='REJECTED';s['D5']=sum(r['actual']=='REJECTED' for r in rows)
    s['A6']='False APPROVED';s['B6']=report['evaluation']['false_approved']
    s['C6']='False REJECTED';s['D6']=report['evaluation']['false_rejected']
    sheet('Photos','Local photo diagnostics',
          ['Case ID','Role','SHA-256','Width','Height','Label support','Confirmed IMEI','Recognized model','Non-PASS checks'],photos,[22,12,70,12,12,20,34,25,90])
    sheet('Fields','Recognition evidence — consensus is not independent confirmation',
          ['Case ID','Role','Field','Literal value','Format valid','Recognized','Confirmation','Source','Variants'],fields,[22,12,20,30,16,16,34,28,90])
    target=Path(output);target.parent.mkdir(parents=True,exist_ok=True);wb.save(target)
    loaded=load_workbook(target,data_only=False)
    for name,data in [('Cases',cases),('Photos',photos),('Fields',fields)]:
        for ri,row in enumerate(data,9):
            for ci,value in enumerate(row,1):
                actual=loaded[name].cell(ri,ci)
                assert actual.value==(None if value=='' else value),(name,ri,ci)
                if isinstance(value,str) and value!='':assert actual.data_type=='s',(name,ri,ci)
        assert loaded[name].freeze_panes=='B9'
    loaded.close();return target


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('input',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
    if a.input.resolve()==a.output.resolve():p.error('Output must not overwrite input')
    report=json.loads(a.input.read_text(encoding='utf-8'))
    export_report(report,a.output);print('XLSX exported and literal fields verified')


if __name__=='__main__':main()
