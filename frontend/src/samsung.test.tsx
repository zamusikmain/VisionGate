import React from 'react';
import {render,screen,fireEvent,waitFor,cleanup} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {SamsungPage} from './samsung';
afterEach(()=>{cleanup();localStorage.clear();vi.unstubAllGlobals()});
it('requires both photos before requesting validation',()=>{
 render(<SamsungPage/>);expect(screen.getByRole('button',{name:'Проверить пару'})).toBeDisabled();
 fireEvent.change(screen.getByLabelText('Device — коробка'),{target:{files:[new File(['x'],'device.jpg',{type:'image/jpeg'})]}});
 expect(screen.getByRole('button',{name:'Проверить пару'})).toBeDisabled();
});
it('switches language and disables Samsung when the server capability is off',async()=>{
 vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:true,json:async()=>({samsung_enabled:false})}));
 render(<SamsungPage/>);fireEvent.click(screen.getByRole('button',{name:'EN'}));
 await waitFor(()=>expect(screen.getByText('Samsung is disabled on this server. Use the local build.')).toBeInTheDocument());
 expect(screen.getByRole('button',{name:'Capture device'})).toBeDisabled();
 expect(screen.getByRole('link',{name:'Barcode QA'})).toHaveAttribute('href','/');
});
it('shows insufficient-evidence rejection separately from a proven defect',async()=>{
 vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:true,json:async()=>({final_decision:'REJECTED',diagnostic_state:'UNKNOWN',review_required:true,rejection_basis:'insufficient_evidence',photos:[],diagnostics:[],findings:[]})}));
 render(<SamsungPage/>);
 for(const label of ['Device — коробка','Scan — наклейка'])fireEvent.change(screen.getByLabelText(label),{target:{files:[new File(['x'],'photo.jpg',{type:'image/jpeg'})]}});
 fireEvent.click(screen.getByRole('button',{name:'Проверить пару'}));
 await waitFor(()=>expect(screen.getByRole('heading',{name:'REJECTED'})).toBeInTheDocument());
 expect(screen.getByText(/Недостаточно доказательств; это не подтверждённый дефект/)).toBeInTheDocument();
});
it.each(['REJECTED_CONFIRMED','REJECTED_UNVERIFIED'] as const)('shows explicit evidence status %s',async status=>{
 vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:true,json:async()=>({final_decision:'REJECTED',diagnostic_state:'UNKNOWN',review_required:true,rejection_basis:'insufficient_evidence',rejection_status:status,photos:[],diagnostics:[],findings:[]})}));
 render(<SamsungPage/>);
 for(const label of ['Device — коробка','Scan — наклейка'])fireEvent.change(screen.getByLabelText(label),{target:{files:[new File(['x'],'photo.jpg',{type:'image/jpeg'})]}});
 fireEvent.click(screen.getByRole('button',{name:'Проверить пару'}));
 await waitFor(()=>expect(screen.getByText(new RegExp(`\\(${status}\\)`))).toBeInTheDocument());
});
