import React,{useEffect,useRef,useState} from 'react';
import type {SamsungResult} from './samsung';
import type {Lang} from './i18n';

export function samsungError(code:string,lang:Lang){
 const errors:Record<string,[string,string]>={
  FILE_TOO_LARGE:['Файл или пара превышает 12 MiB.','File or pair exceeds 12 MiB.'],
  CORRUPTED_IMAGE:['Изображение повреждено.','The image is damaged.'],
  INVALID_IMAGE_TYPE:['Поддерживаются только JPEG, PNG и WebP.','Only JPEG, PNG and WebP are supported.'],
  INVALID_ZIP:['ZIP повреждён или не поддерживается.','The ZIP is damaged or unsupported.'],
  EMPTY_ARCHIVE:['В архиве нет файлов.','The archive contains no files.'],
  UNSAFE_ARCHIVE_PATH:['ZIP содержит небезопасные пути или ссылки.','The ZIP contains unsafe paths or links.'],
  ENCRYPTED_STOP:['Зашифрованный ZIP не поддерживается.','Encrypted ZIP is not supported.'],
  NASCA_DRM_STOP:['Обнаружен NASCA DRM; обработка остановлена.','NASCA DRM detected; processing stopped.'],
  ARCHIVES_TOO_LARGE:['После распаковки допускается до 64 MiB.','Expanded files may total up to 64 MiB.'],
  TOO_MANY_ENTRIES:['Допускается до 100 файлов.','Up to 100 files are supported.'],
  BUSY:['Сервис занят. Повторите позже.','The service is busy. Please retry later.'],
  EXPORT_DEPENDENCY_MISSING:['Не установлен компонент XLSX; см. инструкцию запуска.','XLSX dependency missing; see the launch guide.'],
  DUPLICATE_PHOTOS:['Device и scan должны быть разными фотографиями.','Device and scan must be different photographs.'],
  AbortError:['Операция остановлена или истекло время ожидания.','Operation stopped or timed out.']};
 const value=errors[code];return value?value[lang==='ru'?0:1]:`${lang==='ru'?'Ошибка обработки':'Processing error'}: ${code}`;
}

export function findingLabel(code:string,lang:Lang){
 const labels:Record<string,[string,string]>={
  DEVICE_TOP_VISIBLE:['Верх коробки и идентификационная сторона','Box top and identification side'],
  IDENTIFICATION_VISIBLE:['Наличие обязательной идентификационной информации','Required identification information'],
  IDENTIFIER_READABLE:['Читаемость IMEI или S/N','IMEI or S/N readability'],
  BARCODE_READABLE:['Читаемость штрихкодов','Barcode readability'],
  IDENTIFICATION_NOT_CROPPED:['Полнота обязательной области без критической обрезки','Required region coverage without critical cropping'],
  INFORMATION_IMAGE_QUALITY:['Качество обязательной информации: размытие, темнота, блики, перекрытия','Required information quality: blur, darkness, glare, occlusion'],
  SCREEN_RECAPTURE_ABSENT:['Проверка пересъёмки экрана','Screen recapture check'],
  IMEI_CONSISTENCY:['Согласованность идентификаторов device и scan','Device and scan identifier consistency']};
 if(labels[code])return labels[code][lang==='ru'?0:1];
 if(code.includes('MISMATCH'))return lang==='ru'?`Сопоставление идентификаторов (${code})`:`Identifier comparison (${code})`;
 if(code.startsWith('CONFLICTING_'))return lang==='ru'?`Конфликт распознанных значений (${code})`:`Conflicting readings (${code})`;
 return code;
}

type ExportRow={name:string;result:SamsungResult};
export function ExportButton({rows,lang,disabled=false}:{rows:ExportRow[];lang:Lang;disabled?:boolean}){
 const [busy,setBusy]=useState(false),[error,setError]=useState('');const lock=useRef(false);
 async function download(){
  if(lock.current||disabled||!rows.length)return;lock.current=true;setBusy(true);setError('');
  try{
   const cases=rows.map(({name,result:r})=>({case_id:name,final_decision:r.final_decision,diagnostic_state:r.diagnostic_state,
    review_required:r.review_required,rejection_basis:r.rejection_basis,rejection_status:r.rejection_status,
    findings:r.findings.map(f=>({code:f.code})),photos:r.photos.map(p=>({role:p.role,sha256:p.sha256,width:p.width,height:p.height,
     label_index:p.label_index,extraction:p.extraction,checks:p.checks,fields:p.fields.map(f=>({key:f.key,value:f.value,format_valid:f.format_valid,
      confirmed:f.confirmed,confirmation:f.confirmation,evidence:f.evidence.map(e=>({source:e.source,variant:e.variant}))}))}))}));
   const response=await fetch('/api/v1/samsung/export',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cases})});
   if(!response.ok)throw new Error((await response.json()).error||'EXPORT_ERROR');
   const url=URL.createObjectURL(await response.blob());const a=document.createElement('a');a.href=url;a.download='samsung-results.xlsx';document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }catch(e){setError(samsungError(e instanceof Error?e.message:'EXPORT_ERROR',lang))}
  finally{lock.current=false;setBusy(false)}
 }
 return <><button disabled={disabled||busy||!rows.length} onClick={download}>{lang==='ru'?'Скачать XLSX':'Download XLSX'} ({rows.length})</button>{error&&<p role="alert">{error}</p>}</>;
}

type Asset={id:string;name:string;file:File|null;error:string|null};
type Pair={id:string;name:string;device:string;scan:string};
type Outcome={id:string;name:string;result?:SamsungResult;error?:string};
function AssetPreview({asset}:{asset?:Asset}){
 const [url,setUrl]=useState('');
 useEffect(()=>{if(!asset?.file||typeof URL.createObjectURL!=='function'){setUrl('');return}const u=URL.createObjectURL(asset.file);setUrl(u);return()=>URL.revokeObjectURL(u)},[asset]);
 return url?<img className="photo-preview" alt={asset?.name} src={url}/>:null;
}
export function SamsungBatch({lang,disabled,onBusy}:{lang:Lang;disabled:boolean;onBusy:(busy:boolean)=>void}){
 const tr=(ru:string,en:string)=>lang==='ru'?ru:en;
 const [assets,setAssets]=useState<Asset[]>([]),[pairs,setPairs]=useState<Pair[]>([]),[outcomes,setOutcomes]=useState<Outcome[]>([]);
 const [busy,setBusy]=useState(false),[error,setError]=useState(''),[progress,setProgress]=useState('');
 const lock=useRef(false),controller=useRef<AbortController|null>(null),sequence=useRef(0),stopping=useRef(false);
 useEffect(()=>()=>{stopping.current=true;controller.current?.abort()},[]);
 function active(value:boolean){lock.current=value;setBusy(value);onBusy(value)}
 async function importZip(files:File[]){
  if(lock.current||disabled||!files.length)return;active(true);setError('');setProgress(tr('Чтение ZIP…','Reading ZIP…'));stopping.current=false;
  const next=[...assets],suggested=[...pairs];
  try{
   for(const zip of files){
    if(zip.size>12*1024*1024)throw Error('FILE_TOO_LARGE');
    const c=new AbortController();controller.current=c;const body=new FormData();body.append('image',zip);
    const response=await fetch('/api/v1/samsung/batch/preview',{method:'POST',body,signal:c.signal});
    const d=await response.json();if(!response.ok)throw Error(d.error||'INVALID_ZIP');
    const prefix=`upload${++sequence.current}-`;
    for(const a of d.assets){
     let file:File|null=null;
     if(!a.error){const raw=atob(a.data);const bytes=Uint8Array.from(raw,c=>c.charCodeAt(0));file=new File([bytes],a.name.split('/').pop(),{type:a.mime})}
     next.push({id:prefix+a.id,name:a.name,file,error:a.error});
    }
    for(const pair of d.pairs)suggested.push({id:`pair${++sequence.current}`,name:pair.name.slice(0,200),device:pair.device?prefix+pair.device:'',scan:pair.scan?prefix+pair.scan:''});
    if(next.length>100)throw Error('TOO_MANY_ENTRIES');
    if(next.reduce((n,a)=>n+(a.file?.size||0),0)>64*1024*1024)throw Error('ARCHIVES_TOO_LARGE');
   }
   setAssets(next);setPairs(suggested);setOutcomes([]);
  }catch(e){setError(samsungError(e instanceof Error?(e.name==='AbortError'?e.name:e.message):'INVALID_ZIP',lang))}
  finally{controller.current=null;active(false);setProgress('')}
 }
 const selected=pairs.flatMap(p=>[p.device,p.scan]);
 const valid=pairs.length>0&&pairs.every(p=>p.name.trim()&&p.device&&p.scan&&p.device!==p.scan&&[p.device,p.scan].every(id=>assets.some(a=>a.id===id&&a.file))&&[p.device,p.scan].reduce((n,id)=>n+(assets.find(a=>a.id===id)?.file?.size||0),0)<=12*1024*1024)&&new Set(selected).size===selected.length;
 function edit(id:string,change:Partial<Pair>){setPairs(ps=>ps.map(p=>p.id===id?{...p,...change}:p));setOutcomes([])}
 async function run(){
  if(lock.current||disabled||!valid)return;active(true);setOutcomes([]);setError('');stopping.current=false;
  try{
   for(let i=0;i<pairs.length&&!stopping.current;i++){
    const pair=pairs[i];setProgress(`${i+1}/${pairs.length}: ${pair.name}`);
    const c=new AbortController();controller.current=c;const timeout=setTimeout(()=>c.abort(),240000);
    try{
     const body=new FormData();for(const role of ['device','scan'] as const)body.append(role,assets.find(a=>a.id===pair[role])!.file!);
     const response=await fetch('/api/v1/samsung/validate-case',{method:'POST',body,signal:c.signal});const d=await response.json();
     if(!response.ok)throw Error(d.error||'ANALYSIS_ERROR');
     setOutcomes(os=>[...os,{id:pair.id,name:pair.name,result:d}]);
    }catch(e){setOutcomes(os=>[...os,{id:pair.id,name:pair.name,error:samsungError(e instanceof Error?(e.name==='AbortError'?e.name:e.message):'ANALYSIS_ERROR',lang)}])}
    finally{clearTimeout(timeout);controller.current=null}
   }
  }finally{active(false);setProgress('')}
 }
 return <section className="admin samsung-batch" aria-label={tr('Пакетная проверка','Batch validation')}><h2>{tr('Пакетная проверка','Batch validation')}</h2>
  <p>{tr('Загрузите ZIP (до 12 MiB каждый). До 100 файлов и 64 MiB после распаковки. Проверьте и исправьте пары перед запуском. Имена файлов используются только для предложений пар.','Upload ZIP files (up to 12 MiB each). Up to 100 files and 64 MiB expanded. Review and correct pairs before starting. Filenames only suggest pairings.')}</p>
  <label>{tr('ZIP-архивы','ZIP archives')}<input type="file" accept=".zip,application/zip" multiple disabled={busy||disabled} onChange={e=>{void importZip(Array.from(e.target.files||[]));e.target.value=''}}/></label>
  {error&&<p role="alert">{error}</p>}
  {assets.length>0&&<><p>{tr('Файлов','Files')}: {assets.length}. {tr('Не включено в пары','Not included in pairs')}: {assets.filter(a=>!selected.includes(a.id)).length}</p>
   {assets.filter(a=>a.error).map(a=><p role="alert" key={a.id}>{a.name}: {samsungError(a.error!,lang)}</p>)}
   {pairs.map((pair,i)=><fieldset key={pair.id} disabled={busy||disabled}><legend>{tr('Пара','Pair')} {i+1}</legend>
    <label>{tr('Название пары','Pair name')} {i+1}<input value={pair.name} maxLength={200} onChange={e=>edit(pair.id,{name:e.target.value})}/></label>
    <div className="photo-pair">{(['device','scan'] as const).map(role=><div key={role}><label>{role} {i+1}<select value={pair[role]} onChange={e=>edit(pair.id,{[role]:e.target.value})}><option value="">{tr('Выберите фото','Choose photo')}</option>{assets.map(a=><option key={a.id} value={a.id} disabled={!a.file}>{a.name}{a.error?' — '+samsungError(a.error,lang):''}</option>)}</select></label><AssetPreview asset={assets.find(a=>a.id===pair[role])}/></div>)}</div>
    <button onClick={()=>{setPairs(ps=>ps.filter(p=>p.id!==pair.id));setOutcomes([])}}>{tr('Удалить пару','Remove pair')} {i+1}</button>
   </fieldset>)}
   <button disabled={busy||disabled||pairs.length>=50} onClick={()=>{setPairs(ps=>[...ps,{id:`pair${++sequence.current}`,name:tr('Новая пара','New pair'),device:'',scan:''}]);setOutcomes([])}}>{tr('Добавить пару','Add pair')}</button>
   <button disabled={busy||disabled} onClick={()=>{setAssets([]);setPairs([]);setOutcomes([]);setError('')}}>{tr('Очистить пакет','Clear batch')}</button>
   {!valid&&<p role="status">{tr('Заполните пары: два разных доступных фото, без повторного использования; до 12 MiB на пару. Повреждённые и лишние файлы можно исключить, удалив соответствующую пару.','Complete pairs: two different available photos, no reuse, up to 12 MiB per pair. Exclude damaged or unwanted files by removing the corresponding pair.')}</p>}
   <button disabled={busy||disabled||!valid} onClick={run}>{tr('Проверить пакет','Validate batch')}</button>
  </>}
  {busy&&<><p role="status">{progress}</p><button onClick={()=>{stopping.current=true;controller.current?.abort()}}>{tr('Остановить очередь','Stop queue')}</button><p>{tr('Уже запущенная серверная проверка может завершиться после остановки.','An active server analysis may finish after stopping.')}</p></>}
  {outcomes.length>0&&<><h3>{tr('Результаты пакета','Batch results')}</h3><p>{tr('XLSX включает только завершённые проверки, без ошибочных запросов и непройденных пар.','XLSX includes completed analyses only, excluding failed requests and unprocessed pairs.')}</p>
   <ExportButton rows={outcomes.filter(o=>o.result).map(o=>({name:o.name,result:o.result!}))} lang={lang} disabled={busy}/>
   {outcomes.map(o=><div key={o.id}><h4>{o.name}: {o.result?.final_decision||tr('Ошибка обработки','Processing error')}</h4>{o.error&&<p role="alert">{o.error}</p>}{o.result&&<><p>{o.result.rejection_status==='REJECTED_UNVERIFIED'?tr('Недостаток доказательств — дефект не подтверждён.','Insufficient evidence — no proven defect.'):o.result.rejection_status==='REJECTED_CONFIRMED'?tr('Подтверждённое несоответствие.','Confirmed nonconformity.'):tr('Обязательные проверки пройдены.','Mandatory checks passed.')}</p><ul>{o.result.findings.map((f,i)=><li key={i}>{f.state}: {findingLabel(f.code,lang)}</li>)}</ul></>}</div>)}
  </>}
 </section>;
}
