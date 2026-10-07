export interface Analysis {request_id:string;timestamp:string;decision:'ACCEPT'|'RETAKE';quality_score:number;barcode:{decoded:boolean;detected:boolean;type:string|null;value:string|null;bounding_box:number[]|null};metrics:{sharpness:number;brightness:number;contrast:number;barcode_area_ratio:number;[key:string]:number|boolean};issues:string[];recommendations:string[];processing_time_ms:number;algorithm_version:string;config_version:string}
export class APIError extends Error {constructor(public code:string,public requestId:string){super(code)}}
export async function analyzePhoto(file:File, signal:AbortSignal):Promise<Analysis>{
 const body=new FormData();body.append('image',file);
 const cancellation=new AbortController();
 const abort=()=>cancellation.abort();
 if(signal.aborted)abort();else signal.addEventListener('abort',abort,{once:true});
 const timer=setTimeout(abort,60000);
 try {
  const response=await fetch('/api/v1/analyze',{method:'POST',body,signal:cancellation.signal});
  if(!response.ok){const error=await response.json().catch(()=>({}));throw new APIError(error.error||'SYSTEM_ERROR',error.request_id||response.headers?.get('X-Request-ID')||'');}
  return await response.json();
 } finally {clearTimeout(timer);signal.removeEventListener('abort',abort)}
}
// Future preview module can call this API at a bounded interval with cancellation.
// Preview results must never replace verification of the captured image.
