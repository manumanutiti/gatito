/* Whiteboard of the open session, in a column to the right of the chat (collapsible and
   remembered) or full screen on mobile with the header button.

   - A "Debug" session (profile debug) draws its live board: a JSON that the agent changes
     line by line with `bin/whiteboard` (GET /api/debug, asked every 2 s while it works and
     repainted only if it changed). It shows from the first moment, before the agent writes.
     Every piece is clickable: what was tested on it, where, and what came out.
   - Otherwise, the notebook notes that cite the session (their `sessions`); an old debugging
     note (type "debugging") is shown whole with the Notebooks renderer. */
let PZ={key:null,notes:[],note:null,mtime:0,expanded:false,busy:false,dep:null,depM:'',openIds:new Set(),sal:new Set()};
const wbMobile=()=>matchMedia('(max-width:760px)').matches;
const wbFolded=()=>stored('gatito-pz-off')==='1';
const wbIsDebug=a=>!!a&&(a.profile==='debug'||(PZ.key===a.key&&!!PZ.dep));
const pzHay=()=>!!CUR&&PZ.key===CUR.key&&(wbIsDebug(CUR)||PZ.notes.length>0);

function wbButton(a){
  if(PZ.key!==a.key||!(wbIsDebug(a)||PZ.notes.length))return'';
  const n=wbIsDebug(a)||PZ.notes[0]?.whiteboard?'Whiteboard':'Notes';
  return `<button class="btn ghost" data-act="pz" title="${n} for this session" aria-label="${n}">${ICON('book')}<span class="btn-t">${n}</span></button>`;
}

function pzReset(a){
  PZ={key:a.key,notes:[],note:null,mtime:0,expanded:false,busy:false,dep:null,depM:'',openIds:new Set(),sal:new Set()};
}

async function loadWhiteboard(force){
  const a=CUR; if(!a)return;
  if(PZ.key!==a.key){pzReset(a);wbDraw();if(wbIsDebug(a))renderDetail(false)}   // board and its button, at once
  if(wbIsDebug(a))await loadDep(force);
  if(!a.sessionId||PZ.busy)return;
  PZ.busy=true;
  try{
    const notes=await api('/api/session/notes?sid='+encodeURIComponent(a.sessionId));
    if(!CUR||CUR.key!==a.key)return;
    const habia=PZ.notes.length;
    PZ.notes=Array.isArray(notes)?notes:[];
    const p=PZ.notes.find(n=>n.whiteboard);
    if(!PZ.dep&&p&&(force||!PZ.note||PZ.note.relpath!==p.relpath||PZ.note.notebook!==p.notebook||p.mtime!==PZ.mtime)){
      const n=await api(`/api/notebook/note?id=${encodeURIComponent(p.notebook)}&relpath=${encodeURIComponent(p.relpath)}`);
      if(!CUR||CUR.key!==a.key)return;
      if(n&&n.text!=null){PZ.note={...n,notebook:p.notebook};PZ.mtime=p.mtime;wbDraw()}
    }else if(force||habia!==PZ.notes.length)wbDraw();
    if(habia!==PZ.notes.length)renderDetail(false);   // the header button appears
  }catch(e){}
  finally{PZ.busy=false}
}

// the live board: cheap (one small JSON, or {same} if nothing changed)
async function loadDep(force){
  const a=CUR; if(!a)return;
  const ids=[a.key,a.id,a.sessionId].filter(Boolean).map(encodeURIComponent).join(',');
  try{
    const r=await api(`/api/debug?ids=${ids}${!force&&PZ.depM?'&m='+PZ.depM:''}`);
    if(!CUR||CUR.key!==a.key||!r||r.same)return;
    const habia=!!PZ.dep;
    PZ.dep=r.whiteboard||null; PZ.depM=PZ.dep?String(PZ.dep.mtime):'';
    wbDraw();
    if(habia!==!!PZ.dep)renderDetail(false);
  }catch(e){}
}
setInterval(()=>{if(CUR&&wbIsDebug(CUR)&&CUR.ui==='working'&&!document.hidden)loadDep(false)},2000);

function wbDraw(){
  const d=$('#detail'); if(!d)return;
  let el=$('#pz');
  const hay=pzHay();
  const ver=hay&&(wbMobile()?PZ.expanded:!wbFolded());
  d.classList.toggle('pz-on',!!ver);
  if(!hay){el&&el.remove();return}
  if(!el){el=document.createElement('aside');el.id='pz';el.className='pz';d.appendChild(el)}
  el.hidden=!ver;
  if(!ver)return;
  const sc=el.querySelector('.pz-b')?.scrollTop||0;
  if(wbIsDebug(CUR))dbgDraw(el);else wbNotes(el);
  const b=el.querySelector('.pz-b'); if(b)b.scrollTop=sc;   // refreshing doesn't move you from where you are reading
  el.querySelector('[data-pz-x]').onclick=()=>pzToggle(false);
}

function wbNotes(el){
  const n=PZ.note, others=PZ.notes.filter(x=>!n||x.relpath!==n.relpath||x.notebook!==n.notebook);
  let html=`<div class="pz-h"><b>${n?'Whiteboard':'Notes for this session'}</b>
    ${n?`<a class="pz-t" href="${nbHash(n.notebook,n.relpath)}" title="Open in Notebooks">${esc(n.info?.title||n.relpath)}</a>
      ${nbChip('status',n.info?.status)}`:''}<span class="spacer"></span>
    <button class="btn ghost icon" data-pz-x aria-label="Collapse the whiteboard" title="Collapse">${ICON('x')}</button></div>`;
  if(n){const {body,off}=nbSinH1(n);
    html+=`<div class="pz-b nb-md">${nbMd(body,{id:n.notebook,dir:nbDir(n.relpath),off,relpath:n.relpath,mtime:n.mtime})}</div>`}
  if(others.length)html+=`<div class="pz-others"><div class="nb-sec">Other notes it cites</div>${others.map(x=>
    `<a class="nb-row" href="${nbHash(x.notebook,x.relpath)}">${ICON('book')}<span class="nb-rt">${esc(x.title)}</span></a>`).join('')}</div>`;
  el.innerHTML=html;
  enhance(el);
  el.querySelectorAll('input.nb-task').forEach(cb=>cb.onchange=async()=>{
    const r=await api('/api/notebook/task',{id:cb.dataset.id,relpath:cb.dataset.relpath,line:+cb.dataset.line,
      done:cb.checked,mtime:+cb.dataset.mtime}).catch(()=>({ok:false}));
    if(!r.ok){cb.checked=!cb.checked;toast('The whiteboard has changed: reloading',true)}
    loadWhiteboard(true);
  });
}

/* ---------------- the live debugging board ---------------- */
const DBG_MARK={ok:'✓',fails:'✗',suspect:'?',unchecked:'·',deduced:'≈',info:'i'};
const DP_TXT={ok:'OK',fails:'Fails',suspect:'Suspect',unchecked:'Not checked',deduced:'OK (inferred)',info:'Note'};
const DBG_CAUSE={ok:'Ruled out',fails:'Confirmed',suspect:'Suspect',unchecked:'Not checked',deduced:'Ruled out (inferred)'};
// before the agent draws its own path: the stack, bottom-up, in gray
const DBG_LADDER=[['L1-2','Link'],['L3','IP / routes'],['DNS','Name resolution'],['L4','Ports'],['L7','Application']];

function dbgDraw(el){
  const d=PZ.dep, a=CUR, works=a.ui==='working';
  const pieces=d?[...d.usual,...d.modules]:[];
  const count=k=>pieces.filter(p=>p.status===k).length;
  const cnt=d?[['ok',count('ok')+count('deduced')],['fails',count('fails')],['suspect',count('suspect')]]
    .filter(([,n])=>n).map(([k,n])=>`<span class="dp-c st-${k}">${DBG_MARK[k]} ${n}</span>`).join(''):'';
  const est=d?.status==='solved'?'<span class="dp-st ok">resolved</span>':'<span class="dp-st">in progress</span>';
  let html=`<div class="pz-h"><b>Whiteboard</b>${d?est:''}<span class="dp-cnt">${cnt}</span><span class="spacer"></span>
    <button class="btn ghost icon" data-pz-x aria-label="Collapse the whiteboard" title="Collapse">${ICON('x')}</button></div>
    <div class="pz-b dp">`;
  html+=`<div class="dp-sym"><div class="dp-k">Symptom</div>
    <div class="dp-sym-t">${d?.symptom?esc(d.symptom):`<span class="dp-wait">${works?'The agent is writing it down…':esc(a.name||'—')}</span>`}</div>
    ${d?.wait?`<div class="dp-esp">Expected: ${esc(d.wait)}</div>`:''}</div>`;
  if(d?.conclusion)html+=`<div class="dp-fin"><div class="dp-k">Cause</div><div>${esc(d.conclusion.cause)}</div>
    ${d.conclusion.fix?`<div class="dp-k">Fix</div><pre class="dp-pre">${esc(d.conclusion.fix)}</pre>`:''}</div>`;
  if(d?.next_step)html+=dbgNextStep(d.next_step,pieces);
  html+=`<section class="dp-sec"><h4><span class="dp-n">1</span>Usual causes</h4>`;
  html+=d?.usual.length?`<div class="dbg-causes">${d.usual.map(p=>dbgPiece(p,d,true)).join('')}</div>`
    :`<div class="dbg-empty">${works?'The agent is listing the usual causes of this symptom…':'None yet.'}</div>`;
  html+=`</section><section class="dp-sec"><h4><span class="dp-n">2</span>Path</h4>`;
  html+=d?.modules.length?`<div class="dbg-relpath">${d.modules.map(p=>dbgPiece(p,d,false)).join('')}</div>`
    :`<div class="dbg-relpath dbg-ghost">${DBG_LADDER.map(([c,n])=>`<div class="dp-p st-unchecked"><span class="dp-m">·</span>
        <span class="dbg-name">${n}</span><span class="dbg-layer">${c}</span></div>`).join('')}</div>
      <div class="dbg-empty">Bottom-up if nothing points elsewhere; the agent adapts it to the problem.</div>`;
  html+=`</section>`;
  if(d?.probes.length){
    html+=`<section class="dp-sec"><h4><span class="dp-n">${ICON('clock')}</span>Tests</h4><ol class="dp-tl">${d.probes.slice().reverse().map(t=>{
      const p=pieces.find(x=>x.id===t.piece);
      return `<li class="dp-tli r-${esc(t.res)}" data-ir="${esc(t.piece)}"><span class="dp-m">${DBG_MARK[t.res]||'·'}</span><b>#${t.n}</b>
        <span class="dp-tl-p">${esc(p?.name||t.piece)}</span><code>${esc(t.cmd)}</code><span class="dbg-where">${esc(t.where)}</span></li>`}).join('')}</ol></section>`;
  }
  html+=`</div>`;
  el.innerHTML=html;
  dpCablea(el);
}

function dbgNextStep(s,pieces){
  const p=s.piece&&pieces.find(x=>x.id===s.piece), yo=s.who==='user';
  return `<div class="dp-sig${yo?' yo':''}"><div class="dp-k">Next step${p?` · ${esc(p.name)}`:''}${yo?' · on your side':''}</div>
    <code class="dp-cmd">${esc(s.cmd)}</code>${s.why?`<div class="dp-why">${esc(s.why)}</div>`:''}
    <div class="dp-acts">
      ${yo?'':`<button class="btn primary" data-dp="run">${ICON('play')}Run it</button>`}
      <button class="btn${yo?' primary':''}" data-dp="mine">${ICON('copy')}I'll run it</button>
      <button class="btn ghost" data-dp="skip">Skip</button></div></div>`;
}

function dbgPiece(p,d,cause){
  const ts=d.probes.filter(t=>t.piece===p.id), expanded=PZ.openIds.has(p.id);
  const where=[...new Set(ts.map(t=>t.where))];
  const lab=(cause?DBG_CAUSE:DP_TXT)[p.status]||p.status;
  let h=`<div class="dp-pw${expanded?' open':''}" id="dp-${esc(p.id)}">
    <button class="dp-p st-${esc(p.status)}" data-p="${esc(p.id)}" aria-expanded="${expanded}">
      <span class="dp-m">${DBG_MARK[p.status]||'·'}</span><span class="dbg-name">${esc(p.name)}</span>
      ${p.layer?`<span class="dbg-layer">${esc(p.layer)}</span>`:''}
      <span class="dp-meta">${ts.length?`${ts.length} test${ts.length>1?'s':''} · ${esc(where.join(', '))}`:esc(lab)}</span>
    </button>`;
  if(expanded){
    h+=`<div class="dp-det"><div class="dp-lab st-${esc(p.status)}">${esc(lab)}</div>${p.note?`<div class="dbg-note">${esc(p.note)}</div>`:''}`;
    h+=ts.length?ts.map(t=>`<div class="dp-t r-${esc(t.res)}">
        <div class="dp-t-h"><span class="dp-m">${DBG_MARK[t.res]||'·'}</span><b>#${t.n}</b>
          <code class="dp-cmd" title="Copy">${esc(t.cmd)}</code><button class="btn ghost icon dp-cp" data-cp="${esc(t.cmd)}" aria-label="Copy">${ICON('copy')}</button></div>
        <div class="dp-t-r">${esc(t.summary)}</div>
        <div class="dbg-where">${esc(t.where)} · ${esc(t.ts.slice(11))}</div>
        ${t.output?`<details data-sal="${t.n}"${PZ.sal.has(t.n)?' open':''}><summary>Output</summary><pre class="dp-pre">${esc(t.output)}</pre></details>`:''}
      </div>`).join(''):`<div class="dbg-empty">Nothing tested here yet.</div>`;
    h+=`<div class="dp-acts"><button class="btn" data-mira="${esc(p.id)}">Look at this</button></div></div>`;
  }
  return h+`</div>`;
}

function dpCablea(el){
  const d=PZ.dep;
  el.querySelectorAll('[data-p]').forEach(b=>b.onclick=()=>{
    const id=b.dataset.p; PZ.openIds.has(id)?PZ.openIds.delete(id):PZ.openIds.add(id); wbDraw()});
  el.querySelectorAll('[data-ir]').forEach(li=>li.onclick=()=>{
    const id=li.dataset.ir; PZ.openIds.add(id); wbDraw();
    $('#dp-'+CSS.escape(id))?.scrollIntoView({block:'nearest',behavior:'smooth'})});
  el.querySelectorAll('details[data-sal]').forEach(x=>x.ontoggle=()=>{
    x.open?PZ.sal.add(+x.dataset.sal):PZ.sal.delete(+x.dataset.sal)});
  el.querySelectorAll('[data-cp]').forEach(b=>b.onclick=async()=>toast(await copy(b.dataset.cp)?'Copied':'Could not copy',false));
  el.querySelectorAll('[data-mira]').forEach(b=>b.onclick=()=>{
    const p=[...d.usual,...d.modules].find(x=>x.id===b.dataset.mira);
    dpEnvia(`Look at «${p?.name||b.dataset.mira}» next.`)});
  const s=d?.next_step; if(!s)return;
  el.querySelector('[data-dp="run"]')?.addEventListener('click',()=>dpEnvia(`Run it: ${s.cmd}`));
  el.querySelector('[data-dp="mine"]').onclick=async()=>{
    const ok=await copy(s.cmd);
    dpPrepara(`I ran \`${s.cmd}\` myself. Output:\n`);
    toast(ok?'Command copied: paste the output in the reply':'Could not copy the command',!ok);
  };
  el.querySelector('[data-dp="skip"]').onclick=()=>dpPrepara('Skip that step: ');
}

// buttons on the board answer in the chat (sendReply resumes the session if it has finished)
function dpPrepara(t){
  const r=$('#r-text'); if(!r)return toast('This session is open in a terminal: reply from there',true);
  r.value=t; autosize(r);
  if(wbMobile())pzToggle(false);
  r.focus(); r.setSelectionRange(r.value.length,r.value.length);
}
function dpEnvia(t){
  const r=$('#r-text'); if(!r)return toast('This session is open in a terminal: reply from there',true);
  if(r.value.trim()&&!confirm('Replace what you are typing?'))return;
  r.value=t; sendReply();
}

function pzToggle(on){
  if(wbMobile())PZ.expanded=on??!PZ.expanded;
  else store('gatito-pz-off',(on??wbFolded())?null:'1');
  wbDraw();
}
addEventListener('resize',()=>{if(pzHay())wbDraw()});
