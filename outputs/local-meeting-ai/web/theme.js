(() => {
 'use strict';
 const key='protocol-theme';
 function apply(value){
  const theme=value==='dark'?'dark':'light';
  document.documentElement.dataset.theme=theme;
  const button=document.getElementById('theme-toggle');
  if(button){button.textContent=theme==='dark'?'Светлая тема':'Тёмная тема';button.setAttribute('aria-pressed',String(theme==='dark'));}
 }
 let saved;try{saved=localStorage.getItem(key)}catch{}
 apply(saved);
 document.getElementById('theme-toggle')?.addEventListener('click',()=>{
  const theme=document.documentElement.dataset.theme==='dark'?'light':'dark';apply(theme);
  try{localStorage.setItem(key,theme)}catch{}
  for(const frame of document.querySelectorAll('iframe'))frame.contentWindow?.postMessage({type:'protocol:theme',theme},location.origin);
 });
 window.addEventListener('storage',event=>{if(event.key===key)apply(event.newValue)});
 window.addEventListener('message',event=>{
  if(event.origin===location.origin && event.source===parent && event.data?.type==='protocol:theme')apply(event.data.theme);
 });
})();
