import React from 'react';
import {render,screen,fireEvent,waitFor,cleanup} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {SamsungBatch,ExportButton} from './samsung-batch';
import type {SamsungResult} from './samsung';
afterEach(()=>{cleanup();vi.unstubAllGlobals();vi.restoreAllMocks()});
const result:SamsungResult={final_decision:'REJECTED',diagnostic_state:'UNKNOWN',review_required:true,rejection_basis:'insufficient_evidence',rejection_status:'REJECTED_UNVERIFIED',photos:[],diagnostics:[],findings:[{state:'UNKNOWN',code:'DEVICE_TOP_VISIBLE'}]};
const manifest={assets:[{id:'f1',name:'c/device.png',mime:'image/png',data:btoa('device'),error:null},{id:'f2',name:'c/scan.png',mime:'image/png',data:btoa('scan'),error:null}],pairs:[{name:'case',device:'f1',scan:'f1'}]};
function upload(){fireEvent.change(screen.getByLabelText('ZIP-архивы'),{target:{files:[new File(['zip'],'batch.zip',{type:'application/zip'})]}})}

it('requires pair correction, then sends separate files without labels and shows UNKNOWN honestly',async()=>{
 const fetcher=vi.fn().mockResolvedValueOnce({ok:true,json:async()=>manifest}).mockResolvedValueOnce({ok:true,json:async()=>result});vi.stubGlobal('fetch',fetcher);
 render(<SamsungBatch lang="ru" disabled={false} onBusy={()=>{}}/>);upload();
 await screen.findByLabelText('scan 1');expect(screen.getByRole('button',{name:'Проверить пакет'})).toBeDisabled();
 const options=screen.getByLabelText('scan 1').querySelectorAll('option');fireEvent.change(screen.getByLabelText('scan 1'),{target:{value:options[2].value}});
 fireEvent.click(screen.getByRole('button',{name:'Проверить пакет'}));
 await screen.findByText('case: REJECTED');expect(screen.getByText('Недостаток доказательств — дефект не подтверждён.')).toBeInTheDocument();
 const body=fetcher.mock.calls[1][1].body as FormData;
 const names:string[]=[];body.forEach((_value,key)=>names.push(key));
 expect(names).toEqual(['device','scan']);expect(body.get('device')).not.toBe(body.get('scan'));
 expect(screen.getByRole('button',{name:'Скачать XLSX (1)'})).toBeEnabled();
});

it('blocks damaged files and permits exclusion before analysis',async()=>{
 vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:true,json:async()=>({...manifest,assets:[manifest.assets[0],{...manifest.assets[1],error:'CORRUPTED_IMAGE',data:null}],pairs:[{name:'case',device:'f1',scan:'f2'}]})}));
 render(<SamsungBatch lang="ru" disabled={false} onBusy={()=>{}}/>);upload();
 await screen.findByText(/c\/scan.png: Изображение повреждено/);
 expect(screen.getByRole('button',{name:'Проверить пакет'})).toBeDisabled();
 fireEvent.click(screen.getByRole('button',{name:'Удалить пару 1'}));expect(screen.queryByLabelText('scan 1')).not.toBeInTheDocument();
 fireEvent.click(screen.getByRole('button',{name:'Добавить пару'}));expect(screen.getByLabelText('device 1')).toHaveValue('');
});

it('prevents repeated starts and stops remaining queue without inventing a rejection',async()=>{
 let requests=0;const good={...manifest,pairs:[{name:'case',device:'f1',scan:'f2'}]};
 vi.stubGlobal('fetch',vi.fn().mockImplementation((_url,init)=>{
  if(!requests++)return Promise.resolve({ok:true,json:async()=>good});
  return new Promise((_resolve,reject)=>init.signal.addEventListener('abort',()=>reject(new DOMException('Stopped','AbortError'))));
 }));
 render(<SamsungBatch lang="ru" disabled={false} onBusy={()=>{}}/>);upload();await screen.findByLabelText('scan 1');
 const run=screen.getByRole('button',{name:'Проверить пакет'});fireEvent.click(run);fireEvent.click(run);
 expect(run).toBeDisabled();expect(requests).toBe(2);
 fireEvent.click(screen.getByRole('button',{name:'Остановить очередь'}));await screen.findByText('case: Ошибка обработки');
 expect(screen.queryByText('case: REJECTED')).not.toBeInTheDocument();expect(screen.getByRole('button',{name:'Скачать XLSX (0)'})).toBeDisabled();
});

it('exports completed rows without image data or expected labels',async()=>{
 const fetcher=vi.fn().mockResolvedValue({ok:true,blob:async()=>new Blob(['xlsx'])});vi.stubGlobal('fetch',fetcher);
 vi.stubGlobal('URL',{createObjectURL:vi.fn(()=> 'blob:synthetic'),revokeObjectURL:vi.fn()});vi.spyOn(HTMLAnchorElement.prototype,'click').mockImplementation(()=>{});
 render(<ExportButton rows={[{name:'review',result}]} lang="en"/>);fireEvent.click(screen.getByRole('button',{name:'Download XLSX (1)'}));
 await waitFor(()=>expect(fetcher).toHaveBeenCalledTimes(1));const payload=JSON.parse(fetcher.mock.calls[0][1].body);
 expect(payload.cases[0].rejection_status).toBe('REJECTED_UNVERIFIED');expect(payload.cases[0]).not.toHaveProperty('expected');expect(payload.cases[0]).not.toHaveProperty('diagnostics');
});

it('keeps existing pairs if a later archive upload fails',async()=>{
 const fetcher=vi.fn().mockResolvedValueOnce({ok:true,json:async()=>manifest}).mockResolvedValueOnce({ok:false,json:async()=>({error:'INVALID_ZIP'})});vi.stubGlobal('fetch',fetcher);
 render(<SamsungBatch lang="ru" disabled={false} onBusy={()=>{}}/>);upload();await screen.findByLabelText('scan 1');upload();
 await screen.findByText('ZIP повреждён или не поддерживается.');expect(screen.getByLabelText('Название пары 1')).toHaveValue('case');
});
