import React from 'react';
import {Lang} from './i18n';
export function ModeNav({active,lang}:{active:'barcode'|'samsung';lang:Lang}){
 return <nav aria-label={lang==='ru'?'Режим проверки':'Validation mode'} className="mode-nav">
  <a href="/" aria-current={active==='barcode'?'page':undefined}>Barcode QA</a>
  <a href="/samsung" aria-current={active==='samsung'?'page':undefined}>Samsung Photo Validation</a>
 </nav>
}
