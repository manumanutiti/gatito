/* Anonymization (gatitod/mask.py): the on/off switch of the chat and the "Anonymize" view
   (#/anonymize), where you keep the list of real values and the placeholders Claude sees
   instead, try it live, and import or export the list as JSON.
   With it on, what you type leaves for Claude with consistent placeholders; the
   conversation is always shown with the real values ("As sent" shows what the AI saw). */
function anonOn(){return stored('gatito-anon')==='1'}
function setAnon(on){store('gatito-anon',on?'1':null);paintAnon();
  toast(on?'Anonymize on: real names leave as placeholders':'Anonymize off: what you type leaves as is')}
function paintAnon(){
  const on=anonOn();
  document.querySelectorAll('[data-anon-tog]').forEach(b=>b.setAttribute('aria-pressed',on));
  document.querySelectorAll('#composer,#r-box').forEach(b=>b.classList.toggle('anon',on));
  const sw=$('#m-sw'); if(sw){sw.setAttribute('aria-checked',on);sw.querySelector('span').textContent=on?'On in the chat':'Off in the chat'}
  document.querySelectorAll('.tab[data-view="mask"]').forEach(t=>t.classList.toggle('anon-on',on));
}
document.addEventListener('click',e=>{
  if(e.target.closest('[data-anon-tog]')){e.preventDefault();setAnon(!anonOn())}
  else if(e.target.closest('[data-anon-cfg]')){e.preventDefault();location.hash='#/anonymize'}
});

const MASK={data:null,saved:'',built:false,mode:'mask',timer:0};

// the placeholder a kind suggests: tenant-alpha, rg-bravo, a fake GUID...
function suggestFake(kind,used){
  const k=(MASK.data.kinds.find(x=>x.id===kind)||MASK.data.kinds.at(-1)).fake;
  const taken=s=>used.has(s.toLowerCase());
  for(let n=1;n<2000;n++){
    const w=MASK.data.nato[(n-1)%26]+(n>26?Math.ceil(n/26):'');
    const s=k.replace('{w}',w).replace('{guid}','00000000-0000-4000-b000-'+n.toString(16).padStart(12,'0'))
      .replace('{aws}','8888'+String(n).padStart(8,'0'));
    if(!taken(s))return s;
  }
  return '';
}
// rows of the starter list: the usual cloud and DevOps names, real value left for you
const TEMPLATE=['tenant','tenant_id','subscription','subscription_id','client','domain','rg','cluster',
  'namespace','keyvault','storage','registry','vnet','app','devops_org','devops_project','repo','pipeline'];

/* ---------------- the list ---------------- */
function maskRow(e){
  const kinds=MASK.data.kinds.map(k=>`<option value="${k.id}"${k.id===e.kind?' selected':''}>${esc(k.label)}</option>`).join('');
  return `<div class="m-row${e.on===false?' off':''}" role="row">
    <input type="checkbox" class="m-on"${e.on===false?'':' checked'} title="Use this row" aria-label="Use this row">
    <select class="m-kind" aria-label="Kind">${kinds}</select>
    <input class="m-real" value="${esc(e.real||'')}" placeholder="Real value, e.g. Contoso" spellcheck="false" autocomplete="off" aria-label="Real value">
    <span class="m-arrow" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M4 12h15M14 7l5 5-5 5"/></svg></span>
    <input class="m-fake" value="${esc(e.fake||'')}" placeholder="Placeholder" spellcheck="false" autocomplete="off" aria-label="Placeholder"
      ${e.auto?'data-auto="1"':''}>
    <button class="btn ghost icon m-del" type="button" title="Delete row" aria-label="Delete row">${ICON('x')}</button></div>`;
}
function maskRows(){
  return [...document.querySelectorAll('#m-rows .m-row')].map(tr=>({tr,kind:tr.querySelector('.m-kind').value,
    real:tr.querySelector('.m-real').value.trim(),fake:tr.querySelector('.m-fake').value.trim(),
    on:tr.querySelector('.m-on').checked}));
}
const plainRows=()=>maskRows().filter(r=>r.real&&r.fake).map(({kind,real,fake,on})=>({kind,real,fake,on}));
function usedFakes(except){return new Set(maskRows().filter(r=>r.tr!==except).map(r=>r.fake.toLowerCase()).filter(Boolean))}
function wireRow(tr){
  const fake=tr.querySelector('.m-fake'), kind=tr.querySelector('.m-kind');
  const fill=()=>{if(!fake.value.trim()||fake.dataset.auto){fake.value=suggestFake(kind.value,usedFakes(tr));fake.dataset.auto='1'}};
  kind.onchange=()=>{fill();maskDirty()};
  tr.querySelector('.m-real').oninput=()=>{if(!fake.value.trim())fill();maskDirty()};
  fake.oninput=()=>{delete fake.dataset.auto;maskDirty()};
  tr.querySelector('.m-on').onchange=e=>{tr.classList.toggle('off',!e.target.checked);maskDirty()};
  tr.querySelector('.m-del').onclick=()=>{tr.remove();maskDirty()};
}
function addRow(e,top){
  const tb=$('#m-rows'); tb.insertAdjacentHTML(top?'afterbegin':'beforeend',maskRow(e));
  const tr=top?tb.firstElementChild:tb.lastElementChild; wireRow(tr); return tr;
}
function setRows(entries){$('#m-rows').innerHTML='';entries.forEach(e=>addRow(e))}

/* ---------------- unsaved changes ---------------- */
function maskState(){
  const detect={}; document.querySelectorAll('#v-mask [data-det]').forEach(c=>detect[c.dataset.det]=c.checked);
  const keep=$('#m-keep').value.split('\n').map(s=>s.trim()).filter(Boolean);
  return {entries:plainRows(),detect,keep};
}
function maskDirty(){
  if(!MASK.built)return;
  const dirty=JSON.stringify(maskState())!==MASK.saved;
  $('#m-save').disabled=!dirty; $('#m-dirty').hidden=!dirty;
  const rows=maskRows(), n=rows.filter(r=>r.real).length;
  $('#m-n').textContent=n?`${n}`:'';
  $('#m-sub').textContent=n?`${n} ${n===1?'value':'values'} in your list`:'Your list is empty';
  $('#m-empty').hidden=rows.length>0;
  if($('#m-test').value.trim()){clearTimeout(MASK.timer);MASK.timer=setTimeout(maskTry,300)}
  return dirty;
}
addEventListener('beforeunload',e=>{if(MASK.built&&!$('#m-save').disabled){e.preventDefault();e.returnValue=''}});

/* ---------------- the view ---------------- */
function initMask(){
  $('#v-mask').innerHTML=`<header class="vh"><h1>Anonymize</h1><span class="sub" id="m-sub"></span>
    <div class="vh-tools">
      <button class="m-sw" id="m-sw" type="button" role="switch" aria-checked="false"
        title="Applies to what you send from this browser"><i aria-hidden="true"></i><span>Off in the chat</span></button>
      <button class="btn ghost" id="m-imp" type="button" title="Add placeholders from a JSON file">${ICON('upload')}Import</button>
      <button class="btn ghost" id="m-exp" type="button" title="Download your list as JSON">${ICON('download')}Export</button>
      <span class="m-dirty" id="m-dirty" hidden>Unsaved changes</span>
      <button class="btn primary" id="m-save" type="button" disabled>Save</button>
    </div></header>
  <div class="m-body">
    <section class="m-main" aria-label="Your list">
      <p class="m-lead">Each real value on the left leaves for Claude as the placeholder on the right, in your messages
        and in anonymous sessions. You always read the conversation with the real values.</p>
      <div class="m-tools">
        <button class="btn ghost" id="m-add" type="button">${ICON('plus')}Add</button>
        <button class="btn ghost" id="m-tpl" type="button" title="Adds empty rows for tenants, subscriptions, resource groups, clusters, vaults, repos…">${ICON('plus')}Cloud and DevOps rows</button>
        <span class="spacer"></span>
        <input id="m-q" type="search" placeholder="Filter" autocomplete="off" aria-label="Filter the list">
      </div>
      <div class="m-head" aria-hidden="true"><span></span><span>Kind</span><span>Real value <b id="m-n"></b></span><span></span><span>Claude sees</span><span></span></div>
      <div class="m-rows" id="m-rows" role="table" aria-label="Real values and placeholders"></div>
      <div class="m-empty" id="m-empty" hidden>
        <p>Add the names Claude should not see: tenants, subscriptions, clients, domains, people…</p>
        <div class="row-btns"><button class="btn ghost" type="button" data-m="add">${ICON('plus')}Add one</button>
          <button class="btn ghost" type="button" data-m="tpl">${ICON('plus')}Start from the cloud and DevOps rows</button>
          <button class="btn ghost" type="button" data-m="imp">${ICON('upload')}Import a JSON file</button></div>
      </div>
      <p class="fine">Case is kept both ways (ACME → TENANT-ALPHA) and it is replaced inside names
        (<code>rg-acme-prod</code>, <code>api.acme.com</code>) but not in the middle of a word (<code>acmeprod</code>).
        Keep the placeholder valid for that kind of resource (storage: lowercase letters and digits only).</p>
    </section>
    <aside class="m-side">
      <section class="m-card m-try">
        <div class="m-card-h"><h2>Try it</h2>
          <div class="m-seg" role="tablist" aria-label="Direction">
            <button type="button" role="tab" data-mode="mask" aria-selected="true">What Claude sees</button>
            <button type="button" role="tab" data-mode="unmask" aria-selected="false">Real values</button></div></div>
        <textarea id="m-test" rows="4" spellcheck="false"
          placeholder="Paste text to see what would leave for Claude, with the list as it is on screen"></textarea>
        <pre class="m-out" id="m-out" hidden></pre>
        <div class="m-found" id="m-found" hidden></div>
      </section>
      <section class="m-card">
        <div class="m-card-h"><h2>Automatic detection</h2></div>
        <div class="m-det" id="m-det"></div>
        <label class="fine" for="m-keep">Never mask, one per line (public DNS, Azure built-in roles and well-known app ids are already left alone):</label>
        <textarea id="m-keep" rows="3" spellcheck="false"></textarea>
      </section>
      <section class="m-card">
        <div class="m-card-h"><h2>Learned by the detectors <b id="m-ln"></b></h2>
          <button class="btn ghost danger" id="m-forget" type="button" hidden>Forget all</button></div>
        <div class="m-learned" id="m-learned"></div>
      </section>
    </aside>
  </div>
  <input type="file" id="m-file" accept="application/json,.json" hidden>`;
  $('#m-sw').onclick=()=>setAnon(!anonOn());
  $('#m-add').onclick=()=>{addRow({kind:'tenant'},true).querySelector('.m-real').focus();maskDirty()};
  $('#m-tpl').onclick=maskTemplate;
  $('#m-imp').onclick=()=>openImport();
  $('#m-exp').onclick=maskExport;
  $('#m-save').onclick=maskSave;
  $('#m-empty').onclick=e=>{const b=e.target.closest('[data-m]'); if(!b)return;
    ({add:()=>$('#m-add').click(),tpl:maskTemplate,imp:()=>openImport()})[b.dataset.m]()};
  $('#m-q').oninput=e=>{const q=e.target.value.toLowerCase();
    maskRows().forEach(r=>r.tr.hidden=!!q&&!`${r.real} ${r.fake} ${r.kind}`.toLowerCase().includes(q))};
  $('#m-keep').oninput=maskDirty;
  $('#m-det').onchange=maskDirty;
  document.querySelectorAll('#v-mask .m-seg button').forEach(b=>b.onclick=()=>{
    MASK.mode=b.dataset.mode;
    document.querySelectorAll('#v-mask .m-seg button').forEach(x=>x.setAttribute('aria-selected',x===b));
    $('#m-test').placeholder=MASK.mode==='mask'?'Paste text to see what would leave for Claude, with the list as it is on screen'
      :'Paste an answer with placeholders to read it with the real values';
    maskTry()});
  $('#m-test').oninput=()=>{clearTimeout(MASK.timer);MASK.timer=setTimeout(maskTry,300)};
  $('#m-forget').onclick=async()=>{
    if(!await confirmBox('Forget what was learned','The detected values (IPs, GUIDs, e-mails, secrets…) and their placeholders are deleted. '+
      'Conversations that used them will show the placeholders instead of the real values.','Forget all'))return;
    await api('/api/mask/forget',{}); toast('Forgotten'); renderMask(true,true)};
  $('#m-file').onchange=async e=>{const f=e.target.files[0]; e.target.value=''; if(f)openImport(await f.text(),f.name)};
  paintAnon();
}

// force: reload from the server; with unsaved edits only the learned list is refreshed
async function renderMask(force,learnedOnly){
  if(VIEW!=='mask'&&!force)return;
  const d=await api('/api/mask').catch(()=>null);
  if(!d)return toast('Could not load the anonymization settings',true);
  MASK.data=d;
  const keepEdits=MASK.built&&!$('#m-save').disabled;
  if(!learnedOnly&&!keepEdits){
    MASK.built=false;
    setRows(d.entries);
    $('#m-det').innerHTML=d.detectors.map(x=>`<label class="check"><input type="checkbox" data-det="${x.id}"${d.detect[x.id]?' checked':''}>${esc(x.label)}</label>`).join('');
    $('#m-keep').value=d.keep.join('\n');
    MASK.built=true; MASK.saved=JSON.stringify(maskState());
  }
  $('#m-ln').textContent=d.learned.length||'';
  $('#m-forget').hidden=!d.learned.length;
  $('#m-learned').innerHTML=d.learned.length?d.learned.map(x=>`<div class="m-lrow"><span class="k">${esc(x.kind)}</span>
      <code title="${esc(x.real)}">${esc(x.real.length>60?x.real.slice(0,60)+'…':x.real)}</code>
      <code class="f">${esc(x.fake)}</code>
      <button class="btn ghost icon" data-forget="${esc(x.real)}" title="Forget" aria-label="Forget">${ICON('x')}</button></div>`).join('')
    :'<p class="fine">Nothing yet: IPs, GUIDs, e-mails and secrets show up here once they are sent.</p>';
  $('#m-learned').querySelectorAll('[data-forget]').forEach(b=>b.onclick=async()=>{
    await api('/api/mask/forget',{real:b.dataset.forget}); renderMask(true,true)});
  maskDirty();
}

function maskTemplate(){
  const have=new Set(maskRows().filter(r=>!r.real).map(r=>r.kind));
  TEMPLATE.filter(k=>!have.has(k)).reverse().forEach(k=>{const tr=addRow({kind:k},true);tr.querySelector('.m-kind').onchange()});
  $('#m-rows').scrollTop=0; maskDirty();
}

async function maskTry(){
  const text=$('#m-test').value, o=$('#m-out'), f=$('#m-found');
  if(!text.trim()){o.hidden=f.hidden=true;return}
  const r=MASK.mode==='mask'?await api('/api/mask/preview',{text,entries:plainRows()}).catch(()=>null)
    :await api('/api/mask/unmask',{text}).catch(()=>null);
  if(!r)return;
  if(r.err){o.hidden=false;o.textContent=r.err;f.hidden=true;return}
  o.hidden=false; o.textContent=r.text;
  if(MASK.mode==='mask'){f.hidden=false;f.innerHTML=r.found&&r.found.length
      ?r.found.map(x=>`<span><code>${esc(x.real.length>40?x.real.slice(0,40)+'…':x.real)}</code> → <code class="f">${esc(x.fake)}</code></span>`).join('')
      :'<span class="fine">Nothing to mask in this text.</span>'}
  else f.hidden=true;
}

async function maskSave(){
  const s=maskState(), empty=maskRows().filter(r=>!r.real).length;
  const r=await api('/api/mask/save',s).catch(e=>({ok:false,err:e.message}));
  if(!r.ok)return toast(r.err||'Could not save',true);
  MASK.saved=JSON.stringify(s); maskDirty();
  toast(`Saved: ${s.entries.length} ${s.entries.length===1?'value':'values'}${empty?` (${empty} empty ${empty===1?'row':'rows'} left out)`:''}`);
  if(CUR)loadConvo(false);
}

/* ---------------- import and export ---------------- */
function maskExport(){
  const s=maskState();
  const body={gatito:'placeholders',version:1,exported:new Date().toISOString(),entries:s.entries,keep:s.keep};
  const a=document.createElement('a');
  a.href=URL.createObjectURL(new Blob([JSON.stringify(body,null,2)+'\n'],{type:'application/json'}));
  a.download=`gatito-placeholders-${new Date().toISOString().slice(0,10)}.json`;
  document.body.appendChild(a); a.click(); a.remove(); setTimeout(()=>URL.revokeObjectURL(a.href),1000);
  toast(`Exported ${s.entries.length} ${s.entries.length===1?'value':'values'}. The file has your real names: keep it private.`);
}

// accepts gatito's export, a list of {real, fake, kind} and a plain {"Real value": "placeholder"}
function parseImport(text){
  let j; try{j=JSON.parse(text)}catch(e){return {err:'It is not valid JSON: '+e.message}}
  const kinds=new Set(MASK.data.kinds.map(k=>k.id));
  const pick=(o,ks)=>{for(const k of ks)if(o[k]!=null&&String(o[k]).trim())return String(o[k]).trim();return ''};
  let raw, keep=[];
  if(Array.isArray(j))raw=j;
  else if(j&&typeof j==='object'&&Array.isArray(j.entries)){raw=j.entries;keep=Array.isArray(j.keep)?j.keep.map(String):[]}
  else if(j&&typeof j==='object')raw=Object.entries(j).map(([real,fake])=>({real,fake:typeof fake==='string'?fake:''}));
  else return {err:'Expected an object or a list'};
  const entries=[], bad=[], seen=new Set();
  for(const o of raw){
    if(!o||typeof o!=='object'){bad.push(String(o));continue}
    const real=pick(o,['real','original','value','from']), fake=pick(o,['fake','placeholder','replacement','to']);
    if(!real||!fake){bad.push(real||fake||'(empty)');continue}
    if(real.length<3){bad.push(`${real} (too short)`);continue}
    if(real.toLowerCase()===fake.toLowerCase()){bad.push(`${real} (same as its placeholder)`);continue}
    if(seen.has(real.toLowerCase()))continue; seen.add(real.toLowerCase());
    entries.push({real,fake,kind:kinds.has(o.kind)?o.kind:'other',on:o.on!==false});
  }
  return {entries,keep,bad};
}

function openImport(text,name){
  if(typeof text!=='string')text='';
  const d=dialog(`<h3>Import placeholders</h3>
    <p>A file exported from here, a list like <code>[{"real": "Contoso", "fake": "client-alpha", "kind": "client"}]</code>
      or simply <code>{"Contoso": "client-alpha"}</code>.</p>
    <div class="m-drop" id="m-drop">${ICON('upload')}<span>${name?esc(name):'Drop a .json file here or'}</span>
      <button class="btn ghost" id="m-pick" type="button">${name?'Choose another':'Choose a file'}</button></div>
    <textarea id="m-paste" rows="6" spellcheck="false" placeholder="…or paste the JSON here">${esc(text)}</textarea>
    <div class="m-imp-sum" id="m-imp-sum" aria-live="polite"></div>
    <div class="acts"><button class="btn ghost" id="m-icancel" type="button">Cancel</button>
      <button class="btn ghost" id="m-ireplace" type="button" disabled>Replace my list</button>
      <button class="btn primary" id="m-imerge" type="button" disabled>Add to my list</button></div>`,'mask-imp');
  let parsed=null;
  const check=()=>{
    const t=$('#m-paste').value.trim(), sum=$('#m-imp-sum');
    parsed=t?parseImport(t):null;
    const ok=!!(parsed&&!parsed.err&&parsed.entries.length);
    $('#m-imerge').disabled=$('#m-ireplace').disabled=!ok;
    if(!parsed){sum.innerHTML='';return}
    if(parsed.err){sum.innerHTML=`<p class="m-bad">${esc(parsed.err)}</p>`;return}
    const cur=new Map(maskRows().filter(r=>r.real).map(r=>[r.real.toLowerCase(),r.fake]));
    let fresh=0, changed=0, same=0;
    for(const e of parsed.entries){const f=cur.get(e.real.toLowerCase());
      if(f==null)fresh++; else if(f===e.fake)same++; else changed++}
    const parts=[];
    if(fresh)parts.push(`<b>${fresh}</b> new`);
    if(changed)parts.push(`<b>${changed}</b> with a different placeholder (the imported one wins)`);
    if(same)parts.push(`<b>${same}</b> already in your list`);
    if(parsed.keep.length)parts.push(`<b>${parsed.keep.length}</b> never-mask ${parsed.keep.length===1?'term':'terms'}`);
    sum.innerHTML=(parts.length?`<p>${parts.join(', ')}.</p>`:'<p class="m-bad">Nothing to import.</p>')+
      (parsed.bad.length?`<p class="m-bad">${parsed.bad.length} left out (they need a real value of 3+ characters and a different placeholder): ${esc(parsed.bad.slice(0,4).join(', '))}${parsed.bad.length>4?'…':''}</p>`:'');
  };
  const apply=replace=>{
    if(!parsed||parsed.err)return;
    if(replace)$('#m-rows').innerHTML='';
    const rows=new Map(maskRows().filter(r=>r.real).map(r=>[r.real.toLowerCase(),r.tr]));
    for(const e of parsed.entries){const tr=rows.get(e.real.toLowerCase());
      if(!tr){addRow(e);continue}
      tr.querySelector('.m-fake').value=e.fake; tr.querySelector('.m-kind').value=e.kind;
      tr.querySelector('.m-on').checked=e.on; tr.classList.toggle('off',!e.on)}
    if(parsed.keep.length){const k=new Set($('#m-keep').value.split('\n').map(s=>s.trim()).filter(Boolean));
      parsed.keep.forEach(x=>k.add(x.trim())); $('#m-keep').value=[...k].filter(Boolean).join('\n')}
    d.close(); maskDirty();
    toast(`Imported ${parsed.entries.length} ${parsed.entries.length===1?'value':'values'}: check them and Save`);
  };
  $('#m-paste').oninput=check;
  $('#m-pick').onclick=()=>{d.close();$('#m-file').click()};
  $('#m-icancel').onclick=()=>d.close();
  $('#m-imerge').onclick=()=>apply(false);
  $('#m-ireplace').onclick=()=>apply(true);
  const drop=$('#m-drop');
  drop.ondragover=e=>{e.preventDefault();drop.classList.add('over')};
  drop.ondragleave=()=>drop.classList.remove('over');
  drop.ondrop=async e=>{e.preventDefault();drop.classList.remove('over');
    const f=e.dataTransfer.files[0]; if(!f)return;
    $('#m-paste').value=await f.text(); drop.querySelector('span').textContent=f.name; check()};
  check();
}
