import React from 'react';
import {render,screen,fireEvent,waitFor,cleanup} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {PhotoCapture} from './photo-capture';
afterEach(()=>{cleanup();vi.restoreAllMocks()});
it('stops camera tracks on close and keeps audio disabled',async()=>{
 const stop=vi.fn(),getUserMedia=vi.fn().mockResolvedValue({getTracks:()=>[{stop}],getVideoTracks:()=>[]});
 Object.defineProperty(navigator,'mediaDevices',{configurable:true,value:{getUserMedia,enumerateDevices:async()=>[]}});
 render(<PhotoCapture role="device" lang="en" disabled={false} onPhoto={vi.fn()}/>);
 fireEvent.click(screen.getByRole('button',{name:'Capture device'}));
 await waitFor(()=>expect(screen.getByRole('button',{name:'Close'})).toBeInTheDocument());
 expect(getUserMedia.mock.calls[0][0].audio).toBe(false);
 fireEvent.click(screen.getByRole('button',{name:'Close'}));expect(stop).toHaveBeenCalledOnce();
});
it('releases a late camera acquisition after the component unmounts',async()=>{
 const stop=vi.fn();let resolve!:(s:unknown)=>void;
 Object.defineProperty(navigator,'mediaDevices',{configurable:true,value:{getUserMedia:()=>new Promise(r=>{resolve=r})}});
 const view=render(<PhotoCapture role="scan" lang="en" disabled={false} onPhoto={vi.fn()}/>);
 fireEvent.click(screen.getByRole('button',{name:'Capture scan'}));view.unmount();resolve({getTracks:()=>[{stop}]});
 await waitFor(()=>expect(stop).toHaveBeenCalledOnce());
});
