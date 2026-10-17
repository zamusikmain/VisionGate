import React,{useEffect,useRef,useState} from 'react';
import {CameraGuide} from './camera-guide';
import {CameraAssist} from './camera-assist';
import {messages,Lang,Key} from './i18n';

export function PhotoCapture({role,lang,disabled,onPhoto}:{role:'device'|'scan';lang:Lang;disabled:boolean;onPhoto:(file:File)=>void}){
 const [stream,setStream]=useState<MediaStream|null>(null),[ready,setReady]=useState(false),[error,setError]=useState(''),[devices,setDevices]=useState<MediaDeviceInfo[]>([]);
 const video=useRef<HTMLVideoElement>(null),live=useRef<MediaStream|null>(null),generation=useRef(0),facing=useRef('environment');
 const t=(k:Key)=>messages[lang][k];
 function stop(){generation.current++;live.current?.getTracks().forEach(t=>t.stop());live.current=null;setStream(null);setReady(false)}
 useEffect(()=>()=>{generation.current++;live.current?.getTracks().forEach(t=>t.stop())},[]);
 useEffect(()=>{if(video.current&&stream)video.current.srcObject=stream},[stream]);
 useEffect(()=>{if(disabled)stop()},[disabled]);
 async function open(deviceId?:string){
  stop();setError('');const token=++generation.current;
  try{
   const acquired=await navigator.mediaDevices.getUserMedia({audio:false,video:{width:{ideal:1920},height:{ideal:1080},...(deviceId?{deviceId:{exact:deviceId}}:{facingMode:{ideal:facing.current}})}});
   if(token!==generation.current){acquired.getTracks().forEach(t=>t.stop());return}
   live.current=acquired;setStream(acquired);
   try{const list=await navigator.mediaDevices.enumerateDevices();if(token===generation.current)setDevices(list.filter(d=>d.kind==='videoinput'))}catch{/* Device switching can still use facingMode. */}
  }catch{if(token===generation.current)setError(t('cameraError'))}
 }
 function capture(){
  const source=video.current;if(!source||!ready||disabled||!source.videoWidth||!source.videoHeight)return;
  const token=generation.current;
  try{
   const canvas=document.createElement('canvas');canvas.width=source.videoWidth;canvas.height=source.videoHeight;
   const context=canvas.getContext('2d');if(!context)throw Error();context.drawImage(source,0,0);
   canvas.toBlob(blob=>{if(token!==generation.current)return;if(!blob){setError(t('captureError'));return}onPhoto(new File([blob],role+'-capture.jpg',{type:'image/jpeg'}));stop()},'image/jpeg',.95);
  }catch{setError(t('captureError'))}
 }
 return <div className="capture-panel">
  <button type="button" disabled={disabled} onClick={()=>open()}>{lang==='ru'?'Снять':'Capture'} {role}</button>
  {stream&&<><div className="viewer camera-view"><video ref={video} autoPlay playsInline muted onCanPlay={()=>setReady(true)}/><CameraGuide video={video}/></div>
   <CameraAssist video={video} stream={stream} t={t}/>
   <div className="actions"><button type="button" onClick={capture} disabled={!ready||disabled}>{t('capture')} {role}</button>
   {devices.length>1?<label>{lang==='ru'?'Камера':'Camera'} {role}<select aria-label={`${lang==='ru'?'Камера':'Camera'} ${role}`} onChange={e=>open(e.target.value)}>{devices.map((d,i)=><option value={d.deviceId} key={d.deviceId}>{d.label||`Camera ${i+1}`}</option>)}</select></label>:<button type="button" onClick={()=>{facing.current=facing.current==='environment'?'user':'environment';void open()}}>{lang==='ru'?'Сменить камеру':'Switch camera'}</button>}
   <button type="button" onClick={stop}>{t('close')}</button></div></>}
  {error&&<p role="alert">{error}</p>}
 </div>
}
