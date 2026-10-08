import {afterEach,beforeEach,expect,test,vi} from 'vitest';
import {render,screen,fireEvent,cleanup} from '@testing-library/react';
import {App} from './main';
import {guideBounds} from './camera-guide';
import {messages} from './i18n';

beforeEach(()=>{localStorage.clear();URL.createObjectURL=vi.fn(()=>'blob:full-frame');URL.revokeObjectURL=vi.fn()});
afterEach(()=>{cleanup();vi.restoreAllMocks();vi.unstubAllGlobals()});

test.each([[320,568],[390,844],[430,932],[844,390],[1024,768]])('guide stays inside contained portrait/landscape video at screen %ix%i',(screenWidth,screenHeight)=>{
 const vw=screenWidth-56,vh=Math.max(220,Math.min(460,screenHeight*.52));
 for(const [width,height] of [[720,1280],[1920,1080],[1080,1080]]){
  const bounds=guideBounds(vw,vh,width,height)!;
  const scale=Math.min(vw/width,vh/height),left=(vw-width*scale)/2,top=(vh-height*scale)/2;
  expect(bounds.left).toBeGreaterThan(left);expect(bounds.top).toBeGreaterThan(top);
  expect(bounds.left+bounds.width).toBeLessThan(vw-left);
  expect(bounds.top+bounds.height).toBeLessThan(vh-top);
 }
});

test('unknown video dimensions never create a misplaced overlay',()=>{
 expect(guideBounds(360,420,0,0)).toBeNull();expect(guideBounds(0,420,720,1280)).toBeNull();
 expect(guideBounds(360,420,Infinity,1280)).toBeNull();
});

test('localized whole-label instructions and visual-only notice',()=>{
 render(<App/>);
 expect(screen.getByRole('heading',{name:messages.ru.guide})).toBeInTheDocument();
 expect(screen.getByText(messages.ru.cameraInstruction)).toBeInTheDocument();
 expect(screen.getByText(messages.ru.fullFrameHint)).toBeInTheDocument();
 fireEvent.click(screen.getByText('EN'));
 expect(screen.getByRole('heading',{name:messages.en.guide})).toBeInTheDocument();
 expect(screen.getByText(messages.en.cameraInstruction)).toBeInTheDocument();
 expect(screen.getByText(messages.en.fullFrameHint)).toBeInTheDocument();
});

test('resize/orientation updates decorative guide; capture always keeps full frame',async()=>{
 let resize:()=>void=()=>{};const disconnect=vi.fn();
 vi.stubGlobal('ResizeObserver',class{constructor(callback:()=>void){resize=callback}observe(){}disconnect=disconnect});
 let width=360,height=420;
 vi.spyOn(HTMLElement.prototype,'getBoundingClientRect').mockImplementation(()=>({width,height,left:0,top:0,right:width,bottom:height,x:0,y:0,toJSON(){}}));
 const stop=vi.fn();Object.defineProperty(navigator,'mediaDevices',{configurable:true,value:{getUserMedia:vi.fn().mockResolvedValue({getTracks:()=>[{stop}]})}});
 const drawImage=vi.fn();vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue({drawImage} as unknown as CanvasRenderingContext2D);
 vi.spyOn(HTMLCanvasElement.prototype,'toBlob').mockImplementation(function(this:HTMLCanvasElement,callback:BlobCallback){expect(this.width).toBe(720);expect(this.height).toBe(1280);callback(new Blob(['full-frame'],{type:'image/jpeg'}))});
 const view=render(<App/>);fireEvent.click(screen.getByText(messages.ru.camera));
 const capture=await screen.findByText(messages.ru.capture);expect(capture).toBeDisabled();
 const video=view.container.querySelector('video')!;Object.defineProperties(video,{videoWidth:{value:720,configurable:true},videoHeight:{value:1280,configurable:true}});
 fireEvent.canPlay(video);
 let guide=screen.getByTestId('camera-guide');expect(guide).toHaveAttribute('aria-hidden','true');
 expect(parseFloat(guide.style.width)).toBeCloseTo(198.45);
 width=700;height=260;fireEvent(window,new Event('resize'));
 guide=screen.getByTestId('camera-guide');expect(parseFloat(guide.style.width)).toBeCloseTo(122.85);
 Object.defineProperties(video,{videoWidth:{value:1280,configurable:true},videoHeight:{value:720,configurable:true}});
 fireEvent(video,new Event('resize'));expect(parseFloat(screen.getByTestId('camera-guide').style.width)).toBeCloseTo(388.26667);
 Object.defineProperties(video,{videoWidth:{value:720,configurable:true},videoHeight:{value:1280,configurable:true}});
 fireEvent.canPlay(video);resize();expect(capture).toBeEnabled();fireEvent.click(capture);
 expect(drawImage).toHaveBeenCalledExactlyOnceWith(video,0,0);
 expect(stop).toHaveBeenCalledOnce();expect(disconnect).toHaveBeenCalledOnce();
 expect(screen.queryByTestId('camera-guide')).not.toBeInTheDocument();
 expect(screen.queryByText(messages.ru.fullFrameHint)).not.toBeInTheDocument();
 expect(screen.getByText(messages.ru.analyze)).toBeEnabled();
});
