import {afterEach,beforeEach,expect,test,vi} from 'vitest';
import {act,cleanup,fireEvent,render,screen} from '@testing-library/react';
import {App} from './main';
import {CameraAssist,previewHints,requestContinuousFocus} from './camera-assist';
import {messages} from './i18n';

beforeEach(()=>{localStorage.clear();vi.stubGlobal('fetch',vi.fn());URL.createObjectURL=vi.fn(()=>'blob:assist');URL.revokeObjectURL=vi.fn()});
afterEach(()=>{cleanup();vi.restoreAllMocks();vi.unstubAllGlobals();vi.useRealTimers()});
function flat(value:number,width=16,height=16){const bytes=new Uint8ClampedArray(width*height*4);for(let i=0;i<width*height;i++)bytes.set([value,value,value,255],i*4);return bytes}
const result={request_id:'assist',timestamp:'synthetic',decision:'RETAKE',quality_score:50,barcode:{decoded:false},metrics:{sharpness:10,brightness:150,contrast:60,barcode_area_ratio:.1},recommendations:['HOLD_STEADY'],processing_time_ms:20,config_version:'initial'};
function upload(){fireEvent.change(screen.getByLabelText(messages.ru.upload),{target:{files:[new File(['synthetic'],'a.png',{type:'image/png'})]}})}

test('preview indicators cover darkness, excess brightness and low edge detail',()=>{
 expect(previewHints(flat(20),16,16)).toEqual(['previewDark']);expect(previewHints(flat(250),16,16)).toEqual(['previewBright']);
 expect(previewHints(flat(150),16,16)).toEqual(['previewBlur']);expect(previewHints(new Uint8ClampedArray(),16,16)).toEqual([]);
 const patterned=flat(150);for(let y=0;y<16;y++)for(let x=0;x<16;x++)patterned.set([x%2?255:0,x%2?255:0,x%2?255:0,255],(y*16+x)*4);
 expect(previewHints(patterned,16,16)).toEqual([]);
});

test('focus preserves constraints, applies only advertised continuous mode, and verifies reported settings',async()=>{
 const applyConstraints=vi.fn().mockResolvedValue(undefined);
 const track={getCapabilities:()=>({focusMode:['continuous','manual']}),getConstraints:()=>({width:{ideal:1920}}),applyConstraints,getSettings:()=>({focusMode:'continuous'})} as unknown as MediaStreamTrack;
 expect(await requestContinuousFocus(track)).toBe('confirmed');expect(applyConstraints).toHaveBeenCalledWith({width:{ideal:1920},advanced:[{focusMode:'continuous'}]});
});

test('unsupported, rejected and unconfirmed focus requests never block the camera',async()=>{
 const applyConstraints=vi.fn().mockRejectedValue(Error('unsupported'));
 expect(await requestContinuousFocus()).toBe('default');
 expect(await requestContinuousFocus({getCapabilities:()=>({focusMode:['manual']}),applyConstraints} as unknown as MediaStreamTrack)).toBe('default');expect(applyConstraints).not.toHaveBeenCalled();
 const track={getCapabilities:()=>({focusMode:['continuous']}),applyConstraints} as unknown as MediaStreamTrack;
 expect(await requestContinuousFocus(track)).toBe('default');applyConstraints.mockResolvedValue(undefined);
 expect(await requestContinuousFocus(track)).toBe('requested');
});

test('hints are opt-in, local, translated and stop immediately on disable/unmount',async()=>{
 vi.useFakeTimers();const video=document.createElement('video');Object.defineProperties(video,{videoWidth:{value:720},videoHeight:{value:1280},readyState:{value:2}});
 const drawImage=vi.fn(),getImageData=vi.fn((_x:number,_y:number,w:number,h:number)=>({data:flat(20,w,h)}));
 vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue({drawImage,getImageData} as unknown as CanvasRenderingContext2D);
 const props={video:{current:video},stream:null};const view=render(<CameraAssist {...props} t={key=>messages.ru[key]}/>);
 expect(screen.getByRole('checkbox')).not.toBeChecked();expect(drawImage).not.toHaveBeenCalled();
 fireEvent.click(screen.getByRole('checkbox'));await act(async()=>{});
 expect(screen.getByRole('status')).toHaveTextContent(messages.ru.previewDark);expect(fetch).not.toHaveBeenCalled();
 expect(drawImage).toHaveBeenCalledWith(video,0,0,90,160);
 view.rerender(<CameraAssist {...props} t={key=>messages.en[key]}/>);expect(screen.getByRole('status')).toHaveTextContent(messages.en.previewDark);
 fireEvent.click(screen.getByRole('checkbox'));const count=drawImage.mock.calls.length;
 await act(async()=>{await vi.advanceTimersByTimeAsync(5000)});expect(drawImage).toHaveBeenCalledTimes(count);expect(screen.queryByRole('status')).not.toBeInTheDocument();
 view.unmount();await act(async()=>{await vi.advanceTimersByTimeAsync(5000)});expect(drawImage).toHaveBeenCalledTimes(count);
});

test('preview canvas failure leaves capture enabled and keeps full-frame capture',async()=>{
 Object.defineProperty(navigator,'mediaDevices',{configurable:true,value:{getUserMedia:vi.fn().mockResolvedValue({getTracks:()=>[{stop:vi.fn()}]})}});
 const drawImage=vi.fn();vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue({drawImage,getImageData:()=>{throw Error('no readback')}} as unknown as CanvasRenderingContext2D);
 vi.spyOn(HTMLCanvasElement.prototype,'toBlob').mockImplementation(function(this:HTMLCanvasElement,callback:BlobCallback){expect(this.width).toBe(720);expect(this.height).toBe(1280);callback(new Blob(['full-frame'],{type:'image/jpeg'}))});
 const view=render(<App/>);fireEvent.click(screen.getByText(messages.ru.camera));const capture=await screen.findByText(messages.ru.capture);
 const video=view.container.querySelector('video')!;Object.defineProperties(video,{videoWidth:{value:720},videoHeight:{value:1280},readyState:{value:2}});fireEvent.canPlay(video);fireEvent.click(screen.getByRole('checkbox'));
 expect(capture).toBeEnabled();fireEvent.click(capture);expect(drawImage).toHaveBeenCalledWith(video,0,0);expect(screen.getByText(messages.ru.analyze)).toBeEnabled();
});

test('darkness warning never prevents full-resolution capture or auto-submits',async()=>{
 Object.defineProperty(navigator,'mediaDevices',{configurable:true,value:{getUserMedia:vi.fn().mockResolvedValue({getTracks:()=>[{stop:vi.fn()}]})}});
 const drawImage=vi.fn();vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue({drawImage,getImageData:(_x:number,_y:number,w:number,h:number)=>({data:flat(20,w,h)})} as unknown as CanvasRenderingContext2D);
 vi.spyOn(HTMLCanvasElement.prototype,'toBlob').mockImplementation(function(this:HTMLCanvasElement,callback:BlobCallback){expect(this.width).toBe(1280);expect(this.height).toBe(720);callback(new Blob(['full'],{type:'image/jpeg'}))});
 const view=render(<App/>);fireEvent.click(screen.getByText(messages.ru.camera));const capture=await screen.findByText(messages.ru.capture);
 const video=view.container.querySelector('video')!;Object.defineProperties(video,{videoWidth:{value:1280},videoHeight:{value:720},readyState:{value:2}});fireEvent.canPlay(video);fireEvent.click(screen.getByRole('checkbox'));
 expect(screen.getByRole('status')).toHaveTextContent(messages.ru.previewDark);expect(capture).toBeEnabled();fireEvent.click(capture);
 expect(drawImage).toHaveBeenCalledWith(video,0,0);expect(fetch).not.toHaveBeenCalled();expect(screen.getByText(messages.ru.analyze)).toBeEnabled();
});

test('RETAKE reopens camera in one action; camera denial keeps upload fallback',async()=>{
 vi.mocked(fetch).mockResolvedValue({ok:true,json:async()=>result} as Response);
 const getUserMedia=vi.fn().mockRejectedValue(Error('denied'));Object.defineProperty(navigator,'mediaDevices',{configurable:true,value:{getUserMedia}});
 render(<App/>);upload();fireEvent.click(screen.getByText(messages.ru.analyze));await screen.findByText(messages.ru.retake);
 expect(screen.getByText(messages.ru.replacePhoto)).toBeInTheDocument();fireEvent.click(screen.getByText(messages.ru.retakeCamera));
 expect(await screen.findByRole('alert')).toHaveTextContent(messages.ru.cameraError);expect(getUserMedia).toHaveBeenCalledOnce();expect(screen.queryByRole('img')).not.toBeInTheDocument();
 upload();expect(screen.getByText(messages.ru.analyze)).toBeEnabled();
});

test('same-event duplicate submits are locked; technical retry and replacement are still allowed',async()=>{
 let resolve:(r:Response)=>void=()=>{};vi.mocked(fetch).mockReturnValueOnce(new Promise(r=>{resolve=r})).mockResolvedValue({ok:true,json:async()=>result} as Response);
 render(<App/>);upload();const button=screen.getByText(messages.ru.analyze);
 act(()=>{button.click();button.click()});expect(fetch).toHaveBeenCalledOnce();
 resolve({ok:false,json:async()=>({error:'BUSY'})} as Response);await screen.findByRole('alert');fireEvent.click(screen.getByText(messages.ru.retry));
 await screen.findByText(messages.ru.retake);expect(fetch).toHaveBeenCalledTimes(2);
 fireEvent.click(screen.getByText(messages.ru.replacePhoto));upload();fireEvent.click(screen.getByText(messages.ru.analyze));await screen.findByText(messages.ru.retake);expect(fetch).toHaveBeenCalledTimes(3);
});
