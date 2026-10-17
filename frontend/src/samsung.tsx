import React,{useEffect,useRef,useState} from 'react';
import {ModeNav} from './mode-nav';
import {PhotoCapture} from './photo-capture';
import {Lang} from './i18n';

function Preview({file,role}:{file:File|null;role:string}){
 const [url,setUrl]=useState('');
 useEffect(()=>{if(!file||typeof URL.createObjectURL!=='function'){setUrl('');return}const value=URL.createObjectURL(file);setUrl(value);return()=>URL.revokeObjectURL(value)},[file]);
 return url?<img className="photo-preview" src={url} alt={`${role} preview`}/>:null;
}

interface Check {state:string;reason:string}
interface Field {key:string;value:string;confirmed:boolean;confirmation:string;conflicted?:boolean}
interface Photo {role:string;sha256:string;checks:Record<string,Check>;fields:Field[]}
interface SamsungResult {final_decision:'APPROVED'|'REJECTED';diagnostic_state:string;review_required:boolean;rejection_basis:string;rejection_status?:'REJECTED_CONFIRMED'|'REJECTED_UNVERIFIED'|null;photos:Photo[];diagnostics:{role:string;image:string}[];findings:{code:string;state:string;reason?:string}[]}

export function SamsungPage(){
 const [lang,setLang]=useState<Lang>(()=>{try{return localStorage.getItem('lang')==='en'?'en':'ru'}catch{return 'ru'}}),[enabled,setEnabled]=useState(true);
 const tr=(ru:string,en:string)=>lang==='ru'?ru:en;
 useEffect(()=>{try{localStorage.setItem('lang',lang)}catch{}document.documentElement.lang=lang},[lang]);
 useEffect(()=>{const controller=new AbortController();fetch('/api/v1/capabilities',{signal:controller.signal}).then(r=>r.ok?r.json():null).then(d=>{if(!controller.signal.aborted&&d?.samsung_enabled===false)setEnabled(false)}).catch(()=>{});return()=>controller.abort()},[]);
 const [device,setDevice]=useState<File|null>(null),[scan,setScan]=useState<File|null>(null),[result,setResult]=useState<SamsungResult|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const pending=useRef<AbortController|null>(null);
 useEffect(()=>()=>pending.current?.abort(),[]);
 function choose(role:string,file:File|null){pending.current?.abort();pending.current=null;setBusy(false);setResult(null);setError('');if(role==='device')setDevice(file);else setScan(file)}
 async function validate(){
  if(!device||!scan||busy||!enabled)return;
  const controller=new AbortController();pending.current=controller;setBusy(true);setResult(null);setError('');
  const timer=setTimeout(()=>controller.abort(),240000);
  try{
   const body=new FormData();body.append('device',device);body.append('scan',scan);
   const response=await fetch('/api/v1/samsung/validate-case',{method:'POST',body,signal:controller.signal});
   if(!response.ok){const data=await response.json().catch(()=>({}));throw new Error(data.error||`HTTP ${response.status}`)}
   const data=await response.json();if(pending.current===controller)setResult(data);
  }catch(e){if(pending.current===controller)setError(e instanceof Error?e.message:'Ошибка проверки')}
  finally{clearTimeout(timer);if(pending.current===controller){setBusy(false);pending.current=null}}
 }
 return <div className="app"><header><strong>VisionGate · Samsung Photo Validation</strong><button className="language" onClick={()=>setLang(lang==='ru'?'en':'ru')}>{lang==='ru'?'EN':'RU'}</button></header><main><ModeNav active="samsung" lang={lang}/>
  <h1>{tr('Коробка и заводская наклейка','Box and identification label')}</h1><p>{tr('Device: покажите верх коробки и сторону с идентификацией под углом. Scan: крупно покажите читаемую идентификационную область и штрихкоды. Сохраняется весь кадр.','Device: show the box top and identification side at an angle. Scan: show readable identification and barcodes close up. The full frame is captured.')}</p>
  <p>{tr('Неподтверждённый обязательный критерий блокирует APPROVED. Недостаток доказательств отделён от найденного дефекта.','Unverified mandatory criteria prevent APPROVED. Insufficient evidence is distinguished from a detected defect.')}</p>
  {!enabled&&<p role="status">{tr('Samsung отключён на этом сервере. Используйте локальную сборку.','Samsung is disabled on this server. Use the local build.')}</p>}
  <section className="admin"><div className="photo-pair">{(['device','scan'] as const).map(role=><div key={role}><label>{role==='device'?tr('Device — коробка','Device — box'):tr('Scan — наклейка','Scan — identification')}<input type="file" accept="image/jpeg,image/png,image/webp" disabled={busy||!enabled} onChange={e=>choose(role,e.target.files?.[0]||null)}/></label>
  <Preview role={role} file={role==='device'?device:scan}/><PhotoCapture role={role} lang={lang} disabled={busy||!enabled} onPhoto={file=>choose(role,file)}/>
  {(role==='device'?device:scan)&&<button disabled={busy} onClick={()=>choose(role,null)}>{tr('Удалить / переснять','Remove / retake')} {role}</button>}</div>)}</div>
  <p>{tr('Общий размер пары: до 12 MiB при стандартной настройке.','Combined pair size: up to 12 MiB with default settings.')}</p>
  <button disabled={!device||!scan||busy||!enabled} onClick={validate}>{busy?tr('Проверка и OCR…','Checking and OCR…'):tr('Проверить пару','Validate pair')}</button>
  {busy&&<p role="status">{tr('Распознавание может занять несколько минут.','Recognition may take several minutes.')}</p>}
  {error&&<p role="alert">{error}</p>}</section>
  {result&&<section className="admin" aria-label={tr('Результат Samsung','Samsung result')}><h2>{result.final_decision}</h2>
   {result.rejection_status&&<p>{result.rejection_status==='REJECTED_CONFIRMED'?tr('Подтверждённый отказ','Confirmed rejection'):tr('Отказ без подтверждённого дефекта','Rejection without a proven defect')} ({result.rejection_status})</p>}
   <p>{tr('Диагностика','Diagnostic')}: {result.diagnostic_state}. {result.rejection_basis==='insufficient_evidence'?tr('Недостаточно доказательств; это не подтверждённый дефект.','Insufficient evidence; this is not a proven defect.'):result.rejection_basis==='identifier_mismatch'?tr('Обнаружено несовпадение идентификаторов.','Identifier mismatch detected.'):result.rejection_basis==='detected_defect'?tr('Обнаружен дефект; см. доказательства.','A defect was detected; inspect the evidence.'):tr('Обязательные проверки пройдены.','Mandatory checks passed.')}</p>
   {result.review_required&&<p>{tr('Нужна дополнительная проверка неподтверждённых критериев.','Unverified criteria require additional review.')}</p>}
   <p>{tr('Оранжевые рамки — кандидаты наклейки, красные — проблемные области. Рамка сама по себе не подтверждает обнаружение заводской наклейки.','Orange boxes mark label candidates; red boxes mark problem areas. A box alone does not prove factory-label detection.')}</p>
   <div style={{display:'flex',gap:16,flexWrap:'wrap'}}>{result.diagnostics.map(d=><figure key={d.role}><img src={d.image} alt={`Диагностика ${d.role}`} style={{maxWidth:360,maxHeight:550}}/><figcaption>{d.role}</figcaption></figure>)}</div>
   <ul>{result.findings.map((f,i)=><li key={i}>{f.state}: {f.code}{f.reason?` — ${f.reason}`:''}</li>)}</ul>
   {result.photos.map(p=><details key={p.sha256+p.role}><summary>{tr('Поля и проверки','Fields and checks')}: {p.role}</summary><table><thead><tr><th>{tr('Поле','Field')}</th><th>{tr('Значение','Value')}</th><th>{tr('Подтверждение','Evidence')}</th></tr></thead><tbody>{p.fields.map((f,i)=><tr key={i}><td>{f.key}</td><td>{f.value}</td><td>{f.conflicted?tr('Конфликт чтений; значение не выбрано','Conflicting readings; no value selected'):f.confirmed?f.confirmation:tr('Не подтверждено','Unverified')}</td></tr>)}</tbody></table><ul>{Object.entries(p.checks).map(([k,c])=><li key={k}>{c.state}: {k} — {c.reason}</li>)}</ul></details>)}
  </section>}
 </main></div>
}
