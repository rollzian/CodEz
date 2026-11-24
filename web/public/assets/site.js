'use strict';
const root=document.documentElement;
const themes=['system','dark','light'];
let theme='system';
try { const saved=localStorage.getItem('codez-theme'); if(themes.includes(saved)) theme=saved; } catch(e) { console.debug('Theme preference unavailable'); }
function applyTheme(){
  if(theme==='system') delete root.dataset.theme; else root.dataset.theme=theme;
  const b=document.querySelector('#theme'); if(b){b.title='Theme: '+theme;b.setAttribute('aria-label','Theme: '+theme+'. Change theme');}
}
applyTheme();
document.querySelector('#theme')?.addEventListener('click',()=>{
  theme=themes[(themes.indexOf(theme)+1)%themes.length];applyTheme();
  try{localStorage.setItem('codez-theme',theme);}catch(e){console.debug('Theme preference unavailable');}
});
document.querySelector('.mobile')?.addEventListener('click',e=>{
  const nav=document.querySelector('#navigation');
  const open=nav.classList.toggle('open');e.currentTarget.setAttribute('aria-expanded',String(open));
});
const samples={models:'Model library\nOpenAI\nAnthropic\nOpenRouter\nCustom compatible endpoint',skills:'Local skills\n.codez/skills/<name>/SKILL.md\nPreview → Approve → Enable',cloud:'Auxia Cloud\nWorkspaces\nTeams\nFriends\nPublic projects'};
document.querySelectorAll('[data-demo]').forEach(b=>b.addEventListener('click',()=>{
  const text=samples[b.dataset.demo]; if(!text)return;
  document.querySelectorAll('[data-demo]').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));
  const demo=document.querySelector('#demo');demo.textContent=text;
  if(!matchMedia('(prefers-reduced-motion: reduce)').matches) demo.animate([{opacity:.2,transform:'translateY(4px)'},{opacity:1,transform:'none'}],{duration:220,easing:'ease-out'});
}));
document.querySelectorAll('[data-channel]').forEach(b=>b.addEventListener('click',()=>{
  document.querySelectorAll('[data-channel]').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));
  document.querySelectorAll('[data-release]').forEach(x=>x.hidden=b.dataset.channel!=='all'&&x.dataset.release!==b.dataset.channel);
}));
document.querySelectorAll('[data-copy]').forEach(b=>b.addEventListener('click',async()=>{
  try{await navigator.clipboard.writeText(document.getElementById(b.dataset.copy).textContent);b.textContent='Copied';}
  catch(e){b.textContent='Copy unavailable';}
}));
const os=document.querySelector('#os');
if(os){
 const ua=navigator.userAgent;
 const platform=/Android/i.test(ua)?'Android':/iPhone|iPad/i.test(ua)?'iOS':/Windows/i.test(ua)?'Windows':/Macintosh/i.test(ua)?'macOS':/Linux/i.test(ua)?'Linux':'Unknown OS';
 os.textContent=platform==='Linux'?'Linux detected. Choose a compatible published package.':platform+' detected. Check available builds below.';
}
const poll=document.querySelector('#poll');
if(poll){
 let timer,busy=false,stopped=false,delay=Math.max(3,Number(poll.dataset.interval)||3);
 const status=document.querySelector('#poll-status');
 function schedule(){if(!stopped)timer=setTimeout(check,delay*1000);}
 async function check(){
  if(busy||stopped)return;busy=true;clearTimeout(timer);
  try{
   const response=await fetch(poll.action,{method:'POST',body:new FormData(poll),credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(16000)});
   const data=await response.json();
   if(data.state==='connected'){stopped=true;location.assign('/dashboard');return;}
   if(data.state==='expired'){stopped=true;status.textContent='Code expired. Start again.';return;}
   if(data.state==='pending'){delay=Math.max(1,Math.min(30,Number(data.interval)||3));status.textContent='Waiting for authorization';}
   else{delay=Math.min(60,delay*2);status.textContent='Connection unavailable. Retrying.';}
  }catch(e){delay=Math.min(60,delay*2);status.textContent='Connection unavailable. Retrying.';}
  finally{busy=false;schedule();}
 }
 poll.addEventListener('submit',e=>{e.preventDefault();check();});
 window.addEventListener('pagehide',()=>{stopped=true;clearTimeout(timer);},{once:true});
 schedule();
}
