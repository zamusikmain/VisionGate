import {afterEach,beforeEach,expect,test,vi} from 'vitest';
import {render,screen,fireEvent,waitFor,cleanup} from '@testing-library/react';
import appSource from './main.tsx?raw';
import ts from 'typescript';
import {App} from './main';
import {messages} from './i18n';
import {analyzePhoto} from './api';

const accepted={request_id:'audit',timestamp:'2026-10-07',decision:'ACCEPT',quality_score:95,barcode:{decoded:true},metrics:{sharpness:150,brightness:150,contrast:60,barcode_area_ratio:.1},recommendations:[],processing_time_ms:25,config_version:'initial'};
beforeEach(()=>{localStorage.clear();vi.stubGlobal('fetch',vi.fn());URL.createObjectURL=vi.fn(()=> 'blob:audit');URL.revokeObjectURL=vi.fn()});
afterEach(()=>{cleanup();vi.restoreAllMocks();vi.unstubAllGlobals();vi.useRealTimers()});
function choose(file=new File(['bytes'],'audit.png',{type:'image/png'})){fireEvent.change(screen.getByLabelText('Загрузить фото'),{target:{files:[file]}})}
function media(getUserMedia:ReturnType<typeof vi.fn>){Object.defineProperty(navigator,'mediaDevices',{configurable:true,value:{getUserMedia}})}

test('invalid replacement clears previous preview and file; errors translate immediately',()=>{
 render(<App/>);choose();expect(screen.getByText('Проверить фотографию')).toBeInTheDocument();
 choose(new File(['pdf'],'other.pdf',{type:'application/pdf'}));
 expect(screen.queryByText('Проверить фотографию')).not.toBeInTheDocument();
 expect(screen.queryByRole('img')).not.toBeInTheDocument();
 expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:audit');
 fireEvent.click(screen.getByText('EN'));expect(screen.getByRole('alert')).toHaveTextContent(messages.en.invalid);
});

test('HEIC is explained in both languages, never sent as a supported upload',()=>{
 render(<App/>);choose(new File(['container'],'IMG_1234.HEIC',{type:'image/heic'}));
 expect(screen.getByRole('alert')).toHaveTextContent(messages.ru.unsupportedHEIF);
 expect(fetch).not.toHaveBeenCalled();fireEvent.click(screen.getByText('EN'));
 expect(screen.getByRole('alert')).toHaveTextContent(messages.en.unsupportedHEIF);
});

test('unknown MIME from a mobile file can reach content validation; oversized file cannot',()=>{
 render(<App/>);choose(new File(['bytes'],'photo.jpeg'));
 expect(screen.getByText('Проверить фотографию')).toBeInTheDocument();
 const oversized=new File(['bytes'],'photo.jpg',{type:'image/jpeg'});Object.defineProperty(oversized,'size',{value:12*1024*1024+1});choose(oversized);
 expect(screen.getByRole('alert')).toHaveTextContent(messages.ru.invalid);
 expect(screen.queryByText('Проверить фотографию')).not.toBeInTheDocument();
});

test('double submit is blocked; completed photo can be deliberately analyzed again',async()=>{
 let resolve:(value:Response)=>void=()=>{};
 vi.mocked(fetch).mockReturnValueOnce(new Promise<Response>(r=>{resolve=r})).mockResolvedValueOnce({ok:true,json:async()=>({...accepted,request_id:'second'})} as Response);
 render(<App/>);choose();fireEvent.click(screen.getByText('Проверить фотографию'));
 const pending=screen.getByRole('button',{name:'Проверяем штрихкод…'});expect(pending).toBeDisabled();fireEvent.click(pending);
 expect(fetch).toHaveBeenCalledTimes(1);resolve({ok:true,json:async()=>accepted} as Response);
 await screen.findByText('Фотография принята');fireEvent.click(screen.getByText('Проверить фотографию'));
 await screen.findByText('Фотография принята');expect(fetch).toHaveBeenCalledTimes(2);
});

test('busy server is technical retry guidance; backend HEIF is localized',async()=>{
 vi.mocked(fetch).mockResolvedValueOnce({ok:false,json:async()=>({error:'BUSY',request_id:'busy-id'})} as Response).mockResolvedValueOnce({ok:false,json:async()=>({error:'UNSUPPORTED_HEIF',request_id:'heif-id'})} as Response);
 render(<App/>);choose();fireEvent.click(screen.getByText('Проверить фотографию'));
 expect(await screen.findByRole('alert')).toHaveTextContent(messages.ru.busyError);
 expect(screen.queryByText('Переснимите фотографию')).not.toBeInTheDocument();
 fireEvent.click(screen.getByText('Повторить'));await waitFor(()=>expect(screen.getByRole('alert')).toHaveTextContent(messages.ru.unsupportedHEIF));
 fireEvent.click(screen.getByText('EN'));expect(screen.getByRole('alert')).toHaveTextContent(messages.en.unsupportedHEIF);
});

test.each([['CORRUPTED_IMAGE','corruptImage'],['INVALID_IMAGE_DIMENSIONS','invalidDimensions'],['UNSUPPORTED_ANIMATION','unsupportedAnimation']] as const)('API %s has specific localized validation guidance',async(code,key)=>{
 vi.mocked(fetch).mockResolvedValue({ok:false,json:async()=>({error:code,request_id:'validation-id'})} as Response);
 render(<App/>);choose();fireEvent.click(screen.getByText('Проверить фотографию'));
 expect(await screen.findByRole('alert')).toHaveTextContent(messages.ru[key]);fireEvent.click(screen.getByText('EN'));
 expect(screen.getByRole('alert')).toHaveTextContent(messages.en[key]);
 expect(screen.queryByRole('img')).not.toBeInTheDocument();expect(screen.queryByText('Analyze photo')).not.toBeInTheDocument();
 expect(screen.queryByText('Retry')).not.toBeInTheDocument();expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:audit');
});

test('rear camera, playsInline, frame readiness and full portrait capture',async()=>{
 const stop=vi.fn();const stream={getTracks:()=>[{stop}]} as unknown as MediaStream;
 const getUserMedia=vi.fn().mockResolvedValue(stream);media(getUserMedia);
 const drawImage=vi.fn();vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue({drawImage} as unknown as CanvasRenderingContext2D);
 vi.spyOn(HTMLCanvasElement.prototype,'toBlob').mockImplementation(function(this:HTMLCanvasElement,callback:BlobCallback){expect(this.width).toBe(720);expect(this.height).toBe(1280);callback(new Blob(['jpeg'],{type:'image/jpeg'}))});
 vi.mocked(fetch).mockResolvedValue({ok:true,json:async()=>accepted} as Response);
 const view=render(<App/>);fireEvent.click(screen.getByText('Включить камеру'));
 const capture=await screen.findByText('Сделать фото');expect(capture).toBeDisabled();
 const video=view.container.querySelector('video')!;expect(video.playsInline).toBe(true);expect(video.srcObject).toBe(stream);
 Object.defineProperties(video,{videoWidth:{value:720},videoHeight:{value:1280}});fireEvent.canPlay(video);
 expect(capture).toBeEnabled();fireEvent.click(capture);
 expect(drawImage).toHaveBeenCalledWith(video,0,0);expect(stop).toHaveBeenCalledOnce();
 fireEvent.click(screen.getByText('Проверить фотографию'));await screen.findByText('Фотография принята');
 const photo=(vi.mocked(fetch).mock.calls[0][1]?.body as FormData).get('image') as File;
 expect(photo.name).toBe('capture.jpg');expect(photo.type).toBe('image/jpeg');
 expect(getUserMedia).toHaveBeenCalledWith({video:{facingMode:{ideal:'environment'},width:{ideal:1920},height:{ideal:1080}},audio:false});
});

test('late camera capture cannot overwrite a newly uploaded image',async()=>{
 media(vi.fn().mockResolvedValue({getTracks:()=>[{stop:vi.fn()}]}));
 vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue({drawImage:vi.fn()} as unknown as CanvasRenderingContext2D);
 let finish:BlobCallback=()=>{};vi.spyOn(HTMLCanvasElement.prototype,'toBlob').mockImplementation(callback=>{finish=callback});
 vi.mocked(fetch).mockResolvedValue({ok:true,json:async()=>accepted} as Response);
 const view=render(<App/>);fireEvent.click(screen.getByText('Включить камеру'));await screen.findByText('Сделать фото');
 const video=view.container.querySelector('video')!;Object.defineProperties(video,{videoWidth:{value:1280},videoHeight:{value:720}});fireEvent.canPlay(video);
 fireEvent.click(screen.getByText('Сделать фото'));choose(new File(['fresh'],'fresh.png',{type:'image/png'}));
 finish(new Blob(['stale'],{type:'image/jpeg'}));fireEvent.click(screen.getByText('Проверить фотографию'));await screen.findByText('Фотография принята');
 const photo=(vi.mocked(fetch).mock.calls[0][1]?.body as FormData).get('image') as File;expect(photo.name).toBe('fresh.png');
});

test('analysis cancellation propagates on unmount and object URLs are revoked',async()=>{
 vi.mocked(fetch).mockImplementation((_url,options)=>new Promise((_resolve,reject)=>{options?.signal?.addEventListener('abort',()=>reject(Error('aborted')))}));
 const view=render(<App/>);choose();fireEvent.click(screen.getByText('Проверить фотографию'));
 const signal=vi.mocked(fetch).mock.calls[0][1]?.signal;expect(signal?.aborted).toBe(false);
 view.unmount();expect(signal?.aborted).toBe(true);expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:audit');
});

test('network timeout releases frontend loading rather than hanging indefinitely',async()=>{
 vi.useFakeTimers();vi.mocked(fetch).mockImplementation((_url,options)=>new Promise((_resolve,reject)=>{options?.signal?.addEventListener('abort',()=>reject(Error('timeout')))}));
 const promise=analyzePhoto(new File(['a'],'a.png'),new AbortController().signal);
 const rejection=expect(promise).rejects.toThrow('timeout');await vi.advanceTimersByTimeAsync(60000);await rejection;
});

test('language still works with disabled browser storage',()=>{
 vi.spyOn(Storage.prototype,'getItem').mockImplementation(()=>{throw Error('denied')});vi.spyOn(Storage.prototype,'setItem').mockImplementation(()=>{throw Error('denied')});
 render(<App/>);expect(screen.getByText('Включить камеру')).toBeInTheDocument();fireEvent.click(screen.getByText('EN'));expect(screen.getByText('Open camera')).toBeInTheDocument();
});

test('translation key parity and no hardcoded prose in JSX/accessible attributes',()=>{
 expect(Object.keys(messages.ru).sort()).toEqual(Object.keys(messages.en).sort());
 const tree=ts.createSourceFile('main.tsx',appSource,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
 const literals:string[]=[];
 function visit(node:ts.Node){
  if(ts.isJsxText(node)){const value=node.text.trim();if(/[A-Za-zА-Яа-яЁё]/u.test(value)&&!/^· v[\d.]+$/.test(value))literals.push(value)}
  if(ts.isJsxAttribute(node)&&['aria-label','alt','title','placeholder'].includes(node.name.getText(tree))&&node.initializer&&ts.isStringLiteral(node.initializer))literals.push(node.initializer.text);
  ts.forEachChild(node,visit);
 }
 visit(tree);expect(literals).toEqual([]);
});
