/* Utilities shared by all views: global state, API, markdown,
   diagrams, dialogs and the backlog vocabulary. Loaded first. */
const $=s=>document.querySelector(s);
const ICON=n=>`<svg class="i"><use href="#i-${n}"/></svg>`;
let META={projects:[],actions:[],models:[],modes:[],efforts:[],defaults:{model:'sonnet',mode:'auto'}}, AGENTS=[], CUR=null, LAST_OK=0;
/* model / permission / effort options: they come from /api/meta (core.py) */
const OPT={models:['Model: ','Model: auto'],modes:['Permissions: ',null],efforts:['Effort: ','Effort: normal']};
function selOpts(kind,cur,blank=OPT[kind][1],pre=OPT[kind][0]){
  const list=(META[kind]||[]).map(x=>typeof x==='string'?{id:x,label:x}:x);
  if(cur&&!list.some(x=>x.id===cur))list.push({id:cur,label:cur});
  return (blank!=null?`<option value="">${esc(blank)}</option>`:'')+list.map(x=>
    `<option value="${esc(x.id)}"${x.id===cur?' selected':''}${x.hint?` title="${esc(x.hint)}"`:''}>${esc(pre+x.label)}</option>`).join('');
}
function label(kind,id){const x=(META[kind]||[]).find(x=>(x.id||x)===id);return x?(x.label||x):id}
/* task profiles (profiles/*.md, come in /api/meta): how the agent works and what it can touch */
const profileFor=id=>(META.profiles||[]).find(p=>p.id===id);
function profileOpts(cur,blank='Profile: none',pre='Profile: '){
  return `<option value="">${esc(blank)}</option>`+(META.profiles||[]).map(p=>
    `<option value="${esc(p.id)}"${p.id===cur?' selected':''} title="${esc(p.description)}">${esc(pre+p.title)}${p.read_only?' · read-only':''}</option>`).join('');
}
function setSel(el,v){
  if(!el||v==null)return;
  if(![...el.options].some(o=>o.value===v))el.insertAdjacentHTML('beforeend',`<option value="${esc(v)}">${esc(v)}</option>`);
  el.value=v;
}
// When a profile is chosen, the selectors show its values and can be changed; in a
// read-only one the mode is fixed to "Don't ask" (the server enforces it anyway).
function applyProfile(id,{model,mode,effort,wt}={},fill=true){
  const p=profileFor(id);
  if(p&&fill){setSel(model,p.model);setSel(mode,p.mode);setSel(effort,p.effort);if(wt)wt(!!p.worktree)}
  if(!mode)return;
  const lock=!!(p&&p.read_only);
  if(lock)setSel(mode,'dontAsk');
  mode.disabled=lock;
  mode.title=lock?`${p.title}: read-only, the mode can't be raised`:'Permission mode';
}
// profile tag in the list, the card and the detail
function profileTag(id,title,ro,link){
  if(!id)return'';
  const t=title||profileFor(id)?.title||id, read=ro??profileFor(id)?.read_only;
  const tag=link?'a':'span', href=link?` href="#/profiles/${encodeURIComponent(id)}"`:'';
  return `<${tag} class="pf${read?' ro':''}"${href} title="Profile "${esc(t)}"${read?': read-only':''}${link?' (see inside)':''}">${esc(t)}</${tag}>`;
}
function store(k,v){try{v==null?localStorage.removeItem(k):localStorage.setItem(k,v)}catch(e){}}
function stored(k){try{return localStorage.getItem(k)}catch(e){return null}}
let CONVO={key:null,msgs:[],showAll:false};
let BACKLOG=[];  // all backlog tasks, including already launched ones (?all=1)

/* ---------------- util ---------------- */
function tok(){const m=document.cookie.match(/gatito=([^;]+)/);return m?m[1]:''}
async function api(path,body){
  const opts={headers:{'X-Gatito-Token':tok()}};
  if(body!==undefined){opts.method='POST';opts.body=JSON.stringify(body);
    opts.headers['Content-Type']='application/json'}
  const r=await fetch(path,opts);
  if(r.status===401){setConn('off','not paired');$('#unpaired').hidden=false;throw new Error('401')}
  return r.json();
}
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function toast(t,err){const e=$('#toast');e.textContent=t;e.classList.toggle('err',!!err);
  e.classList.add('show');clearTimeout(e._t);e._t=setTimeout(()=>e.classList.remove('show'),2800)}
function ago(ms){
  if(!ms)return'';const s=(Date.now()-ms)/1000;
  if(s<60)return'now';if(s<3600)return`${Math.floor(s/60)} min ago`;
  if(s<86400)return`${Math.floor(s/3600)} h ago`;
  const d=Math.floor(s/86400);return d===1?'yesterday':`${d} days ago`;
}
function proj(a){
  // in a worktree the cwd is <repo>/.claude/worktrees/<name>: show the repo
  const c=(a.cwd||'').split('/.claude/worktrees/')[0];
  return (c.split('/').filter(Boolean).pop()||c)+(a.worktreeBranch?' · worktree':'');
}
function home(p){return(p||'').replace(/^\/home\/[^/]+/,'~')}
function setConn(cls,t){
  if(cls==='on')$('#unpaired').hidden=true;
  $('#conn').className='conn '+cls; $('#conn').title=t;
  const ct=$('#conn-t'); ct.textContent=cls==='on'?'':t; ct.classList.toggle('off',cls==='off');
}
function autosize(t){t.style.height='auto';t.style.height=Math.min(t.scrollHeight,200)+'px'}
function inline(s){return esc(s).replace(/`([^`\n]+)`/g,'<code>$1</code>').replace(/\*\*([^*\n]+)\*\*/g,'<b>$1</b>')}
function fileUrl(p){return'/api/file?path='+encodeURIComponent(p)}
function figImg(src,cap){return`<span class="fig" data-zoom><img src="${esc(src)}" alt="${esc(cap)}" loading="lazy">${cap?`<span class="cap">${esc(cap)}</span>`:''}</span>`}
function mdText(p){
  const out=[];let tbl=[];
  const flush=()=>{if(!tbl.length)return;
    const rows=tbl.filter(r=>!/^\|[\s:|-]+\|?$/.test(r)).map(r=>r.replace(/^\||\|$/g,'').split('|').map(c=>c.trim()));
    out.push('<table>'+rows.map((r,j)=>'<tr>'+r.map(c=>j?`<td>${inline(c)}</td>`:`<th>${inline(c)}</th>`).join('')+'</tr>').join('')+'</table>');
    tbl=[]};
  for(const line of p.split('\n')){
    if(/^\s*\|.*\|\s*$/.test(line)){tbl.push(line.trim());continue}
    flush();
    const img=line.match(/^\s*!\[([^\]]*)\]\(([^)\s]+)\)\s*$/);
    // a saved artifact: images show inline (with a link), the rest is a card
    const ar=img&&typeof artRef==='function'&&artRef(img[2]);
    if(ar){out.push(artEsImg(ar.f)
      ?`<span class="fig" data-zoom><img src="${esc(artUrl(ar.id,ar.v,ar.f))}" alt="${esc(img[1])}" loading="lazy"><span class="cap">${esc(img[1]||ar.id)} · <a href="#/artifacts/${esc(ar.id)}" onclick="event.stopPropagation()">in Artifacts</a></span></span>`
      :artChatCard(ar,img[1]));continue}
    if(img&&/\.(svg|png|jpe?g|gif|webp)$/i.test(img[2])&&/^(\/|~)/.test(img[2])){out.push(figImg(fileUrl(img[2]),img[1]||img[2]));continue}
    const h=line.match(/^#{1,6}\s+(.*)/);
    if(h){out.push(`<span class="mh">${inline(h[1])}</span>`);continue}
    if(/^\s*(-{3,}|\*{3,})\s*$/.test(line)){out.push('<hr>');continue}
    out.push(inline(line)+'\n');
  }
  flush();return out.join('').replace(/\n(<table)/g,'$1').replace(/\n{3,}/g,'\n\n');
}
function md(s){
  // minimal markdown: code, mermaid, svg, images, tables, headings and bold
  s=String(s); const out=[]; let last=0, m;
  const re=/```([\w-]*)[^\n]*\n([\s\S]*?)(?:```|$)/g;
  while((m=re.exec(s))){
    out.push(mdText(s.slice(last,m.index))); last=re.lastIndex;
    const lang=m[1].toLowerCase(), code=m[2].replace(/\n$/,'');
    if(lang==='mermaid')out.push(`<span class="fig pending" data-mermaid="${esc(code)}" data-zoom>drawing diagram…</span>`);
    else if(lang==='svg'||(lang==='xml'&&/^\s*<svg[\s>]/.test(code)))
      out.push(figImg('data:image/svg+xml;charset=utf-8,'+encodeURIComponent(code),''));
    else out.push(codeBox(lang,code));
  }
  out.push(mdText(s.slice(last)));
  return out.join('');
}

// a code block with its header: the language and a copy button
const SHELL=new Set(['','bash','sh','shell','zsh','console','terminal']);
function codeBox(lang,code){
  const sh=SHELL.has(lang)&&!!code.trim();
  return `<div class="code${sh?' sh':''}" data-copy title="Click to copy">
    <div class="code-h"><span>${esc(lang||(sh?'bash':''))}</span>
    <button class="code-cp" type="button" aria-label="Copy">${ICON('copy')}<span>Copy</span></button></div>
    <pre><code>${esc(code)}</code></pre></div>`;
}
// what gets copied is the command, without the "$ " prompt
function copyText(box){
  const t=box.querySelector('code').textContent, ls=t.split('\n');
  return ls.filter(l=>l.trim()).every(l=>/^\$ /.test(l))?ls.map(l=>l.replace(/^\$ /,'')).join('\n'):t;
}
async function copy(t){
  try{await navigator.clipboard.writeText(t);return true}catch{}
  // no clipboard without HTTPS: the usual trick
  const a=document.createElement('textarea'); a.value=t; a.style.cssText='position:fixed;opacity:0';
  document.body.append(a); a.select(); const ok=document.execCommand('copy'); a.remove(); return ok;
}
function wireCopy(root){
  root.querySelectorAll('[data-copy]').forEach(box=>box.onclick=async e=>{
    // if you're selecting some text, leave it alone
    if(!e.target.closest('.code-cp')&&String(getSelection()).trim())return;
    const ok=await copy(copyText(box)), b=box.querySelector('.code-cp span');
    box.classList.toggle('copied',ok); b.textContent=ok?'Copied':'Could not copy';
    clearTimeout(box._t); box._t=setTimeout(()=>{box.classList.remove('copied');b.textContent='Copy'},1600);
  });
}

/* ---------------- diagrams ---------------- */
let MERMAID=null; const SVG_CACHE=new Map(); let MID=0;
function loadMermaid(){
  if(!MERMAID)MERMAID=new Promise((res,rej)=>{
    const sc=document.createElement('script'); sc.src='/vendor/mermaid.min.js?v=11.4.1-p1'; // ?v: vendor is served with a long cache; bump it when it changes
    sc.onload=()=>{
      mermaid.initialize({startOnLoad:false,securityLevel:'strict',theme:'base',
        fontFamily:'Figtree,system-ui,sans-serif',
        themeVariables:{darkMode:true,background:'#11111b',primaryColor:'#313244',
          primaryTextColor:'#cdd6f4',primaryBorderColor:'#cba6f7',lineColor:'#a6adc8',
          secondaryColor:'#45475a',tertiaryColor:'#1e1e2e',noteBkgColor:'#45475a',
          noteTextColor:'#cdd6f4',clusterBkg:'#181825',clusterBorder:'#585b70',
          edgeLabelBackground:'#1e1e2e',actorBkg:'#313244',actorBorder:'#cba6f7',
          actorTextColor:'#cdd6f4',signalColor:'#a6adc8',signalTextColor:'#cdd6f4'}});
      res(window.mermaid)};
    sc.onerror=rej; document.head.appendChild(sc);
  });
  return MERMAID;
}
function tidy(src){
  // in sequenceDiagram quotes are drawn literally: strip them
  if(!/^\s*sequenceDiagram/.test(src))return src;
  return src.replace(/^(\s*(?:participant|actor)\s+\S+\s+as\s+)"(.*)"\s*$/gm,'$1$2')
            .replace(/^(\s*[^:\n]*?:\s*)"(.*)"\s*$/gm,'$1$2');
}
async function renderDiagrams(root){
  const els=[...root.querySelectorAll('[data-mermaid]')]; if(!els.length)return;
  let mm; try{mm=await loadMermaid()}catch(e){els.forEach(el=>el.textContent='Could not load mermaid');return}
  for(const el of els){
    const src=el.dataset.mermaid; el.removeAttribute('data-mermaid');
    try{
      let svg=SVG_CACHE.get(src);
      if(!svg){svg=(await mm.render('mmd'+(++MID),tidy(src))).svg;SVG_CACHE.set(src,svg)}
      el.classList.remove('pending'); el.innerHTML=svg;
    }catch(e){
      el.classList.remove('pending'); el.classList.add('err'); el.removeAttribute('data-zoom');
      el.innerHTML=`<div class="e">The diagram has a syntax error</div><pre><code>${esc(src)}</code></pre>`;
      document.querySelectorAll('#dmmd'+MID).forEach(x=>x.remove());
    }
  }
}
function wireZoom(root){
  root.querySelectorAll('[data-zoom]').forEach(el=>el.onclick=()=>{
    if(el.classList.contains('pending')||el.classList.contains('err'))return;
    const d=$('#dlg'); d.className='lightbox';
    d.innerHTML=`<div class="lb-bar"><button class="btn ghost" id="lb-z">Enlarge</button>
      <span class="spacer"></span><button class="btn ghost" id="lb-x">Close</button></div>
      <div class="lb-body" id="lb-b">${el.innerHTML}</div>`;
    d.onclose=()=>{d.className=''};
    $('#lb-x').onclick=()=>d.close();
    $('#lb-z').onclick=()=>{const b=$('#lb-b');b.classList.toggle('zoom');
      $('#lb-z').textContent=b.classList.contains('zoom')?'Fit':'Enlarge'};
    d.showModal();
  });
}
async function enhance(root){wireCopy(root);wireZoom(root);await renderDiagrams(root);wireZoom(root)}

/* ---------------- dialogs ---------------- */
function dialog(html,cls){const d=$('#dlg');d.className=cls||'';d.innerHTML=html;d.showModal();return d}
function confirmBox(title,text,okLabel='Delete',danger=true){
  return new Promise(res=>{
    const d=dialog(`<h3>${esc(title)}</h3><p>${esc(text)}</p><div class="acts">
      <button class="btn ghost" data-v="0">Cancel</button>
      <button class="btn ${danger?'danger':'primary'}" data-v="1">${esc(okLabel)}</button></div>`);
    d.querySelectorAll('button').forEach(b=>b.onclick=()=>{d.close();res(b.dataset.v==='1')});
    d.onclose=()=>res(false);
  });
}


/* ---------------- backlog: shared vocabulary ---------------- */
const WHEN_TXT={manual:'To do',queue:'Queued',at:'Scheduled'};
const REPEAT_TXT={'':'Once',daily:'Every day',weekdays:'Monday to Friday',weekly:'Every week'};
function repeatOpts(cur){return Object.entries(REPEAT_TXT).map(([v,t])=>
  `<option value="${v}"${v===(cur||'')?' selected':''}>${t}</option>`).join('')}
function localInput(ms){const d=new Date(ms-new Date(ms).getTimezoneOffset()*60000);return d.toISOString().slice(0,16)}
function nextHour(){const d=new Date();d.setMinutes(0,0,0);d.setHours(d.getHours()+1);return d.getTime()}
function when(i){
  if(i.trigger==='queue')return i.status==='pending'?`Queued #${i.queue_pos}`:'Queue';
  if(i.trigger==='manual')return'When you say';
  const d=new Date(i.at), t=d.toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit'});
  const day=Math.round((new Date(d).setHours(0,0,0,0)-new Date().setHours(0,0,0,0))/86400000);
  const dd=day===0?'today':day===1?'tomorrow':d.toLocaleDateString('en-GB',{weekday:'short',day:'numeric',month:'short'});
  return `${dd} ${t}`+(i.repeat?` · ${REPEAT_TXT[i.repeat].toLowerCase()}`:'');
}

// each project always has the same color, in every view
const PCOLORS=['mauve','peach','teal','sky','pink','green','yellow','lavender','flamingo','sapphire','maroon','rosewater'];
function projColor(id){
  // by its position in the project list (no repeats until the 13th); if absent, by hash
  let k=META.projects.findIndex(p=>p.id===id);
  if(k<0){k=0;for(const c of String(id||''))k=(k*31+c.charCodeAt(0))>>>0}
  return `var(--${PCOLORS[k%PCOLORS.length]})`;
}
// "no project": each task in its own new folder (gatito creates it on launch)
const FREE={id:'free',path:null};
// a notebook also works as a project ("nb:<id>"): the agent works in its folder
const projOf=id=>id===FREE.id?FREE:META.projects.find(p=>p.id===id)||(META.notebooks||[]).find(p=>p.id===id);
const pname=id=>id===FREE.id?'no project':((META.notebooks||[]).find(p=>p.id===id)||{}).label||id;
const freeOpt=sel=>`<option value="${FREE.id}"${sel===FREE.id?' selected':''}>No project (new folder)</option>`;
function pdot(id){return `<i class="pdot" style="--pc:${projColor(id)}"></i>`}
function hm(ms){return new Date(ms).toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit'})}
function firstLine(t){return String(t||'').split('\n')[0]}
// session from a task's latest launch (if still in the list)
function agentOf(i){const r=(i.runs||[]).at(-1);return r&&r.agent_id?AGENTS.find(a=>a.id===r.agent_id):null}
