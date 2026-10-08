import {useEffect,useState,RefObject} from 'react';
import {startPreviewChecks} from './live-preview';
import {Key} from './i18n';

type FocusCapabilities=MediaTrackCapabilities&{focusMode?:string[]};
type FocusSettings=MediaTrackSettings&{focusMode?:string};
export async function requestContinuousFocus(track?:MediaStreamTrack):Promise<'default'|'requested'|'confirmed'>{
 try{
  if(!track?.getCapabilities||!track.applyConstraints)return 'default';
  if(!(track.getCapabilities() as FocusCapabilities).focusMode?.includes('continuous'))return 'default';
  const current=track.getConstraints?.()??{};
  await track.applyConstraints({...current,advanced:[...(current.advanced??[]),{focusMode:'continuous'} as MediaTrackConstraintSet]});
  return (track.getSettings?.() as FocusSettings|undefined)?.focusMode==='continuous'?'confirmed':'requested';
 }catch{return 'default'}
}

/** Uncalibrated browser-only indicators. Never submission/quality decisions. */
export function previewHints(pixels:Uint8ClampedArray,width:number,height:number):Key[]{
 if(width<3||height<3||pixels.length!==width*height*4)return [];
 const gray=new Float32Array(width*height);let sum=0;
 for(let i=0;i<gray.length;i++){gray[i]=.299*pixels[i*4]+.587*pixels[i*4+1]+.114*pixels[i*4+2];sum+=gray[i]}
 const brightness=sum/gray.length;
 if(brightness<55)return ['previewDark'];
 if(brightness>235)return ['previewBright'];
 let edge=0;
 for(let y=1;y<height-1;y++)for(let x=1;x<width-1;x++){
  const i=y*width+x;edge+=Math.abs(4*gray[i]-gray[i-1]-gray[i+1]-gray[i-width]-gray[i+width]);
 }
 return edge/((width-2)*(height-2))<8?['previewBlur']:[];
}

export function CameraAssist({video,stream,t}:{video:RefObject<HTMLVideoElement|null>;stream:MediaStream|null;t:(key:Key)=>string}){
 const [enabled,setEnabled]=useState(false),[hint,setHint]=useState<Key|null>(null),[focus,setFocus]=useState<'default'|'requested'|'confirmed'>('default');
 useEffect(()=>{let disposed=false;setFocus('default');void requestContinuousFocus(stream?.getVideoTracks?.()[0]).then(status=>{if(!disposed)setFocus(status)});return()=>{disposed=true}},[stream]);
 useEffect(()=>{
  if(!enabled){setHint(null);return}
  const canvas=document.createElement('canvas');
  const stop=startPreviewChecks(async signal=>{
   const v=video.current;if(signal.aborted||!v||v.readyState<2||!v.videoWidth||!v.videoHeight||document.visibilityState==='hidden')return;
   const scale=160/Math.max(v.videoWidth,v.videoHeight);canvas.width=Math.max(3,Math.round(v.videoWidth*scale));canvas.height=Math.max(3,Math.round(v.videoHeight*scale));
   try{
    const context=canvas.getContext('2d');if(!context)return;
    context.drawImage(v,0,0,canvas.width,canvas.height);
    const hints=previewHints(context.getImageData(0,0,canvas.width,canvas.height).data,canvas.width,canvas.height);
    if(!signal.aborted)setHint(hints[0]??null);
   }catch{if(!signal.aborted)setHint(null)}
  });
  return()=>{stop();canvas.width=0;canvas.height=0};
 },[enabled,video]);
 return <div className="camera-assist">
  <label className="preview-toggle"><input type="checkbox" checked={enabled} onChange={e=>setEnabled(e.target.checked)}/>{t('previewToggle')}</label>
  {enabled&&<><small>{t('previewDisclaimer')}</small>{hint&&<p className="preview-hint" role="status">{t(hint)}</p>}</>}
  {focus!=='default'&&<small>{t(focus==='confirmed'?'focusConfirmed':'focusRequested')}</small>}
 </div>;
}
