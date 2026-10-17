"""Compare local development runs without feeding evaluation labels to inference."""
import argparse
from collections import Counter
import json
from pathlib import Path

from backend.gate.samsung_auto import REQUIRED


def compare(before_path, after_path, output):
    before=json.loads(Path(before_path).read_text(encoding='utf-8'))
    after=json.loads(Path(after_path).read_text(encoding='utf-8'))
    out=Path(output);out.mkdir(parents=True,exist_ok=True)
    lines=['# Samsung CV development comparison', '',
           'Local development examples, not an independent evaluation. Missing evidence is not a detected defect.', '',
           '| Metric | Before | After |','|---|---:|---:|']
    for label,key in [('False APPROVED','false_approved'),('False REJECTED','false_rejected'),
                      ('Cases with REVIEW','review_count'),('Legacy decisive coverage','decisive_coverage'),
                      ('All-check UNKNOWN fraction (denominators differ)','unknown_check_rate')]:
        lines.append(f"| {label} | {before['evaluation'][key]} | {after['evaluation'][key]} |")
    for label,key in [('Label-supported photos','label_supported'),('Photos with confirmed IMEI','imei_photos'),('Photos with recognized model','model_photos')]:
        lines.append(f"| {label} | {before['evaluation']['extraction'][key]}/28 | {after['evaluation']['extraction'][key]}/28 |")
    for report,label in [(before,'Before'),(after,'After')]:
        checks=[p['checks'].get(k,{'state':'UNKNOWN'}) for c in report['cases'] for p in c['photos'] for k in REQUIRED]
        lines.append(f"\n{label}, same current mandatory set: {sum(c['state']=='UNKNOWN' for c in checks)}/{len(checks)} UNKNOWN.")
        lines.append(f"Confusion matrix: `{json.dumps(report['evaluation']['confusion_matrix'])}`.")
        lines.append(f"Real scan swaps: `{json.dumps({k:v for k,v in report['permutations'].items() if k!='rows'})}`.")
    lines += ['',f"Confirmed-decision coverage after: {after['evaluation']['confirmed_decision_coverage']}; rejection statuses: {after['evaluation']['rejection_status_counts']}.",
              '', 'Removing speculative model/serial/dual-SIM obligations changes policy, not image-recognition accuracy.', '',
              '## All cases','', '| Case | Expected | Actual | Evidence status | Diagnostic |', '|---|---|---|---|---|']
    expected={r['case_id']:r['expected'] for r in after['evaluation']['rows']}
    for c in after['cases']:
        lines.append(f"| {c['case_id']} | {expected.get(c['case_id'])} | {c['final_decision']} | {c['rejection_status']} | {c['diagnostic_state']} |")
    audit=[]
    lines+=['','## Five Approved cases: exact UNKNOWN checks before and after','']
    for old,new in zip(before['cases'],after['cases']):
        assert old['case_id']==new['case_id']
        if expected[new['case_id']]!='APPROVED':continue
        lines+=['### '+new['case_id'],'']
        for report,phase in [(old,'Before'),(new,'After')]:
            for p in report['photos']:
                unknown={k:v['reason'] for k,v in p['checks'].items() if v['state']=='UNKNOWN'}
                audit.append(dict(case_id=new['case_id'],phase=phase,role=p['role'],unknown=unknown,
                                  mandatory_unknown=[k for k in unknown if k in REQUIRED]))
                lines.append(f"- {phase} {p['role']}: "+', '.join(unknown))
        lines.append('')
    (out/'comparison.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    (out/'approved-unknown-audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(after['evaluation'],ensure_ascii=False,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('before',type=Path);p.add_argument('after',type=Path);p.add_argument('--output-dir',type=Path,default=Path('reports/samsung-v03'))
    a=p.parse_args();compare(a.before,a.after,a.output_dir)
