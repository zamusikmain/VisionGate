/** Isolated future live guidance scheduler. Final ACCEPT still uses a captured file.
 * The consumer supplies lightweight detection, never a submission decision.
 * Runs at most one check at a time; stop aborts the current check.
 */
export function startPreviewChecks(check:(signal:AbortSignal)=>Promise<void>,intervalMs=1500){
 let stopped=false;let timer:ReturnType<typeof setTimeout>|undefined;let current:AbortController|undefined;
 const tick=async()=>{if(stopped)return;current=new AbortController();try{await check(current.signal)}catch{/* Preview errors do not replace final verification. */}finally{if(!stopped)timer=setTimeout(tick,Math.max(1000,intervalMs))}};
 void tick();return()=>{stopped=true;if(timer)clearTimeout(timer);current?.abort()};
}
