/* "Artifacts" view (#/artifacts): what the agents generate and what stays saved
   (state/artifacts): diagrams with their source, HTML pages, images, reports.
   Gallery with search and filter; opening one shows a viewer with its versions and downloads.
   HTML pages run in a sandboxed iframe without allow-same-origin and the server
   serves them with a network-less CSP: no internet and no gatito API. */

let ART={listing:[],sig:'',q:'',kind:stored('gatito-art-kind')||'',id:null,meta:null,v:null,source:false};
const ART_KIND={diagram:'Diagram',page:'Page',image:'Image',text:'Text',other:'File'};
const ART_FILTERS=[['','All'],['diagram','Diagrams'],['page','Pages'],['otros','Other']];

function artUrl(id,v,f,dl){return`/api/artifact/raw?id=${encodeURIComponent(id)}&v=${encodeURIComponent(v)}&f=${encodeURIComponent(f)}${dl?'&dl=1':''}`}
// …/state/artifacts/<id>/v3/x.svg → {id,v,f}
function artRef(p){const m=String(p).match(/\/state\/artifacts\/([a-z0-9][a-z0-9-]*)\/(v\d+)\/([^/]+)$/);
  return m?{id:m[1],v:m[2],f:m[3]}:null}
const artExt=f=>(String(f).match(/\.([a-z0-9]+)$/i)||[,''])[1].toLowerCase();
const artEsImg=f=>/^(svg|png|jpe?g|gif|webp)$/.test(artExt(f));
const artEsHtml=f=>/^html?$/.test(artExt(f));
function artDate(s){const t=Date.parse(s);return isNaN(t)?'':ago(t)}

function initArt(){
  $('#v-art').innerHTML=`<header class="vh"><h1>Artifacts</h1><span class="sub" id="art-sub"></span>
    <div class="vh-tools">
      <input class="art-q" id="art-q" type="search" placeholder="Search…" aria-label="Search artifacts">
      <div class="seg" id="art-f">${ART_FILTERS.map(([k,t])=>`<button type="button" data-t="${k}">${t}</button>`).join('')}</div>
    </div></header>
    <div class="art-body"><div class="art-grid" id="art-grid"></div><section class="art-view" id="art-view" hidden></section></div>`;
  $('#art-q').oninput=e=>{ART.q=e.target.value.trim().toLowerCase();renderArtGrid()};
  $('#art-f').onclick=e=>{const b=e.target.closest('button');if(!b)return;
    ART.kind=b.dataset.t;store('gatito-art-kind',ART.kind||null);renderArtGrid()};
}

async function renderArt(force){
  if(VIEW!=='art'&&!force)return;
  try{const l=await api('/api/artifacts');
    const sig=JSON.stringify(l.map(m=>[m.id,m.version,m.title,m.updated]));
    if(sig===ART.sig&&!force)return; ART.sig=sig; ART.listing=l;
  }catch(e){return}
  renderArtGrid();
  if(ART.id&&ART.meta&&!ART.listing.some(m=>m.id===ART.id))closeArt();
}

function artFilters(m){
  if(ART.kind==='otros'?['diagram','page'].includes(m.kind):ART.kind&&m.kind!==ART.kind)return false;
  if(!ART.q)return true;
  return [m.title,m.description,m.id,m.origin].join(' ').toLowerCase().includes(ART.q);
}
function artMini(m){
  const u=artUrl(m.id,'v'+m.version,m.principal);
  if(artEsImg(m.principal))return`<img src="${esc(u)}" alt="" loading="lazy">`;
  if(artEsHtml(m.principal))return`<iframe src="${esc(u)}" sandbox="allow-scripts" loading="lazy" tabindex="-1" title=""></iframe>`;
  return`<span class="art-ext">.${esc(artExt(m.principal)||'?')}</span>`;
}
function renderArtGrid(){
  const g=$('#art-grid'); if(!g)return;
  $('#art-f').querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',b.dataset.t===ART.kind));
  const l=ART.listing.filter(artFilters);
  $('#art-sub').textContent=ART.listing.length?`${ART.listing.length} saved`:'';
  if(!ART.listing.length){g.innerHTML=`<div class="art-empty"><b>No artifacts yet.</b>
      This is where the infrastructure diagrams the agents draw (with their source) and the
      pages or reports they save with <code>bin/artifact</code> are kept. In a session,
      try the "Infra diagram" button.</div>`;return}
  if(!l.length){g.innerHTML='<div class="art-empty">Nothing matches the search.</div>';return}
  g.innerHTML=l.map(m=>`<a class="art-card${m.id===ART.id?' on':''}" href="#/artifacts/${esc(m.id)}">
      <span class="art-thumb">${artMini(m)}</span>
      <span class="art-info"><b>${esc(m.title)}</b>
        <span class="art-meta"><span class="art-tag t-${esc(m.kind)}">${esc(ART_KIND[m.kind]||m.kind)}</span>
        v${m.version} · ${esc(artDate(m.updated))}</span></span></a>`).join('');
}

async function openArt(id,v){
  ART.id=id; ART.source=false;
  $('#v-art').classList.add('viewing');
  const box=$('#art-view'); box.hidden=false; box.innerHTML='<div class="art-empty">Loading…</div>';
  let m; try{m=await api('/api/artifact?id='+encodeURIComponent(id))}catch(e){return}
  if(ART.id!==id)return;
  if(!m||!m.versions){box.innerHTML='<div class="art-empty">This artifact no longer exists.</div>';return}
  ART.meta=m; ART.v=v&&m.versions.some(x=>'v'+x.v===v)?v:'v'+m.version;
  renderArtView(); renderArtGrid();
}
function closeArt(){
  ART.id=ART.meta=null; $('#v-art').classList.remove('viewing');
  const box=$('#art-view'); if(box){box.hidden=true;box.innerHTML=''}
  renderArtGrid();
}
function artVersion(){return ART.meta.versions.find(x=>'v'+x.v===ART.v)||ART.meta.versions.at(-1)}

function renderArtView(){
  const m=ART.meta, ver=artVersion(), box=$('#art-view');
  const source=ver.files.find(f=>f!==ver.principal&&/\.(py|md|txt|ya?ml|json|tf|csv)$/i.test(f));
  const vers=m.versions.slice().reverse().map(x=>
    `<option value="v${x.v}"${'v'+x.v===ART.v?' selected':''}>v${x.v} · ${esc(artDate(x.date))}</option>`).join('');
  const downloads=ver.files.map(f=>`<a class="btn ghost" href="${esc(artUrl(m.id,ART.v,f,1))}" download>${ICON('download')}${esc(artExt(f).toUpperCase()||f)}</a>`).join('');
  box.innerHTML=`<div class="art-bar">
      <a class="btn ghost icon" href="#/artifacts" aria-label="Back to the gallery">${ICON('back')}</a>
      <div class="art-t"><b id="art-title">${esc(m.title)}</b>
        <span>${esc(ART_KIND[m.kind]||m.kind)}${m.origin?` · ${esc(home(m.origin))}`:''}</span></div>
      <select class="sel" id="art-ver" title="Version"${m.versions.length<2?' disabled':''}>${vers}</select>
    </div>
    <div class="art-tools">
      ${source?`<button class="btn ghost tog" id="art-src" aria-pressed="${ART.source}">${ICON('code')}Source</button>`:''}
      <a class="btn ghost" href="${esc(artUrl(m.id,ART.v,ver.principal))}" target="_blank" rel="noopener">${ICON('external')}Open</a>
      ${downloads}
      <span class="spacer"></span>
      <button class="btn ghost" id="art-ren">Rename</button>
      <button class="btn ghost danger" id="art-del">${ICON('trash')}Delete</button>
    </div>
    ${m.description?`<p class="art-desc">${esc(m.description)}</p>`:''}
    <div class="art-stage" id="art-stage"></div>`;
  $('#art-ver').onchange=e=>{ART.v=e.target.value;renderArtView()};
  if(source)$('#art-src').onclick=()=>{ART.source=!ART.source;renderArtView()};
  $('#art-ren').onclick=renameArt;
  $('#art-del').onclick=deleteArt;
  artStage(ART.source&&source?source:ver.principal);
}
async function artStage(f){
  const st=$('#art-stage'), u=artUrl(ART.meta.id,ART.v,f);
  if(artEsImg(f)){
    st.innerHTML=`<div class="art-img" title="Click to zoom or fit"><img src="${esc(u)}" alt="${esc(ART.meta.title)}"></div>`;
    st.firstChild.onclick=()=>st.firstChild.classList.toggle('zoom');
  }else if(artEsHtml(f)){
    st.innerHTML=`<iframe class="art-frame" src="${esc(u)}" sandbox="allow-scripts allow-popups allow-downloads" title="${esc(ART.meta.title)}"></iframe>`;
  }else{
    st.innerHTML='<div class="art-empty">Loading…</div>';
    try{const r=await fetch(u,{headers:{'X-Gatito-Token':tok()}});
      st.innerHTML=codeBox(artExt(f)==='py'?'python':artExt(f),await r.text());wireCopy(st)}
    catch(e){st.innerHTML='<div class="art-empty">Could not load.</div>'}
  }
}
function renameArt(){
  const m=ART.meta;
  const d=dialog(`<h3>Rename</h3><input class="art-q" id="ren-t" value="${esc(m.title)}" style="width:100%">
    <div class="acts"><button class="btn ghost" data-v="0">Cancel</button><button class="btn primary" data-v="1">Save</button></div>`);
  const t=$('#ren-t'); t.focus(); t.select();
  const ok=async()=>{const v=t.value.trim();d.close();if(!v||v===m.title)return;
    const r=await api('/api/artifact/rename',{id:m.id,title:v});
    if(r.ok){m.title=v;renderArtView();renderArt(true)}else toast('Could not rename',true)};
  d.querySelector('[data-v="1"]').onclick=ok; d.querySelector('[data-v="0"]').onclick=()=>d.close();
  t.onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();ok()}};
}
async function deleteArt(){
  const m=ART.meta;
  if(!await confirmBox('Delete artifact',`"${m.title}" and its ${m.versions.length} versions go to the trash (state/artifacts/.trash).`))return;
  const r=await api('/api/artifact/remove',{id:m.id});
  if(!r.ok)return toast('Could not delete',true);
  toast('Deleted'); location.hash='#/artifacts'; renderArt(true);
}

/* in the chat: a saved page or file shows as a card that links here */
function artChatCard(ref,title){
  const k=artEsHtml(ref.f)?'Page':artExt(ref.f).toUpperCase()||'File';
  return`<a class="art-chat" href="#/artifacts/${esc(ref.id)}">${ICON('art')}
    <span><b>${esc(title||ref.id)}</b><span>${esc(k)} · ${esc(ref.v)} · Open in Artifacts</span></span>${ICON('right')}</a>`;
}
