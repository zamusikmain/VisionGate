import {useEffect,useState,RefObject} from 'react';

export function guideBounds(viewWidth:number,viewHeight:number,videoWidth:number,videoHeight:number){
 if(![viewWidth,viewHeight,videoWidth,videoHeight].every(v=>Number.isFinite(v)&&v>0))return null;
 const scale=Math.min(viewWidth/videoWidth,viewHeight/videoHeight);
 const width=videoWidth*scale,height=videoHeight*scale;
 const guideWidth=width*.84,guideHeight=Math.min(height*.70,guideWidth*.65);
 return {left:(viewWidth-guideWidth)/2,top:(viewHeight-guideHeight)/2,width:guideWidth,height:guideHeight};
}

/** Decorative only. Matches object-fit:contain; never reads/draws camera pixels. */
export function CameraGuide({video}:{video:RefObject<HTMLVideoElement|null>}){
 const [bounds,setBounds]=useState<ReturnType<typeof guideBounds>>(null);
 useEffect(()=>{
  const element=video.current,viewer=element?.parentElement;if(!element||!viewer)return;
  const update=()=>{const size=viewer.getBoundingClientRect();setBounds(guideBounds(size.width,size.height,element.videoWidth,element.videoHeight))};
  const observer=typeof ResizeObserver!=='undefined'?new ResizeObserver(update):null;
  observer?.observe(viewer);
  for(const event of ['loadedmetadata','canplay','resize'])element.addEventListener(event,update);
  window.addEventListener('resize',update);update();
  return()=>{observer?.disconnect();for(const event of ['loadedmetadata','canplay','resize'])element.removeEventListener(event,update);window.removeEventListener('resize',update)};
 },[video]);
 return bounds?<div className="guide label-guide" style={bounds} aria-hidden="true" data-testid="camera-guide"><i/><i/><i/><i/></div>:null;
}
