/* "Notebooks" view (#/notebooks): the solid state of long-running work.
   Each notebook is a folder of Markdown with metadata in ~/gatito/notebooks (it opens
   the same way in Obsidian): cover, status.md (living memory), folders per project
   or topic, notes, diagrams, flows with checkboxes and the conversations that worked there.
   #/notebooks                  list
   #/notebooks/<id>             notebook cover
   #/notebooks/<id>/<relpath>      a note or a file */

let NB={listing:[],sig:'',q:'',id:null,c:null,csig:'',relpath:null,note:null,edit:false,ver:null,filter:'',
  kinds:{},statuses:[],search:null};
const NB_KIND={notebook:'Cover',status:'Status',folder:'Index',note:'Note',explanation:'Explanation',
  decision:'Decision',runbook:'Runbook',flow:'Flow',journal:'Journal',reference:'Reference',session:'Session'};
const NB_STATUS={draft:'Draft','in-progress':'In progress',review:'Review',done:'Done',archived:'Archived'};
const nbHash=(id,relpath)=>'#/notebooks/'+encodeURIComponent(id)+(relpath?'/'+relpath.split('/').map(encodeURIComponent).join('/'):'');
const nbRaw=(id,relpath,dl)=>`/api/notebook/raw?id=${encodeURIComponent(id)}&relpath=${encodeURIComponent(relpath)}${dl?'&dl=1':''}`;
const nbEsMd=r=>/\.md$/i.test(r||'');
const nbDir=r=>{const i=(r||'').lastIndexOf('/');return i<0?'':r.slice(0,i)};
function nbJoin(base,rel){
  const out=rel.startsWith('/')?[]:(base?base.split('/'):[]);
  for(const p of rel.replace(/^\/+/,'').split('/')){
    if(!p||p==='.')continue; if(p==='..')out.pop(); else out.push(p);
  }
  return out.join('/');
}
function nbChip(kind,v){if(!v)return'';
  const t=kind==='kind'?(NB_KIND[v]||v):kind==='status'?(NB_STATUS[v]||v):v;
  return`<span class="nb-chip ${kind} ${kind}-${esc(v)}">${esc(t)}</span>`}

function initNb(){
  $('#v-nb').innerHTML=`<header class="vh"><h1>Notebooks</h1><span class="sub" id="nb-sub"></span>
    <div class="vh-tools">
      <input class="art-q" id="nb-q" type="search" placeholder="Search notes…" aria-label="Search notebooks">
      <button class="btn primary" id="nb-new" type="button">${ICON('plus')}Notebook</button>
    </div></header>
    <div class="nb-body">
      <div class="nb-home" id="nb-home"></div>
      <aside class="nb-side" id="nb-side" hidden></aside>
      <section class="nb-main" id="nb-main" hidden></section>
    </div>`;
  $('#nb-new').onclick=newNotebook;
  $('#nb-q').oninput=e=>{clearTimeout(NB._t);const v=e.target.value.trim();
    NB._t=setTimeout(()=>searchNb(v),250)};
}

/* ---------------- list ---------------- */
async function renderNb(force){
  if(VIEW!=='nb'&&!force)return;
  try{const r=await api('/api/notebooks');
    NB.kinds=r.kinds||{}; NB.statuses=r.statuses||[]; NB.root=r.root;
    const sig=JSON.stringify(r.notebooks.map(c=>[c.id,c.mtime,c.title,c.notes,c.tasks_open]));
    syncNotebooks(r.notebooks);
    if(sig!==NB.sig||force){NB.sig=sig;NB.listing=r.notebooks;renderNbHome()}
  }catch(e){return}
  // the tree and its conversations every 15 s (scans the whole history); the open note, every 5
  if(NB.id&&(force||Date.now()-(NB._tc||0)>15000)){NB._tc=Date.now();loadNotebook(false)}
  if(NB.id&&NB.relpath&&!NB.edit&&!NB.ver)reloadNote();
}
function renderNbHome(){
  const h=$('#nb-home'); if(!h)return;
  $('#nb-sub').textContent=NB.listing.length?`${NB.listing.length} notebook${NB.listing.length>1?'s':''}`:'';
  if(NB.search)return renderSearch();
  if(!NB.listing.length){h.innerHTML=`<div class="art-empty"><b>No notebooks yet.</b>
    A notebook keeps the state of long-running work (an engineering project or something
    you are learning): notes with metadata, explanations, decisions, flows with checkboxes
    and diagrams, plus the conversations that worked on it. They are Markdown files in
    <code>${esc(home(NB.root||'~/gatito/notebooks'))}</code> and open as-is in Obsidian.
    <p><button class="btn primary" type="button" id="nb-new2">${ICON('plus')}Create the first one</button></p></div>`;
    $('#nb-new2').onclick=newNotebook;return}
  h.innerHTML=`<div class="nb-grid">${NB.listing.map(c=>`<a class="nb-card${c.id===NB.id?' on':''}" href="${nbHash(c.id)}">
      <b>${esc(c.title)}</b>
      ${c.summary?`<span class="nb-res">${esc(c.summary)}</span>`:''}
      <span class="nb-tags">${(c.tags||[]).map(t=>`<span class="nb-chip tag">#${esc(t)}</span>`).join('')}</span>
      <span class="art-meta">${c.notes} notes · ${c.folders} folders${c.tasks_open?` · <span class="nb-open">${c.tasks_open} to do</span>`:''}
        ${c.updated?` · ${esc(nbAgo(c.mtime))}`:''}</span></a>`).join('')}</div>`;
}
function nbAgo(sec){return sec?ago(sec*1000):''}

async function searchNb(q){
  if(!q){NB.search=null;return NB.id?renderNbMain():renderNbHome()}
  const r=await api('/api/notebooks/search?q='+encodeURIComponent(q)).catch(()=>[]);
  NB.search={q,items:r};
  if(NB.id)location.hash='#/notebooks'; else renderSearch();
}
function renderSearch(){
  const h=$('#nb-home'), b=NB.search;
  h.innerHTML=`<div class="nb-results"><div class="nb-sec">${b.items.length} result${b.items.length===1?'':'s'} for "${esc(b.q)}"</div>
    ${b.items.map(r=>`<a class="nb-hit" href="${nbHash(r.notebook,r.relpath)}"><b>${esc(r.title)}</b>
      <span class="art-meta">${nbChip('kind',r.kind)}${nbChip('status',r.status)}<span>${esc(r.notebook)}/${esc(r.relpath)}</span></span>
      ${r.snippet?`<span class="nb-frag">${esc(r.snippet)}</span>`:''}</a>`).join('')||'<div class="art-empty">No matches.</div>'}</div>`;
}

/* ---------------- one notebook ---------------- */
async function openNb(id,relpath){
  const changes=NB.id!==id;
  if(!changes&&(relpath||null)===NB.relpath&&NB.edit)return;   // keep editing what you had
  NB.id=id; $('#v-nb').classList.add('viewing');
  $('#nb-side').hidden=false; $('#nb-main').hidden=false;
  if(changes){NB.c=null;NB.csig='';NB.filter='';NB.sesTodas=false;$('#nb-side').innerHTML='<div class="art-empty">Loading…</div>'}
  if(NB.search){NB.search=null;$('#nb-q').value=''}
  if(NB.edit&&relpath!==NB.relpath&&!await leaveEdit())return location.hash=nbHash(id,NB.relpath);
  NB.relpath=relpath||null; NB.note=null; NB.edit=false; NB.ver=null;
  if(changes)nbDirsLoad(id);
  if(relpath)nbOpenPath(relpath);
  $('#v-nb').classList.toggle('reading',!!relpath);
  await loadNotebook(true);
  renderNbMain();
}
function closeNb(){
  NB.id=NB.c=NB.relpath=NB.note=null; NB.edit=false; NB.ver=null;
  $('#v-nb').classList.remove('viewing','reading');
  $('#nb-side').hidden=true; $('#nb-main').hidden=true;
  renderNbHome();
}
async function leaveEdit(){
  if($('#nbe'))return !edDirty()||confirmBox('Unsaved changes','If you leave now, what you changed in this note is lost.','Leave without saving');
  const t=$('#nb-ed'); if(!t||!NB.note||t.value===NB.note.text)return true;
  return confirmBox('Unsaved changes','If you leave now, what you wrote in this note is lost.','Leave without saving');
}
async function loadNotebook(force){
  const id=NB.id; let c;
  try{c=await api('/api/notebook?id='+encodeURIComponent(id))}catch(e){return}
  if(NB.id!==id)return;
  if(c.ok===false){NB.c=null;$('#nb-side').innerHTML='';$('#nb-main').innerHTML='<div class="art-empty">This notebook no longer exists.</div>';return}
  const sig=JSON.stringify([c.tree,c.sessions.map(s=>[s.sid,s.ui,s.updatedAt]),c.title]);
  if(sig===NB.csig&&!force)return;
  NB.csig=sig; NB.c=c; NB.notes=nbNotes(c.tree);
  renderNbSide();
  if(!NB.relpath&&!force)renderNbMain();
}
/* Tree folders: closed by default. Only the folder of the note you open opens, and opening one
   by hand closes its siblings (accordion), so the tree does not grow with every click.
   Remembered per notebook in this browser. */
function nbDirsLoad(id){let v=[];try{v=JSON.parse(stored('nb-dirs:'+id)||'[]')}catch{}NB.dirs=new Set(Array.isArray(v)?v:[])}
function nbDirsSave(){if(NB.id&&NB.dirs)store('nb-dirs:'+NB.id,JSON.stringify([...NB.dirs]))}
function nbOpenPath(relpath){
  if(!NB.dirs)nbDirsLoad(NB.id);
  const ps=relpath.split('/').slice(0,-1);
  for(let k=1;k<=ps.length;k++){const r=ps.slice(0,k).join('/'), padre=ps.slice(0,k-1).join('/');
    // the other folders at that level close: only the way to this note stays open
    for(const d of [...NB.dirs])if(d!==r&&nbDir(d)===padre&&!r.startsWith(d+'/'))nbDirsClose(d);
    NB.dirs.add(r)}
  nbDirsSave();
}
function nbDirsClose(r){for(const d of [...NB.dirs])if(d===r||d.startsWith(r+'/'))NB.dirs.delete(d)}
function nbNotes(n,out=[]){for(const h of n.children||[]){if(h.children)nbNotes(h,out);else if(h.note)out.push(h)}return out}
function nbFolders(n,out=['']){for(const h of n.children||[])if(h.children&&h.name!=='diagrams'){out.push(h.relpath);nbFolders(h,out)}return out}

/* The notebook's conversations: a folded section under the tree (they used to stay open
   and, with many, buried the notes). Closed by default, remembered per notebook; shows the
   latest few and "Show all" for the rest. While filtering, the matching ones show open. */
const NB_SES_VISIBLE=5;
function nbSessions(c,f){
  const todas=c.sessions||[];
  const listing=f?todas.filter(x=>(x.title||'').toLowerCase().includes(f)):todas;
  if(!listing.length)return '';
  const expanded=!!f||stored('nb-ses:'+c.id)==='1';
  const live=listing.filter(x=>x.ui==='working'||x.ui==='waiting').length;
  const ver=f||NB.sesTodas?listing:listing.slice(0,NB_SES_VISIBLE);
  return`<details class="nb-ses"${expanded?' open':''}><summary class="nb-sec">${ICON('chev')}Conversations
      <span class="n">${listing.length}</span>${live?`<i class="nb-dot e-in-progress" title="${live} active"></i>`:''}</summary>
    ${ver.map(x=>`<button class="nb-row ses" type="button" data-sid="${esc(x.sid)}" title="${esc(x.title)}">
      <i class="nb-dot ${x.ui==='working'?'e-in-progress':x.ui==='waiting'?'e-review':'e-none'}"></i>
      <span class="nb-rt">${esc(x.title)}</span><span class="nb-ty">${esc(nbAgo((x.updatedAt||0)/1000))}</span></button>`).join('')}
    ${!f&&listing.length>NB_SES_VISIBLE?`<button class="nb-row nb-more" type="button" id="nb-ses-more">${NB.sesTodas?'Show fewer':`Show all ${listing.length}`}</button>`:''}
  </details>`;
}

function renderNbSide(){
  const c=NB.c, s=$('#nb-side'); if(!c)return;
  if(!NB.dirs)nbDirsLoad(c.id);
  const scroll=s.querySelector('.nb-tree')?.scrollTop||0;   // re-rendering must not jump to the top
  const f=NB.filter.toLowerCase();
  const matches=h=>!f||[h.note.title,h.note.kind,h.note.status,(h.note.tags||[]).join(' '),h.relpath].join(' ').toLowerCase().includes(f);
  const row=h=>{const i=h.note, ab=i.pending;
    return`<a class="nb-row${h.relpath===NB.relpath?' on':''}" href="${nbHash(c.id,h.relpath)}" title="${esc(i.summary||h.relpath)}">
      <i class="nb-dot e-${esc(i.status||'none')}"></i><span class="nb-rt">${esc(i.title)}</span>
      ${ab?`<span class="nb-n">${ab}</span>`:''}<span class="nb-ty">${esc(NB_KIND[i.kind]||i.kind)}</span></a>`};
  const fileRow=h=>`<a class="nb-row file${h.relpath===NB.relpath?' on':''}" href="${nbHash(c.id,h.relpath)}">${ICON(/^(svg|png|jpe?g|gif|webp)$/.test(h.ext)?'image':'code')}<span class="nb-rt">${esc(h.name)}</span></a>`;
  const rama=(n,prof)=>{
    const children=n.children||[];
    const idx=children.find(h=>h.note&&h.name==='README.md'&&prof>0);
    const rest=children.filter(h=>h!==idx&&!(prof===0&&['notebook.md','status.md'].includes(h.name)));
    let html='';
    for(const h of rest){
      if(h.children){
        const sub=rama(h,prof+1); if(f&&!sub.trim())continue;
        const i=h.index, expanded=f||NB.dirs.has(h.relpath);
        html+=`<details class="nb-dir" data-dir="${esc(h.relpath)}"${expanded?' open':''}><summary>${ICON('chev')}
          ${i?`<a href="${nbHash(c.id,h.relpath+'/README.md')}" class="nb-dn${NB.relpath===h.relpath+'/README.md'?' on':''}">${esc(i.title)}</a>`:`<span class="nb-dn">${esc(h.name)}</span>`}
          ${i&&i.status?`<i class="nb-dot e-${esc(i.status)}"></i>`:''}</summary><div class="nb-in">${sub}</div></details>`;
      }else if(h.note){if(matches(h))html+=row(h)}
      else if(!f)html+=fileRow(h);
    }
    return html;
  };
  const top=n=>(c.tree.children||[]).find(h=>h.name===n);
  s.innerHTML=`<div class="nb-head">
      <a class="btn ghost icon nb-back" href="#/notebooks" aria-label="All notebooks">${ICON('back')}</a>
      <a class="nb-title${!NB.relpath?' on':''}" href="${nbHash(c.id)}"><b>${esc(c.title)}</b>
        <span>${c.notes} notes${c.tasks_open?` · ${c.tasks_open} to do`:''}</span></a>
      <button class="btn ghost icon" type="button" id="nb-fold" title="Collapse all folders" aria-label="Collapse all folders">${ICON('folder')}</button>
    </div>
    <div class="nb-acts">
      <button class="btn primary" type="button" id="nb-chat">${ICON('chat')}Session here</button>
      <button class="btn ghost" type="button" id="nb-nn">${ICON('plus')}Note</button>
      <button class="btn ghost" type="button" id="nb-nf">${ICON('folder')}Folder</button>
    </div>
    <input class="art-q nb-filter" id="nb-f" type="search" placeholder="Filter notes…" value="${esc(NB.filter)}">
    <nav class="nb-tree">
      ${!f?`<a class="nb-row pin nb-mob" href="${nbHash(c.id,'notebook.md')}">${ICON('book')}<span class="nb-rt">Cover</span></a>`:''}
      ${rama(c.tree,0)||'<div class="nb-empty">No matches.</div>'}
      ${nbSessions(c,f)}
    </nav>`;
  $('#nb-chat').onclick=()=>sessionInNb();
  $('#nb-nn').onclick=()=>newNote();
  $('#nb-nf').onclick=()=>newFolder();
  const fi=$('#nb-f'); fi.oninput=()=>{NB.filter=fi.value;renderNbSide();const n=$('#nb-f');n.focus();n.setSelectionRange(n.value.length,n.value.length)};
  s.querySelectorAll('[data-sid]').forEach(b=>b.onclick=()=>openSession(c.sessions.find(x=>x.sid===b.dataset.sid)));
  const sd=s.querySelector('details.nb-ses');
  if(sd)sd.addEventListener('toggle',()=>{if(!f)store('nb-ses:'+c.id,sd.open?'1':null)});
  const more=$('#nb-ses-more'); if(more)more.onclick=()=>{NB.sesTodas=!NB.sesTodas;renderNbSide()};
  s.querySelector('.nb-tree').scrollTop=scroll;
  $('#nb-fold').onclick=()=>{NB.dirs.clear();nbDirsSave();s.querySelectorAll('details.nb-dir[open]').forEach(d=>d.open=false)};
  s.querySelectorAll('details.nb-dir>summary').forEach(sm=>sm.addEventListener('click',e=>{
    if(e.target.closest('a'))return;              // the folder name opens its index; the arrow folds
    if(NB.filter)return;                         // while filtering everything that matches is shown
    e.preventDefault();
    const d=sm.parentElement, r=d.dataset.dir;
    if(d.open){d.open=false;nbDirsClose(r)}
    else{
      d.parentElement.querySelectorAll(':scope>details.nb-dir[open]').forEach(o=>{o.open=false;nbDirsClose(o.dataset.dir)});
      d.open=true; NB.dirs.add(r);
    }
    nbDirsSave();
  }));
}

/* ---------------- cover / note ---------------- */
async function renderNbMain(){
  const m=$('#nb-main'), c=NB.c; if(!c)return;
  if(!NB.relpath)return renderCover();
  const relpath=NB.relpath;
  if(!nbEsMd(relpath)&&!/\.(txt|py|ya?ml|json|csv|tf|sh|mmd)$/i.test(relpath))return renderFile();
  if(!NB.note||NB.note.relpath!==relpath){
    m.innerHTML='<div class="art-empty">Loading…</div>';
    const n=await api(`/api/notebook/note?id=${encodeURIComponent(c.id)}&relpath=${encodeURIComponent(relpath)}${NB.ver?'&v='+NB.ver:''}`).catch(()=>null);
    if(NB.relpath!==relpath)return;
    if(!n||n.ok===false){m.innerHTML='<div class="art-empty">This note no longer exists.</div>';return}
    NB.note=n;
  }
  if(NB.editOnOpen===relpath){NB.editOnOpen=null;NB.edit=true}
  NB.edit?renderEditor():renderNote();
}
async function reloadNote(){
  const c=NB.c, relpath=NB.relpath; if(!c||!relpath||!NB.note)return;
  const n=await api(`/api/notebook/note?id=${encodeURIComponent(c.id)}&relpath=${encodeURIComponent(relpath)}`).catch(()=>null);
  if(n&&n.mtime&&NB.relpath===relpath&&!NB.edit&&!NB.ver&&n.mtime!==NB.note.mtime){NB.note=n;renderNote()}
}

async function renderCover(){
  const c=NB.c, m=$('#nb-main');
  const p=(c.tree.children||[]).some(h=>h.name==='notebook.md')?await api(`/api/notebook/note?id=${encodeURIComponent(c.id)}&relpath=notebook.md`).catch(()=>null):null;
  if(NB.relpath||NB.c!==c)return;
  const recent=NB.notes.filter(h=>!['notebook.md','status.md'].includes(h.relpath)).sort((a,b)=>b.note.mtime-a.note.mtime).slice(0,8);
  const pend=NB.notes.filter(h=>h.note.pending&&h.relpath!=='status.md');
  m.innerHTML=`<article class="nb-doc">
    <div class="nb-bar"><div class="nb-crumb">Notebook</div><span class="spacer"></span>
      <a class="btn ghost" href="${nbHash(c.id,'notebook.md')}">Edit cover</a></div>
    <h1 class="nb-h">${esc(c.title)}</h1>
    <div class="nb-meta">${nbChip('status',c.status)}${(c.tags||[]).map(t=>nbChip('tag','#'+t)).join('')}
      ${c.repos.length?`<span class="nb-chip repo">${ICON('branch')}${c.repos.map(esc).join(', ')}</span>`:''}</div>
    ${c.summary?`<p class="nb-lead">${esc(c.summary)}</p>`:''}
    <div class="nb-cols" style="grid-template-columns:minmax(0,1fr)">
      <section class="nb-panel"><div class="nb-sec">Recent</div>
        ${recent.map(h=>`<a class="nb-row" href="${nbHash(c.id,h.relpath)}"><i class="nb-dot e-${esc(h.note.status||'none')}"></i>
          <span class="nb-rt">${esc(h.note.title)}</span><span class="nb-ty">${esc(nbAgo(h.note.mtime))}</span></a>`).join('')||'<p class="nb-empty">No notes yet.</p>'}
        ${pend.length?`<div class="nb-sec">With open tasks</div>${pend.map(h=>`<a class="nb-row" href="${nbHash(c.id,h.relpath)}">
          <span class="nb-rt">${esc(h.note.title)}</span><span class="nb-n">${h.note.pending}</span></a>`).join('')}`:''}
      </section>
    </div>
    ${p&&p.body.trim()?`<div class="nb-md nb-cover">${nbMd(nbSinH1(p).body,{id:c.id,dir:'',off:nbSinH1(p).off,relpath:'notebook.md',mtime:p.mtime})}</div>`:''}
  </article>`;
  wireNbMd(m);
}
function nbOff(n){return n.text.slice(0,n.text.length-n.body.length).split('\n').length-1}
// the leading "# Title" already shows above as the title: drop it, keeping the line count (checkboxes)
function nbSinH1(n){
  const body=n.body.replace(/^\s*#\s+[^\n]*\n/,'\n');
  return{body,off:nbOff(n)+n.body.split('\n').length-body.split('\n').length};
}

function renderNote(){
  const n=NB.note, c=NB.c, m=$('#nb-main'), i=n.info||{}, meta=n.meta||{};
  const parts=n.relpath.split('/');
  const crumb=parts.slice(0,-1).map((p,k)=>{const r=parts.slice(0,k+1).join('/');
    const idx=NB.notes.find(h=>h.relpath===r+'/README.md');
    return idx?`<a href="${nbHash(c.id,r+'/README.md')}">${esc(idx.note.title)}</a>`:esc(p)}).join(' / ');
  const ses=(i.sessions||[]).map(sid=>c.sessions.find(s=>s.sid===sid)||{sid,title:'Conversation '+sid.slice(0,8)});
  const title=i.title||n.relpath;
  const {body,off}=nbEsMd(n.relpath)?nbSinH1(n):{body:null,off:0};
  m.innerHTML=`<article class="nb-doc">
    <div class="nb-bar">
      <a class="btn ghost icon nb-up" href="${nbHash(c.id)}" aria-label="Back to notebook">${ICON('back')}</a>
      <div class="nb-crumb">${crumb||esc(c.title)}</div><span class="spacer"></span>
      ${NB.ver?`<span class="nb-chip ver">Version ${esc(NB.ver)}</span>
        <button class="btn primary" id="nb-restore">${ICON('restore')}Restore</button>
        <button class="btn ghost" id="nb-now">View current</button>`
      :`<button class="btn ghost" id="nb-ask" title="Open a session about this note">${ICON('chat')}<span class="nb-lbl">Ask</span></button>
        <button class="btn ghost" id="nb-hist" title="Previous versions">${ICON('clock')}<span class="nb-lbl">History</span></button>
        ${nbEsMd(n.relpath)?`<button class="btn ghost" id="nb-pdf" title="Export to PDF (print dialog: Save as PDF)">${ICON('download')}<span class="nb-lbl">PDF</span></button>`:''}
        <button class="btn ghost" id="nb-edit">Edit</button>
        <button class="btn ghost icon danger" id="nb-del" aria-label="Delete note" title="Delete (to the trash)">${ICON('trash')}</button>`}
    </div>
    <h1 class="nb-h">${esc(title)}</h1>
    <div class="nb-meta">${nbChip('kind',i.kind)}${nbChip('status',i.status)}${(i.tags||[]).map(t=>nbChip('tag','#'+t)).join('')}
      ${i.updated?`<span class="nb-when" title="Created ${esc(i.created||'—')}">${esc(i.updated)}</span>`:''}
      ${i.tasks&&(i.tasks[0]+i.tasks[1])?`<span class="nb-when">${i.tasks[1]}/${i.tasks[0]+i.tasks[1]} done</span>`:''}</div>
    ${i.summary?`<p class="nb-lead">${esc(i.summary)}</p>`:''}
    ${!i.frontmatter&&nbEsMd(n.relpath)?`<p class="nb-warn">This note has no metadata. Ask an agent to run <code>notebook touch ${esc(n.relpath)}</code> or add it when editing.</p>`:''}
    <div class="nb-md">${body!==null?nbMd(body,{id:c.id,dir:nbDir(n.relpath),off,relpath:n.relpath,mtime:n.mtime,ro:!!NB.ver}):codeBox(n.relpath.split('.').pop(),n.text)}</div>
    ${ses.length||(meta.sources||[]).length?`<footer class="nb-foot">
      ${ses.length?`<div class="nb-sec">Conversations</div>${ses.map(s=>`<button class="nb-row ses" type="button" data-sid="${esc(s.sid)}">${ICON('chat')}<span class="nb-rt">${esc(s.title)}</span></button>`).join('')}`:''}
      ${(meta.sources||[]).length?`<div class="nb-sec">Sources</div>${meta.sources.map(f=>`<div class="nb-src">${nbInline(String(f),{id:c.id,dir:nbDir(n.relpath)})}</div>`).join('')}`:''}
    </footer>`:''}
  </article>`;
  wireNbMd(m);
  m.querySelectorAll('[data-sid]').forEach(b=>b.onclick=()=>{
    const s=c.sessions.find(x=>x.sid===b.dataset.sid); s?openSession(s):toast('That conversation is no longer in the history',true)});
  if(NB.ver){
    $('#nb-now').onclick=()=>{NB.ver=null;NB.note=null;renderNbMain()};
    $('#nb-restore').onclick=restore;
    return;
  }
  $('#nb-edit').onclick=()=>{NB.edit=true;renderEditor()};
  if($('#nb-pdf'))$('#nb-pdf').onclick=nbPdfNote;
  $('#nb-hist').onclick=historyNote;
  $('#nb-del').onclick=deleteNote;
  $('#nb-ask').onclick=()=>sessionInNb(`About the note "${title}" (${n.relpath}): `);
}

function renderFile(){
  const c=NB.c, r=NB.relpath, m=$('#nb-main'), u=nbRaw(c.id,r);
  const img=/\.(svg|png|jpe?g|gif|webp)$/i.test(r), html=/\.html?$/i.test(r), pdf=/\.pdf$/i.test(r);
  m.innerHTML=`<article class="nb-doc wide">
    <div class="nb-bar"><a class="btn ghost icon nb-up" href="${nbHash(c.id)}" aria-label="Back to notebook">${ICON('back')}</a>
      <div class="nb-crumb">${esc(r)}</div><span class="spacer"></span>
      <a class="btn ghost" href="${esc(u)}" target="_blank" rel="noopener">${ICON('external')}Open</a>
      <a class="btn ghost" href="${esc(nbRaw(c.id,r,1))}" download>${ICON('download')}Download</a></div>
    <div class="nb-file">${img?`<div class="art-img"><img src="${esc(u)}" alt="${esc(r)}"></div>`
      :html||pdf?`<iframe class="art-frame" src="${esc(u)}" ${html?'sandbox="allow-scripts"':''} title="${esc(r)}"></iframe>`
      :'<div class="art-empty">Cannot be shown here: download it.</div>'}</div></article>`;
  const im=m.querySelector('.art-img'); if(im)im.onclick=()=>im.classList.toggle('zoom');
}

/* ---------------- edit ---------------- */
// Markdown notes: the block editor (nbed.js). Other text files (.py, .yaml…): the plain textarea.
function renderEditor(){
  if(nbEsMd(NB.note.relpath))return renderBlocks(NB.note);
  const n=NB.note, m=$('#nb-main');
  m.innerHTML=`<article class="nb-doc nb-editing">
    <div class="nb-bar"><div class="nb-crumb">Editing ${esc(n.relpath)}</div><span class="spacer"></span>
      <button class="btn ghost" id="nb-cancel">Cancel</button>
      <button class="btn primary" id="nb-save">Save</button></div>
    <p class="nb-hint">Markdown with its metadata on top (between <code>---</code>). <code>updated</code> is set automatically on save. Ctrl+S saves.</p>
    <textarea id="nb-ed" class="nb-ed" spellcheck="true"></textarea></article>`;
  const t=$('#nb-ed'); t.value=n.text; t.focus();
  $('#nb-cancel').onclick=async()=>{if(await leaveEdit()){NB.edit=false;renderNote()}};
  $('#nb-save').onclick=()=>saveNote();
  t.onkeydown=e=>{if((e.ctrlKey||e.metaKey)&&e.key==='s'){e.preventDefault();saveNote()}};
}
async function saveNote(force){
  const n=NB.note, t=$('#nb-ed'); if(!t)return;
  const r=await api('/api/notebook/note/save',{id:NB.c.id,relpath:n.relpath,text:t.value,mtime:force?undefined:n.mtime}).catch(()=>({ok:false,err:'no connection'}));
  if(r.conflict){
    if(await confirmBox('The note has changed','Someone (maybe an agent) modified it while you were editing. Save yours over it? The previous version stays in the history.','Save over it',false))return saveNote(true);
    return;
  }
  if(!r.ok)return toast('Could not save: '+(r.err||''),true);
  toast('Saved'); NB.edit=false; NB.note=null; await loadNotebook(true); renderNbMain();
}

/* ---------------- checkboxes, links and images in a note ---------------- */
function wireNbMd(root){
  enhance(root);
  root.querySelectorAll('input.nb-task').forEach(cb=>cb.onchange=async()=>{
    const r=await api('/api/notebook/task',{id:cb.dataset.id,relpath:cb.dataset.relpath,line:+cb.dataset.line,
      done:cb.checked,mtime:+cb.dataset.mtime}).catch(()=>({ok:false}));
    if(!r.ok){cb.checked=!cb.checked;toast(r.conflict?'The note has changed: reloading':'Could not tick it',true)}
    if(NB.note&&NB.note.relpath===cb.dataset.relpath)NB.note=null;
    await loadNotebook(true); renderNbMain();
  });
}

/* Note Markdown: somewhat fuller than the chat's (lists, checkboxes, quotes and
   Obsidian callouts, links between notes and [[wikilinks]], italics, strikethrough). */
function nbLink(href,ctx){
  if(/^(https?:|mailto:)/i.test(href))return{href,ext:true};
  if(href.startsWith('#'))return{href:'javascript:void 0'};
  const [p]=href.split('#'), r=nbJoin(ctx.dir,decodeURIComponent(p));
  return{href:nbEsMd(r)||!/\.[a-z0-9]+$/i.test(r)?nbHash(ctx.id,nbEsMd(r)?r:r+'.md'):nbRaw(ctx.id,r)};
}
function nbWiki(name){
  const k=name.toLowerCase().trim();
  return (NB.notes||[]).find(h=>h.name.toLowerCase()===k+'.md'||h.relpath.toLowerCase()===k+'.md'||h.relpath.toLowerCase()===k
    ||(h.note.title||'').toLowerCase()===k);
}
function nbImgSrc(src,ctx){
  if(/^data:image\//.test(src))return src;
  if(/^(https?:)/.test(src))return null;            // no network: internet images are not loaded
  const ar=typeof artRef==='function'&&artRef(src); if(ar)return artUrl(ar.id,ar.v,ar.f);
  if(/^(\/home\/|~\/)/.test(src))return fileUrl(src);
  return nbRaw(ctx.id,nbJoin(ctx.dir,decodeURIComponent(src)));
}
function nbInline(s,ctx){
  const code=[]; s=esc(s).replace(/`([^`\n]+)`/g,(_,c)=>{code.push(c);return`\u0000${code.length-1}\u0000`});
  const un=x=>x.replace(/&amp;/g,'&').replace(/&#39;/g,"'").replace(/&quot;/g,'"').replace(/&lt;/g,'<').replace(/&gt;/g,'>');
  s=s.replace(/!\[([^\]]*)\]\(([^)\s]+)(?:\s+&quot;[^&]*&quot;)?\)/g,(_,alt,src)=>{const u=nbImgSrc(un(src),ctx);
      return u?`<img class="nb-ii" src="${esc(u)}" alt="${alt}" loading="lazy">`:`<span class="nb-missing">[external image: ${alt||'untitled'}]</span>`})
    .replace(/!\[\[([^\]|]+)(?:\|[^\]]*)?\]\]/g,(_,f)=>`<img class="nb-ii" src="${esc(nbImgSrc(un(f),ctx))}" alt="" loading="lazy">`)
    .replace(/\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g,(_,t,a)=>{const h=nbWiki(un(t));
      return h?`<a href="${nbHash(ctx.id,h.relpath)}">${a||t}</a>`:`<span class="nb-missing" title="No such note">${a||t}</span>`})
    .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g,(_,t,h)=>{const l=nbLink(un(h),ctx);
      return`<a href="${esc(l.href)}"${l.ext?' target="_blank" rel="noopener"':''}>${t}</a>`})
    .replace(/(^|[\s(])(https?:\/\/[^\s<)]+)/g,(_,a,u)=>`${a}<a href="${u}" target="_blank" rel="noopener">${u}</a>`)
    .replace(/\*\*([^*\n]+)\*\*/g,'<b>$1</b>').replace(/__([^_\n]+)__/g,'<b>$1</b>')
    .replace(/(^|[^*\w])\*([^*\n]+)\*(?!\*)/g,'$1<i>$2</i>').replace(/(^|[^_\w])_([^_\n]+)_(?!\w)/g,'$1<i>$2</i>')
    .replace(/~~([^~\n]+)~~/g,'<s>$1</s>').replace(/==([^=\n]+)==/g,'<mark>$1</mark>')
    .replace(/(^|\s)#([a-zA-ZáéíóúñÁÉÍÓÚÑ][\w/-]*)/g,'$1<span class="nb-chip tag">#$2</span>');
  return s.replace(/\u0000(\d+)\u0000/g,(_,k)=>`<code>${code[k]}</code>`);
}
const NB_CALLOUT={note:'Note',info:'Info',tip:'Tip',hint:'Tip',important:'Important',warning:'Warning',
  caution:'Caution',danger:'Danger',error:'Error',bug:'Bug',example:'Example',quote:'Quote',question:'Question',
  success:'Done',check:'Done',todo:'To do',abstract:'Summary',summary:'Summary',failure:'Failure'};
function nbMd(src,ctx){
  const L=String(src).split('\n'), out=[]; let i=0;
  const isBlank=l=>!l.trim();
  while(i<L.length){
    const l=L[i];
    const fence=l.match(/^\s*(```+|~~~+)\s*([\w-]*)/);
    if(fence){const lang=fence[2].toLowerCase(), body=[]; i++;
      while(i<L.length&&!L[i].trim().startsWith(fence[1]))body.push(L[i++]); i++;
      const code=body.join('\n');
      if(lang==='mermaid')out.push(`<span class="fig pending" data-mermaid="${esc(code)}" data-zoom>drawing diagram…</span>`);
      else if(lang==='svg')out.push(figImg('data:image/svg+xml;charset=utf-8,'+encodeURIComponent(code),''));
      else out.push(codeBox(lang,code));
      continue}
    if(isBlank(l)){i++;continue}
    const h=l.match(/^(#{1,6})\s+(.*?)\s*#*\s*$/);
    if(h){const n=Math.min(h[1].length+1,5);out.push(`<h${n}>${nbInline(h[2],ctx)}</h${n}>`);i++;continue}
    if(/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(l)){out.push('<hr>');i++;continue}
    const im=l.match(/^\s*!\[([^\]]*)\]\(([^)\s]+)\)\s*$/)||l.match(/^\s*!\[\[([^\]|]+)()\]\]\s*$/);
    if(im){const u=nbImgSrc(im[2]||im[1],ctx);
      out.push(u?`<span class="fig nb-fig" data-zoom><img src="${esc(u)}" alt="${esc(im[1])}" loading="lazy">${im[1]&&im[2]?`<span class="cap">${esc(im[1])}</span>`:''}</span>`
        :`<p class="nb-missing">[external image: ${esc(im[1])}]</p>`);i++;continue}
    if(/^\s*>/.test(l)){const q=[];while(i<L.length&&/^\s*>/.test(L[i]))q.push(L[i++].replace(/^\s*>\s?/,''));
      const co=q[0]&&q[0].match(/^\[!(\w+)\][+-]?\s*(.*)$/);
      if(co){const k=co[1].toLowerCase();
        out.push(`<div class="nb-callout c-${esc(k)}"><b>${nbInline(co[2]||NB_CALLOUT[k]||co[1],ctx)}</b>${nbMd(q.slice(1).join('\n'),{...ctx,off:null})}</div>`)}
      else out.push(`<blockquote>${nbMd(q.join('\n'),{...ctx,off:null})}</blockquote>`);
      continue}
    if(/^\s*\|.*\|\s*$/.test(l)){const t=[];while(i<L.length&&/^\s*\|.*\|\s*$/.test(L[i]))t.push(L[i++].trim());
      const rows=t.filter(r=>!/^\|[\s:|-]+\|?$/.test(r)).map(r=>r.replace(/^\||\|$/g,'').split('|').map(c=>c.trim()));
      out.push('<div class="nb-table"><table>'+rows.map((r,j)=>'<tr>'+r.map(c=>j?`<td>${nbInline(c,ctx)}</td>`:`<th>${nbInline(c,ctx)}</th>`).join('')+'</tr>').join('')+'</table></div>');
      continue}
    const LI=/^(\s*)([-*+]|\d+[.)])\s+(.*)$/;
    if(LI.test(l)){
      // nested lists by indentation; checkboxes remember their line so they can be ticked
      const stack=[]; let html='';
      while(i<L.length&&(LI.test(L[i])||(!isBlank(L[i])&&/^\s{2,}\S/.test(L[i])&&stack.length))){
        const m=L[i].match(LI);
        if(!m){html+=' '+nbInline(L[i].trim(),ctx);i++;continue}
        const ind=m[1].replace(/\t/g,'    ').length, ord=/\d/.test(m[2]);
        while(stack.length&&ind<stack.at(-1).ind){html+=`</li></${stack.pop().tag}>`}
        if(!stack.length||ind>stack.at(-1).ind){const tag=ord?'ol':'ul';stack.push({ind,tag});html+=`<${tag}>`}
        else html+='</li>';
        const cb=m[3].match(/^\[([ xX])\]\s+(.*)$/);
        if(cb){const ro=ctx.off==null||ctx.ro;
          html+=`<li class="nb-li-task${cb[1]!==' '?' done':''}"><label><input type="checkbox" class="nb-task"${cb[1]!==' '?' checked':''}${ro?' disabled':''}
            data-id="${esc(ctx.id)}" data-relpath="${esc(ctx.relpath||'')}" data-line="${(ctx.off||0)+i}" data-mtime="${ctx.mtime||0}"><span>${nbInline(cb[2],ctx)}</span></label>`}
        else html+=`<li>${nbInline(m[3],ctx)}`;
        i++;
        if(i<L.length&&isBlank(L[i])&&i+1<L.length&&LI.test(L[i+1]))i++;   // "loose" list
      }
      while(stack.length)html+=`</li></${stack.pop().tag}>`;
      out.push(html);continue}
    const p=[];
    while(i<L.length&&!isBlank(L[i])&&!/^(\s*(```|~~~|#{1,6}\s|>|\|)|\s*([-*+]|\d+[.)])\s+|\s*(-{3,}|\*{3,})\s*$)/.test(L[i]))p.push(L[i++]);
    if(!p.length){p.push(L[i++])}
    out.push(`<p>${p.map(x=>nbInline(x,ctx)).join('<br>')}</p>`);
  }
  return out.join('');
}

/* ---------------- actions ---------------- */
function nbForm(title,body,okLabel,onOk){
  const d=dialog(`<h3>${esc(title)}</h3><div class="form nb-form">${body}</div>
    <div class="acts"><button class="btn ghost" data-v="0" type="button">Cancel</button><button class="btn primary" data-v="1" type="button">${esc(okLabel)}</button></div>`);
  const first=d.querySelector('input,textarea,select'); if(first)first.focus();
  const ok=async()=>{const r=await onOk(d);if(r!==false)d.close()};
  d.querySelector('[data-v="1"]').onclick=ok; d.querySelector('[data-v="0"]').onclick=()=>d.close();
  d.querySelectorAll('input').forEach(x=>x.onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();ok()}});
  return d;
}
const nbTags=s=>s.split(',').map(t=>t.trim().replace(/^#/,'')).filter(Boolean);

function newNotebook(){
  const repos=META.projects.map(p=>`<label class="nb-chk"><input type="checkbox" value="${esc(p.id)}"> ${esc(p.id)}</label>`).join('');
  nbForm('New notebook',`
    <label for="nf-t">Title</label><input class="art-q" id="nf-t" placeholder="Azure platform, Learning Kubernetes…">
    <label for="nf-r">Goal in one sentence</label><input class="art-q" id="nf-r" placeholder="What you want to achieve or understand">
    <label for="nf-g">Tags</label><input class="art-q" id="nf-g" placeholder="azure, networking">
    ${repos?`<label>Related repos <span class="nb-hint">(the notebook's agents will get access)</span></label><div class="nb-chks">${repos}</div>`:''}`,
  'Create',async d=>{
    const title=$('#nf-t').value.trim(); if(!title){toast('Give it a title',true);return false}
    const r=await api('/api/notebook/create',{title,summary:$('#nf-r').value.trim(),tags:nbTags($('#nf-g').value),
      repos:[...d.querySelectorAll('.nb-chks input:checked')].map(x=>x.value)});
    if(!r.ok){toast(r.err||'Could not create',true);return false}
    await loadMeta(); await renderNb(true); location.hash=nbHash(r.id);
  });
}
function folderOpts(sel){
  return nbFolders(NB.c.tree).map(r=>`<option value="${esc(r)}"${r===sel?' selected':''}>${r?esc(r):'(notebook root)'}</option>`).join('');
}
function newNote(){
  const c=NB.c, curDir=NB.relpath?nbDir(NB.relpath):'';
  nbForm('New note',`
    <label for="nn-t">Title</label><input class="art-q" id="nn-t" placeholder="How the firewall routes">
    <label for="nn-k">Type</label><select class="sel" id="nn-k">${Object.entries(NB.kinds).filter(([k])=>!['notebook','status','folder'].includes(k))
      .map(([k,v])=>`<option value="${k}"${k==='note'?' selected':''}>${esc(NB_KIND[k]||k)} — ${esc(v)}</option>`).join('')}</select>
    <label for="nn-c">Folder</label><select class="sel" id="nn-c">${folderOpts(curDir)}</select>
    <label for="nn-r">Summary in one sentence</label><input class="art-q" id="nn-r">
    <label for="nn-g">Tags</label><input class="art-q" id="nn-g" placeholder="networking, firewall">`,
  'Create',async()=>{
    const title=$('#nn-t').value.trim(); if(!title){toast('Give it a title',true);return false}
    const r=await api('/api/notebook/note/new',{id:c.id,folder:$('#nn-c').value,title,kind:$('#nn-k').value,
      summary:$('#nn-r').value.trim(),tags:nbTags($('#nn-g').value)});
    if(!r.ok){toast(r.err||'Could not create',true);return false}
    NB.editOnOpen=r.relpath; await loadNotebook(true); location.hash=nbHash(c.id,r.relpath);
  });
}
function newFolder(){
  const c=NB.c;
  nbForm('New folder',`<p class="nb-hint">A project or topic inside the notebook. It gets its own README.md with metadata.</p>
    <label for="nc-p">Inside</label><select class="sel" id="nc-p">${folderOpts(NB.relpath?nbDir(NB.relpath):'')}</select>
    <label for="nc-t">Name</label><input class="art-q" id="nc-t" placeholder="Hub & spoke network">
    <label for="nc-r">What it is for</label><input class="art-q" id="nc-r">`,
  'Create',async()=>{
    const t=$('#nc-t').value.trim(); if(!t){toast('Give it a name',true);return false}
    const r=await api('/api/notebook/folder',{id:c.id,relpath:[$('#nc-p').value,t].filter(Boolean).join('/'),title:t,summary:$('#nc-r').value.trim()});
    if(!r.ok){toast(r.err||'Could not create',true);return false}
    await loadNotebook(true); location.hash=nbHash(c.id,r.relpath+'/README.md');
  });
}
async function deleteNote(){
  const n=NB.note;
  if(!await confirmBox('Delete note',`"${n.info?.title||n.relpath}" goes to the notebooks trash (notebooks/.trash). If it just no longer applies, better mark it as archived.`))return;
  const r=await api('/api/notebook/delete',{id:NB.c.id,relpath:n.relpath});
  if(!r.ok)return toast('Could not delete',true);
  toast('Moved to the trash'); location.hash=nbHash(NB.c.id); loadNotebook(true);
}
async function historyNote(){
  const n=NB.note;
  await api('/api/notebooks/autosave',{}).catch(()=>{});   // the latest changes count too
  const h=await api(`/api/notebook/history?id=${encodeURIComponent(NB.c.id)}&relpath=${encodeURIComponent(n.relpath)}`).catch(()=>[]);
  const d=dialog(`<h3>History</h3><p>Gatito saves a copy of the notebooks every few minutes if anything changed.</p>
    <div class="nb-hlist">${h.map((v,k)=>`<button class="nb-row" type="button" data-h="${esc(v.hash)}"${k===0?' disabled':''}>
      ${ICON('clock')}<span class="nb-rt">${esc(v.date)}</span><span class="nb-ty">${k===0?'current':esc(v.hash)}</span></button>`).join('')||'<p class="nb-empty">No saved versions yet.</p>'}</div>
    <div class="acts"><button class="btn ghost" data-v="0">Close</button></div>`);
  d.querySelector('[data-v="0"]').onclick=()=>d.close();
  d.querySelectorAll('[data-h]').forEach(b=>b.onclick=()=>{d.close();NB.ver=b.dataset.h;NB.note=null;renderNbMain()});
}
async function restore(){
  const old=NB.note;
  const cur=await api(`/api/notebook/note?id=${encodeURIComponent(NB.c.id)}&relpath=${encodeURIComponent(old.relpath)}`);
  const r=await api('/api/notebook/note/save',{id:NB.c.id,relpath:old.relpath,text:old.text,mtime:cur.mtime});
  if(!r.ok)return toast('Could not restore: '+(r.err||''),true);
  toast('Restored'); NB.ver=null; NB.note=null; await loadNotebook(true); renderNbMain();
}

/* open a notebook session in the Sessions view */
function openSession(s){
  if(!s)return;
  location.hash='#/';
  setTimeout(()=>{
    const a=AGENTS.find(x=>x.sessionId===s.sid)||(s.agent&&AGENTS.find(x=>x.key===s.agent));
    if(a)return select(a.key);
    if(!s.transcript)return toast('That conversation has no history yet',true);
    const it=histItem(s); if(!HIST.items.some(x=>x.key===it.key))HIST.items.push(it);
    select(it.key);
  },50);
}
/* new session with the chosen notebook as project: the agent works in its folder */
function sessionInNb(text){
  const c=NB.c; if(!c)return;
  const pid='nb:'+c.id;
  // a notebook the composer does not know yet (created after the page loaded, e.g. by an
  // agent): without its option the selector stayed on "Auto" and the router opened a plain chat
  if(!(META.notebooks||[]).some(p=>p.id===pid))
    syncNotebooks([...(NB.listing||[]).filter(x=>x.id!==c.id),{id:c.id,relpath:c.relpath,title:c.title}]);
  location.hash='#/';
  setTimeout(()=>{
    closeDetail();
    const sel=$('#q-proj');
    if(![...sel.options].some(o=>o.value===pid))return toast(`The notebook "${c.title}" is not in the project list: reload the page`,true);
    sel.value=pid;
    if($('#q-wt').getAttribute('aria-pressed')==='true')setWt(false);  // notebooks/ never uses worktrees
    if(text){q.value=text;autosize(q)}
    q.focus(); toast(`Will launch in the notebook "${c.title}"`);
  },50);
}
