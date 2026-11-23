/* Startup: navigation between views (#/, #/backlog, #/week, #/artifacts, #/notebooks, #/profiles),
   periodic refresh, badges and keyboard shortcuts. Loaded last. */

const VIEWS={sessions:'#/',backlog:'#/backlog',week:'#/week',art:'#/artifacts',nb:'#/notebooks',pf:'#/profiles'};
let VIEW='sessions';

function go(v){if(location.hash!==VIEWS[v])location.hash=VIEWS[v]; else applyRoute()}
function applyRoute(){
  const h=decodeURIComponent(location.hash.slice(1));
  VIEW=h.startsWith('/backlog')||h.startsWith('bl-')?'backlog':h.startsWith('/week')?'week'
    :h.startsWith('/artifacts')?'art':h.startsWith('/notebooks')?'nb':h.startsWith('/profiles')?'pf':'sessions';
  for(const v in VIEWS)$('#v-'+v).hidden=v!==VIEW;
  document.querySelectorAll('.tab').forEach(t=>t.setAttribute('aria-current',t.dataset.view===VIEW?'page':'false'));
  if(VIEW==='backlog')renderBoard(true);
  if(VIEW==='week')renderWeek(true);
  if(VIEW==='art'){   // #/artifacts/<id>[/v3] opens one; #/artifacts, the gallery
    const [,, id, v]=h.split('/');
    renderArt(true); if(id)openArt(id,v); else closeArt();
  }
  if(VIEW==='nb'){    // #/notebooks/<id>[/<note path>]
    const [,, id, ...relpath]=h.split('/');
    renderNb(true); if(id)openNb(id,relpath.join('/')); else closeNb();
  }
  if(VIEW==='pf'){    // #/profiles/<id>
    const [,, id]=h.split('/');
    renderPf(true); if(id)openPf(id); else closePf();
  }
  // direct links: /#bl-<id> opens a task, /#<id> a session
  if(h.startsWith('bl-')){history.replaceState(null,'',VIEWS.backlog);openSheet(h.slice(3))}
  else if(VIEW==='sessions'&&h&&!h.startsWith('/')){history.replaceState(null,'',VIEWS.sessions);select(h)}
}

async function refresh(){
  try{
    [AGENTS,BACKLOG]=await Promise.all([api('/api/agents'),api('/api/backlog?all=1')]);
    LAST_OK=Date.now(); setConn('on','connected');
    if(!META.loaded)await loadMeta();  // e.g. if it started offline or unpaired
    const w=AGENTS.filter(a=>a.group==='waiting').length;
    const pend=BACKLOG.filter(i=>i.status==='pending'||i.status==='failed').length;
    document.title=w?`(${w}) Gatito`:'Gatito';
    $('#b-sessions').textContent=w||''; $('#b-backlog').textContent=pend||'';
    if(CUR){const a=AGENTS.find(x=>x.key===CUR.key);
      if(a){const changed=a.ui!==CUR.ui||a.group!==CUR.group||a.updatedAt!==CUR.updatedAt
          ||a.live!==CUR.live||a.detail!==CUR.detail;
        CUR=a; if(changed){renderDetail(false);loadConvo(false);loadWhiteboard(false);
          // Claude changes state a little before writing the last message to the .jsonl:
          // look again shortly after, or at the end you'd miss its reply
          const k=a.key; [2000,6000].forEach(ms=>setTimeout(()=>CUR&&CUR.key===k&&loadConvo(false),ms))}}}
    renderList(); renderBoard(); renderWeek(); renderArt(); renderNb(); if(!CUR)renderHome();
  }catch(e){if(e.message!=='401')setConn('off','offline')}
}
// project selector of the composer: projects and, apart, the notebooks (nb:<id>)
function fillProjSel(){
  const sel=$('#q-proj'), cur=sel.value;
  sel.innerHTML='<option value="">Auto</option>'+freeOpt()+
    META.projects.map(p=>`<option value="${esc(p.id)}">${esc(p.id)}</option>`).join('')+
    ((META.notebooks||[]).length?`<optgroup label="Notebooks">${META.notebooks.map(p=>
      `<option value="${esc(p.id)}">${esc(p.label)}</option>`).join('')}</optgroup>`:'');
  if([...sel.options].some(o=>o.value===cur))sel.value=cur;
}
// notebooks are created at any time (from this view or by an agent): /api/meta only arrives
// when the page loads, so the list that the Notebooks view reloads keeps them in sync
function syncNotebooks(listing){
  if(!META.loaded)return;
  const nbs=listing.map(c=>({id:'nb:'+c.id,path:c.relpath,label:c.title,git:false}));
  if(JSON.stringify(nbs)===JSON.stringify(META.notebooks||[]))return;
  META.notebooks=nbs; fillProjSel();
}
async function loadMeta(){
  try{
    META={...await api('/api/meta'),loaded:true};
    fillProjSel();
    // the composer remembers your last choice in this browser
    for(const [id,kind,def,blank] of [['q-model','models','','Auto'],['q-mode','modes',META.defaults.mode,null],['q-effort','efforts','','Normal']]){
      const el=$('#'+id), v=el.value||stored('gatito-'+id)||def;
      el.innerHTML=selOpts(kind,v,blank,'');
      if([...el.options].some(o=>o.value===v))el.value=v;
      el.onchange=()=>store('gatito-'+id,el.value||null);
    }
    // profile: when chosen, the other selectors take its values (and are remembered like them)
    const pf=$('#q-profile'), pv=pf.value||stored('gatito-q-profile')||'';
    pf.innerHTML=profileOpts(pv,'None',''); pf.value=profileFor(pv)?pv:'';
    const sels={model:$('#q-model'),mode:$('#q-mode'),effort:$('#q-effort'),wt:setWt};
    applyProfile(pf.value,sels,false);
    pf.onchange=()=>{store('gatito-q-profile',pf.value||null);applyProfile(pf.value,sels);
      for(const id of ['q-model','q-mode','q-effort'])store('gatito-'+id,$('#'+id).value||null);
      const p=profileFor(pf.value);
      if(p)toast(`${p.title}${p.read_only?' · read-only':''}: ${p.description}`)};
    $('#q-debug').hidden=!profileFor('debug');
    renderBoardFilter();
  }catch(e){}
}
/* ---------------- panels ---------------- */
// the composer lives in the center (desktop) or above the list (mobile)
function placeComposer(){
  const slot=matchMedia('(max-width:760px)').matches?$('#side-slot'):$('#home-slot');
  if($('#composer').parentElement!==slot)slot.appendChild($('#composer'));
}
function toggleList(on){
  const off=on==null?!$('#app').classList.contains('list-off'):!on;
  $('#app').classList.toggle('list-off',off); store('gatito-list-off',off?'1':null);
}
function toggleRail(on){
  const off=on==null?!$('#shell').classList.contains('rail-off'):!on;
  $('#shell').classList.toggle('rail-off',off); store('gatito-rail-off',off?'1':null);
}

async function init(){
  initBoard(); initWeek(); initArt(); initNb(); initPf(); initHist(); placeComposer();
  toggleList(stored('gatito-list-off')!=='1'); toggleRail(stored('gatito-rail-off')!=='1');
  addEventListener('resize',placeComposer);
  wireAttach('q',$('#composer'),$('#q-file'),$('#q-attach'));
  swRegister().then(markBell);
  await loadMeta();
  await refresh();
  applyRoute();
  addEventListener('hashchange',applyRoute);
  setInterval(refresh,5000);
  // with a running session open, the conversation updates by itself
  setInterval(()=>{if(CUR&&CUR.ui==='working'&&!document.hidden){loadConvo(false);loadWhiteboard(false)}},6000);
}

/* ---------------- composer ---------------- */
const q=$('#q');
q.oninput=()=>autosize(q);
q.onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();submit()}};
$('#composer').onsubmit=submit;
$('#q-proj-manage').onclick=manageProjects;
$('#q-repeat').innerHTML=repeatOpts('');
const wt=$('#q-wt'); wt.setAttribute('aria-pressed',stored('gatito-q-wt')==='1'?'true':'false');
function setWt(on){wt.setAttribute('aria-pressed',on);store('gatito-q-wt',on?'1':null)}
wt.onclick=()=>{const on=wt.getAttribute('aria-pressed')!=='true'; setWt(on);
  toast(on?'It will launch in an isolated worktree':'It will launch in the project folder')};
$('#q-when').onchange=()=>{
  const at=$('#q-when').value==='at'; $('#q-at-row').hidden=!at;
  if(at&&!$('#q-at').value)$('#q-at').value=localInput(nextHour());
  $('#q-send').textContent=$('#q-when').value==='now'?'Send':'Add';
};

$('#new-chat').onclick=()=>{closeDetail();q.focus()};
// "Debug": picks the profile and starts the message; the agent opens the whiteboard
$('#q-debug').onclick=()=>{
  const pf=$('#q-profile'); pf.value='debug'; pf.dispatchEvent(new Event('change'));
  if(!q.value.trim())q.value='Symptom: ';
  autosize(q); q.focus(); q.setSelectionRange(q.value.length,q.value.length);
};
$('#hide-list').onclick=()=>toggleList(false);
document.addEventListener('click',e=>{if(e.target.closest('[data-show-list]'))toggleList(true)});
$('#rail-hide').onclick=()=>toggleRail(false);
$('#rail-peek').onclick=()=>toggleRail(true);
$('#rail-bell').onclick=openNotify;

/* ---------------- shortcuts ---------------- */
document.addEventListener('keydown',e=>{
  const typing=/^(TEXTAREA|INPUT|SELECT)$/.test(document.activeElement.tagName);
  if(document.querySelector('dialog[open]'))return;  // dialogs handle their own keyboard
  if(e.key==='Escape'&&VIEW==='sessions'&&CUR)closeDetail();
  if(e.key==='Escape'&&VIEW==='art'&&ART.id)location.hash='#/artifacts';
  if(e.key==='Escape'&&VIEW==='pf'&&PF.id)location.hash='#/profiles';
  if(e.key==='Escape'&&VIEW==='nb'&&NB.id&&!NB.edit)location.hash=NB.relpath?nbHash(NB.id):'#/notebooks';
  if(typing||e.ctrlKey||e.metaKey||e.altKey)return;
  if(e.key==='/'){e.preventDefault();go('sessions');if(CUR&&!matchMedia('(max-width:760px)').matches)closeDetail();q.focus()}
  if(e.key==='['&&VIEW==='sessions')toggleList();
  if(e.key===']')toggleRail();
  if(e.key==='1')go('sessions');
  if(e.key==='2')go('backlog');
  if(e.key==='3')go('week');
  if(e.key==='4')go('art');
  if(e.key==='5')go('nb');
  if(e.key==='6')go('pf');
  if(e.key==='n'&&VIEW==='nb'){e.preventDefault();NB.c?newNote():newNotebook();return}
  if(e.key==='n'&&VIEW!=='sessions'){e.preventDefault();openSheet(null,{trigger:VIEW==='week'?'at':'manual'})}
});
init();
