/* Block editor for notebook notes (nb.js calls it from "Edit").
   The body of a note is split into blocks — text (any Markdown: paragraphs, headings,
   lists, tables, quotes), code, mermaid diagram and image — that can be edited one by one,
   dragged (or moved with the arrows / Alt+↑↓), duplicated and deleted. The metadata is a
   form on top. What gets saved is plain Markdown again: the note still opens the same in
   Obsidian and agents still read and write it the same.
   Also here: export a note to PDF (the browser's print dialog, "Save as PDF"). */

let ED=null;   // {relpath, meta, blocks:[{id,t,src,lang,alt,wiki,fence,indent}], ini, active, mode, undo:[]}
let ED_ID=0;

/* ---------------- Markdown <-> blocks ---------------- */
const ED_IMG=/^\s*!\[([^\]]*)\]\(([^)\s]+)(?:\s+"[^"]*")?\)\s*$/, ED_WIKI=/^\s*!\[\[([^\]|]+)(?:\|[^\]]*)?\]\]\s*$/;
function edBlock(t,o={}){return{id:++ED_ID,t,src:'',...o}}
function edParse(body){
  const L=String(body).replace(/\r\n/g,'\n').split('\n'), out=[]; let txt=[];
  const flush=()=>{let cur=[];
    for(const l of [...txt,'']){if(l.trim())cur.push(l);else if(cur.length){out.push(edBlock('text',{src:cur.join('\n')}));cur=[]}}
    txt=[]};
  for(let i=0;i<L.length;i++){
    const l=L[i], f=l.match(/^(\s*)(```+|~~~+)\s*([\w-]*)\s*$/);
    if(f){flush(); const body=[]; i++;
      while(i<L.length&&!(L[i].trim().startsWith(f[2])&&!L[i].trim().slice(f[2].length).trim()))body.push(L[i++]);
      const ind=f[1], lang=f[3];
      const src=body.map(x=>x.startsWith(ind)?x.slice(ind.length):x).join('\n');
      out.push(edBlock(lang.toLowerCase()==='mermaid'?'mermaid':'code',{src,lang,fence:f[2],indent:ind}));
      continue}
    const im=l.match(ED_IMG), wk=!im&&l.match(ED_WIKI);
    if(im||wk){flush(); out.push(edBlock('img',im?{alt:im[1],src:im[2]}:{alt:'',src:wk[1],wiki:true})); continue}
    txt.push(l);
  }
  flush();
  return out;
}
function edMd(b){
  if(b.t==='code'||b.t==='mermaid'){
    const fence=b.fence||'```', ind=b.indent||'', lang=b.t==='mermaid'?'mermaid':(b.lang||'').trim();
    let f=fence; while(b.src.includes(f))f+=fence[0];   // a fence inside the code: one tick more
    return [f+lang,...b.src.split('\n'),f].map(x=>x?ind+x:x).join('\n');
  }
  if(b.t==='img')return b.wiki&&!b.alt?`![[${b.src}]]`:`![${(b.alt||'').replace(/[\[\]\n]/g,' ')}](${String(b.src).replace(/ /g,'%20')})`;
  return b.src.replace(/\s+$/,'').replace(/\n\s*\n/g,'\n\n');
}
function edBody(){return '\n'+ED.blocks.map(edMd).filter(x=>x.trim()).join('\n\n')+'\n'}
function edMeta(){
  const f=id=>{const e=document.getElementById(id);return e?e.value.trim():''};
  const m={...ED.meta};
  const pon=(k,v)=>{if(v||k in m)m[k]=v};
  pon('title',f('ede-title')); pon('summary',f('ede-summary'));
  if(f('ede-kind'))m.kind=f('ede-kind'); if(f('ede-status'))m.status=f('ede-status');
  const tags=f('ede-tags').split(/[,\s]+/).map(t=>t.replace(/^#/,'')).filter(Boolean);
  if(tags.length||'tags' in m)m.tags=tags;
  return Object.values(m).some(v=>Array.isArray(v)?v.length:v)?m:{};
}
function edSignature(){return JSON.stringify([edMeta(),ED.mode==='md'?$('#ede-md').value:edBody()])}
function edDirty(){return !!ED&&!!$('#nbe')&&edSignature()!==ED.ini}

/* ---------------- render ---------------- */
const ED_GRIP='<svg class="i" viewBox="0 0 24 24"><g fill="currentColor" stroke="none"><circle cx="9" cy="6" r="1.6"/><circle cx="15" cy="6" r="1.6"/><circle cx="9" cy="12" r="1.6"/><circle cx="15" cy="12" r="1.6"/><circle cx="9" cy="18" r="1.6"/><circle cx="15" cy="18" r="1.6"/></g></svg>';
const ED_KINDS=[
  ['text','Text','Paragraph in Markdown'],['h2','Heading','## Section'],['list','List','- item'],
  ['check','Checklist','- [ ] task'],['quote','Quote','> text'],['callout','Callout','> [!note]'],
  ['table','Table','| a | b |'],['code','Code','```lang'],['mermaid','Diagram','mermaid'],
  ['img','Image','upload, paste or drop'],['hr','Divider','---']];
const ED_INI={text:'',h2:'## ',list:'- ',check:'- [ ] ',quote:'> ',callout:'> [!note] Note\n> ',
  table:'| Column | Column |\n|---|---|\n|  |  |',hr:'---'};

function edCtx(){return{id:NB.c.id,dir:nbDir(ED.relpath),off:null,relpath:ED.relpath,ro:true}}
function renderBlocks(n){
  const m=$('#nb-main'), meta=n.meta||{}, c=NB.c;
  ED={relpath:n.relpath,meta:{...meta},blocks:edParse(n.body),active:null,mode:'blocks',undo:[],mtime:n.mtime};
  const kinds=Object.keys(NB.kinds||{}).length?Object.keys(NB.kinds):Object.keys(NB_KIND);
  const sel=(id,vals,cur,lbl)=>`<select class="sel" id="${id}"><option value="">—</option>${vals.map(v=>
    `<option value="${esc(v)}"${v===cur?' selected':''}>${esc(lbl[v]||v)}</option>`).join('')}</select>`;
  m.innerHTML=`<article class="nb-doc nb-editing" id="nbe">
    <div class="nb-bar"><div class="nb-crumb">Editing ${esc(n.relpath)}</div><span class="spacer"></span>
      <div class="nbe-mode" role="group" aria-label="Editor mode">
        <button class="on" data-mode="blocks" type="button">Blocks</button><button data-mode="md" type="button">Markdown</button></div>
      <button class="btn ghost icon" id="ede-undo" title="Undo (Ctrl+Z)" aria-label="Undo" disabled>${ICON('restore')}</button>
      <button class="btn ghost" id="ede-pdf" title="Export what you see to PDF">${ICON('download')}<span class="nb-lbl">PDF</span></button>
      <button class="btn ghost" id="nb-cancel">Cancel</button>
      <button class="btn primary" id="nb-save">Save</button></div>
    <input class="nbe-title" id="ede-title" placeholder="Title" value="${esc(meta.title||'')}">
    <details class="nbe-meta"${meta.title?'':' open'}><summary>Metadata</summary>
      <div class="nbe-grid">
        <label>Type${sel('ede-kind',kinds,meta.kind,NB_KIND)}</label>
        <label>State${sel('ede-status',NB.statuses.length?NB.statuses:Object.keys(NB_STATUS),meta.status,NB_STATUS)}</label>
        <label class="w2">Tags<input class="art-q" id="ede-tags" value="${esc((meta.tags||[]).join(', '))}" placeholder="tag, other"></label>
        <label class="w4">Summary<input class="art-q" id="ede-summary" value="${esc(meta.summary||'')}" placeholder="One line: what this note is"></label>
      </div></details>
    <div class="nbe-list" id="ede-list"></div>
    <textarea id="ede-md" class="nb-ed" spellcheck="true" hidden></textarea>
    <p class="nb-hint nbe-help">Click a block to edit it · drag ${ED_GRIP} or Alt+↑↓ to move it · Enter on an empty line starts a new block ·
      paste or drop an image · Esc closes the block · Ctrl+S saves</p>
    <input type="file" id="ede-file" accept="image/png,image/jpeg,image/webp,image/gif" hidden multiple>
  </article>`;
  edDraw();
  ED.ini=edSignature();
  const root=$('#nbe');
  root.querySelectorAll('[data-mode]').forEach(b=>b.onclick=()=>edMode(b.dataset.mode));
  $('#nb-cancel').onclick=async()=>{if(await leaveEdit()){NB.edit=false;ED=null;renderNote()}};
  $('#nb-save').onclick=()=>edSave();
  $('#ede-undo').onclick=edUndo;
  $('#ede-pdf').onclick=()=>{edClose(); nbPdf({title:edMeta().title||nbTitleOf(n),summary:edMeta().summary,
    body:ED.mode==='md'?$('#ede-md').value:edBody(),relpath:n.relpath,meta:edMeta()})};
  root.addEventListener('keydown',e=>{
    if((e.ctrlKey||e.metaKey)&&e.key==='s'){e.preventDefault();edSave()}
    else if((e.ctrlKey||e.metaKey)&&e.key==='z'&&!/^(TEXTAREA|INPUT)$/.test(e.target.tagName)){e.preventDefault();edUndo()}
    else if(e.key==='Escape'&&ED.active){e.preventDefault();e.stopPropagation();edClose()}
  });
  // a click on the empty part of the page closes the open block
  root.addEventListener('mousedown',e=>{if(ED&&ED.active&&!e.target.closest('.nbb,.nbe-add,.nbe-pop,.nb-bar,.nbe-meta,input,select'))edClose()});
  // images: dropped anywhere in the editor or chosen from the picker
  root.addEventListener('dragover',e=>{if([...e.dataTransfer.types].includes('Files')){e.preventDefault();root.classList.add('drop')}});
  root.addEventListener('dragleave',e=>{if(e.target===root)root.classList.remove('drop')});
  root.addEventListener('drop',e=>{root.classList.remove('drop');
    const fs=[...(e.dataTransfer.files||[])].filter(f=>/^image\//.test(f.type)); if(!fs.length)return;
    e.preventDefault(); const b=e.target.closest('.nbb'); edImages(fs,b?+b.dataset.b:ED.blocks.at(-1)?.id)});
  $('#ede-file').onchange=e=>{const fs=[...e.target.files]; e.target.value=''; edImages(fs,ED._afterFile)};
}
function nbTitleOf(n){return (n.info&&n.info.title)||n.relpath}

function edView(b){
  if(b.t==='text')return b.src.trim()?`<div class="nb-md">${nbMd(b.src,edCtx())}</div>`:'<p class="nbe-ph">Empty text — click to write</p>';
  if(b.t==='code')return b.src.trim()||b.lang?codeBox(b.lang,b.src):'<p class="nbe-ph">Empty code block</p>';
  if(b.t==='mermaid')return b.src.trim()?`<span class="fig pending" data-mermaid="${esc(b.src)}">drawing diagram…</span>`:'<p class="nbe-ph">Empty diagram</p>';
  if(b.t==='img'){const u=b.src&&nbImgSrc(b.src,edCtx());
    return u?`<span class="fig nb-fig"><img src="${esc(u)}" alt="${esc(b.alt||'')}">${b.alt?`<span class="cap">${esc(b.alt)}</span>`:''}</span>`
      :`<p class="nbe-ph">${b.src?'External image (not loaded): '+esc(b.src):'No image'}</p>`}
  return '';
}
const ED_TB=[['h','H','Heading'],['b','<b>B</b>','Bold (Ctrl+B)'],['i','<i>I</i>','Italic (Ctrl+I)'],['c','&lt;/&gt;','Inline code'],
  ['l','Link','Link'],['ul','• List','List'],['ck','☐ Task','Checklist'],['q','❝','Quote']];
function edEditor(b){
  if(b.t==='text')return`<div class="nbe-tb">${ED_TB.map(([k,h,t])=>`<button type="button" data-tb="${k}" title="${t}">${h}</button>`).join('')}</div>
    <textarea class="nbe-ta" spellcheck="true" placeholder="Write in Markdown…">${esc(b.src)}</textarea>
    <div class="nbe-pv nb-md"></div>`;
  if(b.t==='code')return`<div class="nbe-row"><input class="art-q nbe-lang" list="ede-langs" value="${esc(b.lang||'')}" placeholder="language (bash, python, yaml…)">
    <datalist id="ede-langs">${['bash','python','javascript','typescript','json','yaml','sql','html','css','go','rust','java','terraform','dockerfile','text'].map(l=>`<option value="${l}">`).join('')}</datalist></div>
    <textarea class="nbe-ta mono" spellcheck="false" placeholder="code…">${esc(b.src)}</textarea>`;
  if(b.t==='mermaid')return`<textarea class="nbe-ta mono" spellcheck="false" placeholder="flowchart LR&#10;  A --> B">${esc(b.src)}</textarea>
    <div class="nbe-pv"></div>`;
  if(b.t==='img')return`${edView(b)}<div class="nbe-grid">
    <label class="w2">Caption<input class="art-q nbe-alt" value="${esc(b.alt||'')}" placeholder="what it shows"></label>
    <label class="w2">File<input class="art-q nbe-src" value="${esc(b.src||'')}" placeholder="attachments/image.png"></label></div>
    <div class="nbe-row"><button class="btn ghost nbe-re" type="button">${ICON('image')}Replace image…</button></div>`;
  return '';
}
function edDraw(focus){
  const list=$('#ede-list'); if(!list)return;
  const add=id=>`<div class="nbe-add"><button type="button" data-add="${id}" title="Add a block here" aria-label="Add a block">${ICON('plus')}</button></div>`;
  list.innerHTML=add(0)+ED.blocks.map((b,k)=>`<div class="nbb t-${b.t}${ED.active===b.id?' on':''}" data-b="${b.id}">
      <div class="nbb-g"><span class="nbb-h" draggable="true" title="Drag to move">${ED_GRIP}</span></div>
      <div class="nbb-c">${ED.active===b.id?edEditor(b):edView(b)}</div>
      <div class="nbb-t">
        <button type="button" data-op="up" title="Move up (Alt+↑)" aria-label="Move up"${k?'':' disabled'}>${ICON('chev')}</button>
        <button type="button" data-op="down" title="Move down (Alt+↓)" aria-label="Move down"${k<ED.blocks.length-1?'':' disabled'}>${ICON('chev')}</button>
        <button type="button" data-op="dup" title="Duplicate" aria-label="Duplicate">${ICON('copy')}</button>
        <button type="button" data-op="del" title="Delete block" aria-label="Delete block" class="danger">${ICON('trash')}</button>
      </div></div>${add(b.id)}`).join('')
    +(ED.blocks.length?'':'<p class="nbe-ph">This note is empty: add a block with +</p>');
  renderDiagrams(list);
  list.querySelectorAll('[data-add]').forEach(x=>x.onclick=e=>{e.stopPropagation();edMenu(x,+x.dataset.add)});
  list.querySelectorAll('.nbb').forEach(el=>{
    const id=+el.dataset.b, b=ED.blocks.find(x=>x.id===id);
    el.querySelector('.nbb-c').addEventListener('click',e=>{
      if(e.target.closest('a'))e.preventDefault();   // a link in a block opens the block, it does not leave the editor
      if(ED.active!==id)edOpen(id)});
    el.querySelectorAll('[data-op]').forEach(x=>x.onclick=e=>{e.stopPropagation();edOp(id,x.dataset.op)});
    const h=el.querySelector('.nbb-h');
    h.addEventListener('dragstart',e=>{ED._drag=id;el.classList.add('drag');e.dataTransfer.effectAllowed='move';
      e.dataTransfer.setData('text/plain','');try{e.dataTransfer.setDragImage(el,20,20)}catch{}});
    h.addEventListener('dragend',()=>{ED._drag=null;el.classList.remove('drag');list.querySelectorAll('.over-a,.over-b').forEach(x=>x.classList.remove('over-a','over-b'))});
    el.addEventListener('dragover',e=>{if(!ED._drag)return;e.preventDefault();
      const r=el.getBoundingClientRect(), above=e.clientY<r.top+r.height/2;
      list.querySelectorAll('.over-a,.over-b').forEach(x=>x!==el&&x.classList.remove('over-a','over-b'));
      el.classList.toggle('over-a',above); el.classList.toggle('over-b',!above)});
    el.addEventListener('drop',e=>{if(!ED._drag)return;e.preventDefault();e.stopPropagation();
      const above=el.classList.contains('over-a'); edMueve(ED._drag,id,above)});
    if(ED.active===id)edCablea(el,b,focus);
  });
}
function edCablea(el,b,focus){
  const ta=el.querySelector('.nbe-ta'), pv=el.querySelector('.nbe-pv');
  const grows=()=>{if(!ta)return;ta.style.height='auto';ta.style.height=Math.max(ta.scrollHeight+2,b.t==='text'?60:90)+'px'};
  let t;
  const view=()=>{if(!pv)return;clearTimeout(t);t=setTimeout(()=>{
    if(b.t==='mermaid'){pv.innerHTML=b.src.trim()?`<span class="fig pending" data-mermaid="${esc(b.src)}">drawing…</span>`:'';renderDiagrams(pv)}
    else pv.innerHTML=/[|#>*`\[!_~=-]/.test(b.src)?nbMd(b.src,edCtx()):'';
  },b.t==='mermaid'?500:250)};
  if(ta){
    grows(); view();
    ta.oninput=()=>{b.src=ta.value;grows();view()};
    ta.onpaste=e=>{const fs=[...(e.clipboardData?.files||[])].filter(f=>/^image\//.test(f.type));
      if(fs.length){e.preventDefault();edImages(fs,b.id)}};
    ta.onkeydown=e=>edKey(e,b,ta);
    if(focus!==false){ta.focus();const p=focus==='start'?0:ta.value.length;ta.setSelectionRange(p,p)}
  }
  const lang=el.querySelector('.nbe-lang'); if(lang){lang.oninput=()=>{b.lang=lang.value.trim()};lang.onkeydown=e=>edKey(e,b,null)}
  const alt=el.querySelector('.nbe-alt'), src=el.querySelector('.nbe-src');
  if(alt){alt.oninput=()=>{b.alt=alt.value;b.wiki=false};alt.onkeydown=e=>edKey(e,b,null);if(focus!==false)alt.focus()}
  if(src){src.onchange=()=>{b.src=src.value.trim();b.wiki=false;edDraw(false)};src.onkeydown=e=>edKey(e,b,null)}
  const re=el.querySelector('.nbe-re'); if(re)re.onclick=()=>{ED._replace=b.id;ED._afterFile=b.id;$('#ede-file').click()};
  el.querySelectorAll('[data-tb]').forEach(x=>{x.onmousedown=e=>e.preventDefault();x.onclick=()=>edFormato(ta,x.dataset.tb,b)});
}
function edKey(e,b,ta){
  if(e.altKey&&(e.key==='ArrowUp'||e.key==='ArrowDown')){e.preventDefault();edOp(b.id,e.key==='ArrowUp'?'up':'down');return}
  if(!ta)return;
  if((e.ctrlKey||e.metaKey)&&(e.key==='b'||e.key==='i')){e.preventDefault();edFormato(ta,e.key,b);return}
  if(b.t!=='text')return;
  const fin=ta.selectionStart===ta.value.length&&ta.selectionEnd===ta.value.length;
  // Enter on an empty last line: new block below (Notion style)
  if(e.key==='Enter'&&!e.shiftKey&&fin&&ta.value.endsWith('\n')&&ta.value.trim()){
    e.preventDefault(); b.src=ta.value.replace(/\n+$/,''); edNew(b.id,'text'); return}
  // Backspace on an empty block: delete it and go to the previous one
  if(e.key==='Backspace'&&!ta.value&&ED.blocks.length>1){
    e.preventDefault(); const k=ED.blocks.indexOf(b); edSaveUndo(); ED.blocks.splice(k,1);
    const prev=ED.blocks[Math.max(0,k-1)]; ED.active=prev.t==='img'?null:prev.id; edDraw(); return}
  // continue lists and checklists on Enter
  if(e.key==='Enter'&&!e.shiftKey&&ta.selectionStart===ta.selectionEnd){
    const v=ta.value, p=ta.selectionStart, ini=v.lastIndexOf('\n',p-1)+1, line=v.slice(ini,p);
    const m=line.match(/^(\s*)([-*+]|\d+[.)])\s+(\[[ xX]\]\s+)?/);
    if(m&&p===(v.indexOf('\n',p)<0?v.length:v.indexOf('\n',p))){
      e.preventDefault();
      if(line.trim()===m[0].trim()){ta.setRangeText('',ini,p,'end')}   // empty item: end the list
      else{const num=m[2].match(/^(\d+)([.)])$/), sig=num?`${+num[1]+1}${num[2]}`:m[2];
        ta.setRangeText(`\n${m[1]}${sig} ${m[3]?'[ ] ':''}`,p,p,'end')}
      ta.dispatchEvent(new Event('input'));
    }
  }
}
function edFormato(ta,k,b){
  if(!ta)return; const s=ta.selectionStart, e=ta.selectionEnd, v=ta.value, sel=v.slice(s,e);
  const wrap=(a,z,ph)=>{const t=sel||ph;ta.setRangeText(a+t+z,s,e,'select');if(!sel)ta.setSelectionRange(s+a.length,s+a.length+t.length)};
  const prefix=(pre,remove)=>{const ini=v.lastIndexOf('\n',s-1)+1, fin=v.indexOf('\n',e)<0?v.length:v.indexOf('\n',e);
    const ls=v.slice(ini,fin).split('\n');
    const todas=ls.every(l=>l.startsWith(pre));
    ta.setRangeText(ls.map(l=>todas?l.slice(pre.length):pre+l.replace(remove||/^$/,'')).join('\n'),ini,fin,'select')};
  if(k==='b')wrap('**','**','bold'); else if(k==='i')wrap('*','*','italic');
  else if(k==='c')wrap('`','`','code'); else if(k==='l')wrap('[','](https://)','text');
  else if(k==='h'){const ini=v.lastIndexOf('\n',s-1)+1, m=v.slice(ini).match(/^(#{0,5})\s*/), n=m[1].length;
    ta.setRangeText(n>=4?'':'#'.repeat(n?n+1:2)+' ',ini,ini+m[0].length,'end')}
  else if(k==='ul')prefix('- ',/^\s*([-*+]|\d+[.)])\s+(\[[ xX]\]\s+)?/);
  else if(k==='ck')prefix('- [ ] ',/^\s*([-*+]|\d+[.)])\s+(\[[ xX]\]\s+)?/);
  else if(k==='q')prefix('> ');
  ta.focus(); ta.dispatchEvent(new Event('input'));
}

/* ---------------- operations ---------------- */
function edSaveUndo(){ED.undo.push(JSON.stringify(ED.blocks)); if(ED.undo.length>60)ED.undo.shift(); const u=$('#ede-undo'); if(u)u.disabled=false}
function edUndo(){if(!ED||!ED.undo.length)return; ED.blocks=JSON.parse(ED.undo.pop()); ED.active=null; edDraw();
  $('#ede-undo').disabled=!ED.undo.length}
function edOpen(id,focus){
  const prev=ED.active&&ED.blocks.find(x=>x.id===ED.active);
  if(prev&&prev.id!==id&&prev.t==='text'&&!prev.src.trim()&&ED.blocks.length>1)ED.blocks.splice(ED.blocks.indexOf(prev),1);
  ED.active=id; edDraw(focus)}
function edClose(){if(!ED||!ED.active)return; const b=ED.blocks.find(x=>x.id===ED.active);
  ED.active=null;
  if(b&&b.t==='text'&&!b.src.trim()&&ED.blocks.length>1)ED.blocks.splice(ED.blocks.indexOf(b),1);   // an empty text block does not stay
  edDraw()}
function edOp(id,op){
  const k=ED.blocks.findIndex(x=>x.id===id); if(k<0)return; edSaveUndo();
  const B=ED.blocks;
  if(op==='up'&&k>0)[B[k-1],B[k]]=[B[k],B[k-1]];
  else if(op==='down'&&k<B.length-1)[B[k+1],B[k]]=[B[k],B[k+1]];
  else if(op==='dup'){B.splice(k+1,0,{...B[k],id:++ED_ID})}
  else if(op==='del'){B.splice(k,1); if(ED.active===id)ED.active=null; toast('Block deleted · Ctrl+Z to undo')}
  edDraw(false);
  const el=document.querySelector(`.nbb[data-b="${id}"]`); if(el&&op!=='del'){el.scrollIntoView({block:'nearest'});
    el.classList.add('moved'); setTimeout(()=>el.classList.remove('moved'),500)}
}
function edMueve(id,dest,above){
  if(id===dest)return; edSaveUndo();
  const B=ED.blocks, k=B.findIndex(x=>x.id===id), [b]=B.splice(k,1);
  const j=B.findIndex(x=>x.id===dest); B.splice(above?j:j+1,0,b); edDraw(false);
}
function edNew(afterId,kind){
  edSaveUndo();
  const b=kind==='code'?edBlock('code',{lang:''}):kind==='mermaid'?edBlock('mermaid',{src:'flowchart LR\n  A[Start] --> B[End]'})
    :edBlock('text',{src:ED_INI[kind]??''});
  const k=afterId?ED.blocks.findIndex(x=>x.id===afterId)+1:0;
  ED.blocks.splice(k,0,b);
  if(kind==='hr'){ED.active=null;edDraw(false)} else edOpen(b.id);
  return b;
}
function edMenu(btn,afterId){
  document.querySelectorAll('.nbe-pop').forEach(p=>p.remove());
  const pop=document.createElement('div'); pop.className='nbe-pop';
  pop.innerHTML=ED_KINDS.map(([k,t,d])=>`<button type="button" data-k="${k}"><b>${t}</b><span>${esc(d)}</span></button>`).join('');
  btn.parentElement.append(pop);
  const outside=e=>{if(!pop.contains(e.target)){pop.remove();document.removeEventListener('mousedown',outside,true)}};
  setTimeout(()=>document.addEventListener('mousedown',outside,true));
  pop.querySelectorAll('[data-k]').forEach(x=>x.onclick=()=>{pop.remove();document.removeEventListener('mousedown',outside,true);
    if(x.dataset.k==='img'){ED._afterFile=afterId;ED._replace=null;$('#ede-file').click()}
    else edNew(afterId,x.dataset.k)});
  pop.querySelector('button').focus();
}
async function edUploads(f){
  const r=await fetch(`/api/notebook/image?id=${encodeURIComponent(NB.c.id)}&relpath=${encodeURIComponent(ED.relpath)}`,
    {method:'POST',body:f,headers:{'X-Gatito-Token':tok(),'Content-Type':f.type,'X-Filename':encodeURIComponent(f.name||'')}})
    .then(r=>r.json()).catch(()=>({ok:false,err:'no connection'}));
  if(!r.ok){toast('Could not add the image: '+(r.err||''),true);return null}
  return r.rel;
}
async function edImages(fs,afterId){
  fs=fs.filter(f=>/^image\/(png|jpeg|webp|gif)$/.test(f.type));
  if(!fs.length)return toast('Images only: png, jpg, webp or gif',true);
  toast(fs.length>1?`Uploading ${fs.length} images…`:'Uploading image…');
  const replace=ED._replace; ED._replace=null;
  for(const f of fs){
    const rel=await edUploads(f); if(!rel||!ED)return;
    const alt=(f.name||'').replace(/\.[^.]+$/,'').replace(/^image$/,'').replace(/[-_]+/g,' ').trim();
    const old=replace&&ED.blocks.find(x=>x.id===replace);
    edSaveUndo();
    if(old){old.src=rel;old.wiki=false;afterId=old.id;continue}
    const b=edBlock('img',{src:rel,alt}), k=afterId?ED.blocks.findIndex(x=>x.id===afterId)+1:ED.blocks.length;
    ED.blocks.splice(k<=0?ED.blocks.length:k,0,b); afterId=b.id;
  }
  ED.active=null; edDraw(false); toast('Image added');
}
function edMode(mode){
  if(mode===ED.mode)return;
  const md=$('#ede-md'), list=$('#ede-list');
  if(mode==='md'){edClose();md.value=edBody().replace(/^\n/,'');md.hidden=false;list.hidden=true;md.focus()}
  else{ED.blocks=edParse(md.value);ED.active=null;md.hidden=true;list.hidden=false;edDraw()}
  ED.mode=mode;
  document.querySelectorAll('[data-mode]').forEach(b=>b.classList.toggle('on',b.dataset.mode===mode));
  $('#ede-undo').hidden=mode==='md';
}
async function edSave(force){
  if(!ED)return;
  const meta=edMeta();
  let body=ED.mode==='md'?'\n'+$('#ede-md').value.replace(/^\n+/,''):edBody();
  // the "# Title" at the top follows the title field
  const old=ED.meta.title, h1=old&&body.match(/^\n*#\s+(.*)\n/);
  if(h1&&h1[1].trim()===old.trim()&&meta.title&&meta.title!==old)body=body.replace(h1[0],'\n# '+meta.title+'\n');
  if(!Object.keys(meta).length)body=body.replace(/^\n+/,'');   // no frontmatter: no blank line on top
  const r=await api('/api/notebook/note/save',{id:NB.c.id,relpath:ED.relpath,meta,body,mtime:force?undefined:ED.mtime})
    .catch(()=>({ok:false,err:'no connection'}));
  if(r.conflict){
    if(await confirmBox('The note has changed','Someone (maybe an agent) modified it while you were editing. Save yours over it? The previous version stays in the history.','Save over it',false))return edSave(true);
    return;
  }
  if(!r.ok)return toast('Could not save: '+(r.err||''),true);
  toast('Saved'); ED=null; NB.edit=false; NB.note=null; await loadNotebook(true); renderNbMain();
}
window.addEventListener('beforeunload',e=>{if(edDirty()){e.preventDefault();e.returnValue=''}});

/* ---------------- PDF ---------------- */
// The browser prints a clean copy of the note (light, without the app around it): "Save as PDF".
async function nbPdf({title,summary,body,relpath,meta}){
  document.getElementById('nb-print')?.remove();
  const ctx={id:NB.c.id,dir:nbDir(relpath),off:null,relpath,ro:true};
  const sinH1=String(body).replace(/^\s*#\s+[^\n]*\n/,'\n');
  // to share: only the title and the content. No metadata, no notebook paths, no links to gatito
  // (localhost or this PC's IP); links to the internet stay. Each page's margin comes from the
  // table's header/footer (they repeat on every page), because @page has no margin: that is what
  // makes the browser drop its own header and footer (URL, date, title).
  const el=document.createElement('div'); el.id='nb-print';
  el.innerHTML=`<table class="nb-pt"><thead><tr><td></td></tr></thead><tfoot><tr><td></td></tr></tfoot><tbody><tr><td>
    <article class="nb-doc"><h1 class="nb-h">${esc(title)}</h1>
    <div class="nb-md">${nbMd(sinH1,ctx).replace(/ loading="lazy"/g,'')}</div></article></td></tr></tbody></table>`;
  el.querySelectorAll('a').forEach(a=>{
    if(/^(https?:|mailto:)/i.test(a.getAttribute('href')||'')&&!/^https?:\/\/(localhost|127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/i.test(a.href))return;
    a.replaceWith(...a.childNodes)});
  el.querySelectorAll('.nb-missing').forEach(x=>x.classList.remove('nb-missing'));
  el.querySelectorAll('img[alt]').forEach(i=>{if(/^\d{8}-\d{6}-/.test(i.alt))i.alt=''});
  document.body.append(el);
  toast('Preparing the PDF…');
  await renderDiagrams(el);
  await Promise.all([...el.querySelectorAll('img')].map(i=>i.complete?0:new Promise(r=>{i.onload=i.onerror=r;setTimeout(r,4000)})));
  const t=document.title; document.title=title;   // the PDF's file name
  document.body.classList.add('nb-printing');
  const fin=()=>{document.body.classList.remove('nb-printing');document.title=t;el.remove();window.removeEventListener('afterprint',fin)};
  window.addEventListener('afterprint',fin);
  window.print();   // on screen #nb-print stays hidden: if "afterprint" never comes, nothing is left in the way
}
function nbPdfNote(){
  const n=NB.note; if(!n)return;
  nbPdf({title:nbTitleOf(n),summary:(n.info||{}).summary,body:n.body,relpath:n.relpath,meta:n.meta});
}
